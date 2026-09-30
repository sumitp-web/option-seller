"""Runs one short strangle: entry, per-leg SL with 4-strike shift, max loss, profit TSL, square-off."""
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from .broker import UNDERLYINGS, OrderError

IST = timezone(timedelta(hours=5, minutes=30))
SHIFT_STRIKES = 4


@dataclass
class TradeParams:
    underlying: str
    expiry: str
    lots: int
    leg_sl_points: float
    max_loss: float
    tsl_start: float = 0
    tsl_lock: float = 0
    tsl_step: float = 0
    square_off: str = "15:15"
    product: str = "NRML"


@dataclass
class Leg:
    id: str
    type: str
    strike: float
    symbol: str
    exchange: str
    quantity: int
    sell_price: float
    sl_price: float
    shift_no: int = 0
    status: str = "open"  # open | closed
    ltp: float | None = None
    buy_price: float | None = None
    exit_reason: str | None = None

    def pnl(self) -> float:
        last = self.buy_price if self.status == "closed" else self.ltp
        return 0.0 if last is None else (self.sell_price - last) * self.quantity


@dataclass
class Trade:
    params: TradeParams
    lot_size: int
    status: str = "running"  # running | exiting | closed
    legs: list[Leg] = field(default_factory=list)
    tsl_floor: float | None = None
    exit_reason: str | None = None
    log: list[dict] = field(default_factory=list)

    def pnl(self) -> float:
        return sum(l.pnl() for l in self.legs)

    def booked(self) -> float:
        return sum(l.pnl() for l in self.legs if l.status == "closed")


def now_ist() -> datetime:
    return datetime.now(IST)


