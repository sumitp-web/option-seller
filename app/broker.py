"""Zerodha Kite access: login, option contracts, prices and market orders."""
import json
import os
import time
from datetime import date

from kiteconnect import KiteConnect

from .config import settings

UNDERLYINGS = {
    # name: (options exchange, spot quote symbol)
    "NIFTY": ("NFO", "NSE:NIFTY 50"),
    "SENSEX": ("BFO", "BSE:SENSEX"),
}


class OrderError(Exception):
    pass


class NotLoggedIn(Exception):
    pass


class KiteBroker:
    def __init__(self) -> None:
        self.kite = KiteConnect(api_key=settings.kite_api_key)
        self._contracts: dict[str, list[dict]] = {}
        self._contracts_day: date | None = None
        self._load_session()

    # --- login -----------------------------------------------------------
    def login_url(self) -> str:
        return self.kite.login_url()

    def complete_login(self, request_token: str) -> None:
        data = self.kite.generate_session(request_token, api_secret=settings.kite_api_secret)
        self.kite.set_access_token(data["access_token"])
        with open(settings.session_file, "w") as f:
            json.dump({"access_token": data["access_token"], "day": date.today().isoformat()}, f)

    def _load_session(self) -> None:
        # Kite tokens expire every morning, so only reuse today's token.
        if not os.path.exists(settings.session_file):
            return
        with open(settings.session_file) as f:
            saved = json.load(f)
        if saved.get("day") == date.today().isoformat():
            self.kite.set_access_token(saved["access_token"])

    @property
    def logged_in(self) -> bool:
        return bool(self.kite.access_token)

    def _require_login(self) -> None:
        if not self.logged_in:
            raise NotLoggedIn()

    # --- market data -----------------------------------------------------
    def contracts(self, underlying: str) -> list[dict]:
        """Option contracts (CE/PE) for an underlying, refreshed once a day."""
        self._require_login()
        if self._contracts_day != date.today():
            self._contracts = {}
            for name, (exchange, _) in UNDERLYINGS.items():
                self._contracts[name] = [
                    i for i in self.kite.instruments(exchange)
                    if i["name"] == name and i["instrument_type"] in ("CE", "PE")
                ]
            self._contracts_day = date.today()
        return self._contracts[underlying]

    def quote(self, keys: list[str]) -> dict[str, dict]:
        """last_price, oi and previous close for each "EXCHANGE:SYMBOL" key."""
        self._require_login()
        if not keys:
            return {}
        out = {}
        for k, v in self.kite.quote(keys).items():
            out[k] = {"ltp": v["last_price"], "oi": v.get("oi") or 0, "close": (v.get("ohlc") or {}).get("close") or 0}
        return out

    # --- orders ----------------------------------------------------------
    def market_order(self, exchange: str, symbol: str, side: str, quantity: int, freeze_qty: int, product: str) -> float:
        """Places a MARKET order (split at the freeze limit) and returns the average fill price."""
        self._require_login()
        filled_value, filled_qty = 0.0, 0
        remaining = quantity
        while remaining > 0:
            qty = min(remaining, freeze_qty)
            try:
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR, exchange=exchange, tradingsymbol=symbol,
                    transaction_type=side, quantity=qty, product=product,
                    order_type=self.kite.ORDER_TYPE_MARKET, market_protection=settings.market_protection,
                    tag="oneclick",
                )
            except Exception as exc:
                raise OrderError(f"{side} {qty} {symbol} rejected: {exc}") from exc
            price = self._wait_for_fill(order_id, f"{side} {qty} {symbol}")
            filled_value += price * qty
            filled_qty += qty
            remaining -= qty
        return filled_value / filled_qty

    def net_quantity(self, exchange: str, symbol: str) -> int:
        """Current net position in the account (negative = short)."""
        self._require_login()
        for pos in self.kite.positions()["net"]:
            if pos["exchange"] == exchange and pos["tradingsymbol"] == symbol:
                return int(pos["quantity"])
        return 0

    def cancel_open_orders(self) -> int:
        """Cancels every pending order in the account (Cancel All Orders / F7)."""
        self._require_login()
        pending = [o for o in self.kite.orders() if o["status"] in ("OPEN", "TRIGGER PENDING", "AMO REQ RECEIVED")]
        for o in pending:
            self.kite.cancel_order(variety=o["variety"], order_id=o["order_id"])
        return len(pending)

    def orders(self) -> list[dict]:
        self._require_login()
        return self.kite.orders()

    def trades(self) -> list[dict]:
        self._require_login()
        return self.kite.trades()

    def profile(self) -> dict:
        self._require_login()
        return self.kite.profile()

    def _wait_for_fill(self, order_id: str, label: str, timeout: float = 15) -> float:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            last = self.kite.order_history(order_id)[-1]
            if last["status"] == "COMPLETE":
                return float(last["average_price"])
            if last["status"] in ("REJECTED", "CANCELLED"):
                raise OrderError(f"{label} {last['status'].lower()}: {last.get('status_message') or ''}".strip())
            time.sleep(0.3)
        raise OrderError(f"{label} not filled within {timeout:.0f}s (order {order_id}); check Kite")