class Engine:
    def __init__(self, broker, freeze_qty: dict[str, int], state_file: str | None = None, clock=now_ist) -> None:
        self.broker = broker
        self.freeze_qty = freeze_qty
        self.state_file = state_file
        self.clock = clock
        self.trade: Trade | None = None
        self.lock = threading.RLock()
        self._load()

    # --- contracts -------------------------------------------------------
    def chain_contracts(self, underlying: str, expiry: str) -> dict[tuple[float, str], dict]:
        exp = date.fromisoformat(expiry)
        return {
            (float(c["strike"]), c["instrument_type"]): c
            for c in self.broker.contracts(underlying)
            if (c["expiry"].date() if isinstance(c["expiry"], datetime) else c["expiry"]) == exp
        }

    def expiries(self, underlying: str) -> list[str]:
        today = self.clock().date()
        days = {c["expiry"].date() if isinstance(c["expiry"], datetime) else c["expiry"] for c in self.broker.contracts(underlying)}
        return [d.isoformat() for d in sorted(d for d in days if d >= today)]

    def lot_size(self, underlying: str) -> int:
        return int(self.broker.contracts(underlying)[0]["lot_size"])

    # --- actions ---------------------------------------------------------
    def sell(self, p: TradeParams, typ: str, strike: float) -> Trade:
        """One-click sell of a call or put. The first sell of the day starts a trade; later sells add legs."""
        with self.lock:
            if typ not in ("CE", "PE"):
                raise ValueError("Type must be CE or PE.")
            if p.underlying not in UNDERLYINGS:
                raise ValueError("Only NIFTY and SENSEX are supported.")
            if p.lots < 1 or p.leg_sl_points <= 0 or p.max_loss <= 0:
                raise ValueError("Lots, leg SL and max loss must all be above zero.")
            if p.tsl_start and p.tsl_lock >= p.tsl_start:
                raise ValueError("The locked profit must be less than the TSL start profit.")
            if self.clock().time() >= self._square_off_time(p):
                raise ValueError(f"It is past the square-off time ({p.square_off}).")
            t = self.trade
            if t and t.status == "exiting":
                raise ValueError("Positions are being closed. Wait for that to finish.")
            if t and t.status == "running" and (t.params.underlying, t.params.expiry) != (p.underlying, p.expiry):
                raise ValueError(f"A {t.params.underlying} {t.params.expiry} trade is running. Close it before switching.")
            contract = self.chain_contracts(p.underlying, p.expiry).get((float(strike), typ))
            if not contract:
                raise ValueError(f"{p.underlying} {strike:g} {typ} is not listed for {p.expiry}.")

            if not t or t.status == "closed":
                self.trade = Trade(params=p, lot_size=self.lot_size(p.underlying))
            else:
                self.trade.params = p  # latest risk settings apply to the whole trade
            self._sell_leg(contract, shift_no=0, qty=p.lots * self.trade.lot_size)
            if not self.trade.legs:
                self.trade.status = "closed"
                self.trade.exit_reason = "Entry failed"
            self._save()
            return self.trade

    def buy(self, typ: str) -> None:
        """Buy Call / Buy Put: buy back every open short leg of that type."""
        with self.lock:
            t = self.trade
            legs = [l for l in t.legs if l.status == "open" and l.type == typ] if t else []
            if not legs:
                raise ValueError(f"There is no open short {'call' if typ == 'CE' else 'put'} to buy back.")
            for leg in legs:
                self._buy_back(leg, "Manual")
            self._close_if_flat("Manual")
            self._save()

    def exit_all(self, reason: str = "Manual") -> None:
        with self.lock:
            t = self.trade
            if not t or t.status == "closed":
                return
            if t.status != "exiting":
                t.status = "exiting"
                t.exit_reason = reason
                self._log(f"Exiting all legs: {reason}")
            for leg in [l for l in t.legs if l.status == "open"]:
                self._buy_back(leg, reason)
            if all(l.status == "closed" for l in t.legs):
                t.status = "closed"
                self._log(f"Trade closed ({reason}). Final P&L ₹{t.pnl():,.0f}")
            self._save()

    def exit_leg(self, leg_id: str) -> None:
        with self.lock:
            t = self.trade
            leg = next((l for l in t.legs if l.id == leg_id), None) if t else None
            if not leg or leg.status != "open":
                raise ValueError("That leg is not open.")
            self._buy_back(leg, "Manual")
            self._close_if_flat("Manual")
            self._save()

    def _close_if_flat(self, reason: str) -> None:
        t = self.trade
        if t.status == "running" and not any(l.status == "open" for l in t.legs):
            t.status = "closed"
            t.exit_reason = reason
            self._log(f"All legs closed. Final P&L ₹{t.pnl():,.0f}")

    # --- monitoring ------------------------------------------------------
    def open_keys(self) -> list[str]:
        t = self.trade
        if not t or t.status == "closed":
            return []
        return [f"{l.exchange}:{l.symbol}" for l in t.legs if l.status == "open"]

    def on_prices(self, ltp: dict[str, float]) -> None:
        """Called every tick with the latest LTPs; applies all exit rules."""
        with self.lock:
            t = self.trade
            if not t or t.status == "closed":
                return
            if t.status == "exiting":  # retry legs whose exit failed
                self.exit_all(t.exit_reason or "Retry")
                return
            for leg in t.legs:
                key = f"{leg.exchange}:{leg.symbol}"
                if leg.status == "open" and key in ltp:
                    leg.ltp = ltp[key]

            p = t.params
            if self.clock().time() >= self._square_off_time(p):
                self.exit_all(f"Square-off {p.square_off}")
                return

            for leg in [l for l in t.legs if l.status == "open" and l.ltp is not None]:
                if leg.ltp >= leg.sl_price:
                    self._log(f"{leg.strike:g} {leg.type} SL hit: LTP {leg.ltp:.2f} ≥ SL {leg.sl_price:.2f}")
                    if self._buy_back(leg, "SL"):
                        self._shift(leg)

            pnl = t.pnl()
            if pnl <= -p.max_loss:
                self.exit_all(f"Max loss ₹{p.max_loss:,.0f} reached")
                return
            if p.tsl_start > 0 and pnl >= p.tsl_start:
                steps = int((pnl - p.tsl_start) // p.tsl_step) if p.tsl_step > 0 else 0
                floor = p.tsl_lock + steps * p.tsl_step
                if t.tsl_floor is None or floor > t.tsl_floor:
                    t.tsl_floor = floor
                    self._log(f"TSL: profit locked at ₹{floor:,.0f}")
            if t.tsl_floor is not None and pnl <= t.tsl_floor:
                self.exit_all(f"TSL hit at ₹{t.tsl_floor:,.0f}")
                return
            self._save()

    # --- internals -------------------------------------------------------
    def _square_off_time(self, p: TradeParams) -> time:
        h, m = p.square_off.split(":")
        return time(int(h), int(m))

    def _order(self, exchange: str, symbol: str, side: str, qty: int) -> float:
        p = self.trade.params
        return self.broker.market_order(exchange, symbol, side, qty, self.freeze_qty[p.underlying], p.product)

    def _sell_leg(self, contract: dict, shift_no: int, qty: int) -> Leg | None:
        t = self.trade
        typ, strike = contract["instrument_type"], float(contract["strike"])
        try:
            price = self._order(contract["exchange"], contract["tradingsymbol"], "SELL", qty)
        except OrderError as exc:
            self._log(f"Could not sell {strike:g} {typ}: {exc}", "error")
            return None
        leg = Leg(
            id=uuid.uuid4().hex[:8], type=typ, strike=strike, symbol=contract["tradingsymbol"],
            exchange=contract["exchange"], quantity=qty, sell_price=price,
            sl_price=round(price + t.params.leg_sl_points, 2), shift_no=shift_no, ltp=price,
        )
        t.legs.append(leg)
        self._log(f"Sold {qty} {strike:g} {typ} at {price:.2f}, SL {leg.sl_price:.2f}")
        return leg

    def _buy_back(self, leg: Leg, reason: str) -> bool:
        try:
            # Never buy more than is actually short, so a leg closed in Kite does not turn into a long.
            short = -self.broker.net_quantity(leg.exchange, leg.symbol)
            if short <= 0:
                leg.status, leg.buy_price, leg.exit_reason = "closed", leg.ltp, "Closed outside app"
                self._log(f"{leg.strike:g} {leg.type} is no longer short in your account; marked closed without an order", "error")
                return True
            price = self._order(leg.exchange, leg.symbol, "BUY", min(leg.quantity, short))
        except OrderError as exc:
            self._log(f"Could not buy back {leg.strike:g} {leg.type}, will retry: {exc}", "error")
            return False
        leg.status, leg.buy_price, leg.exit_reason = "closed", price, reason
        self._log(f"Bought back {leg.quantity} {leg.strike:g} {leg.type} at {price:.2f} ({reason}), P&L ₹{leg.pnl():,.0f}")
        return True

    def _shift(self, leg: Leg) -> None:
        p = self.trade.params
        contracts = self.chain_contracts(p.underlying, p.expiry)
        strikes = sorted(s for (s, typ) in contracts if typ == leg.type)
        i = strikes.index(leg.strike)
        j = i + SHIFT_STRIKES if leg.type == "CE" else i - SHIFT_STRIKES
        if not 0 <= j < len(strikes):
            self._log(f"No strike {SHIFT_STRIKES} away from {leg.strike:g} {leg.type}; leg not replaced", "error")
            return
        self._log(f"Shifting {leg.type} from {leg.strike:g} to {strikes[j]:g}")
        self._sell_leg(contracts[(strikes[j], leg.type)], shift_no=leg.shift_no + 1, qty=leg.quantity)

    def _log(self, message: str, level: str = "info") -> None:
        self.trade.log.append({"time": self.clock().strftime("%H:%M:%S"), "message": message, "level": level})
        self.trade.log = self.trade.log[-300:]

    # --- persistence -----------------------------------------------------
    def snapshot(self) -> dict | None:
        t = self.trade
        if not t:
            return None
        d = asdict(t)
        d["pnl"] = t.pnl()
        d["booked_pnl"] = t.booked()
        for leg, raw in zip(t.legs, d["legs"]):
            raw["pnl"] = leg.pnl()
        return d

    def _save(self) -> None:
        if not self.state_file or not self.trade:
            return
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(asdict(self.trade), f)
        os.replace(tmp, self.state_file)

    def _load(self) -> None:
        if not self.state_file or not os.path.exists(self.state_file):
            return
        with open(self.state_file) as f:
            raw = json.load(f)
        raw["params"] = TradeParams(**raw["params"])
        raw["legs"] = [Leg(**l) for l in raw["legs"]]
        self.trade = Trade(**raw)
