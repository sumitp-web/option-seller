from datetime import date

from app.broker import OrderError


class FakeBroker:
    """NIFTY chain with 50-point strikes; prices set by the test, orders fill at the current price."""

    logged_in = True

    def __init__(self, expiry=date(2026, 10, 6)):
        self.expiry = expiry
        self.prices: dict[str, float] = {"NSE:NIFTY 50": 25500.0}
        self.placed: list[tuple] = []
        self.reject: set[tuple] = set()
        self._contracts = []
        for strike in range(24000, 27050, 50):
            for typ in ("CE", "PE"):
                sym = f"NIFTY26OCT{strike}{typ}"
                self._contracts.append({
                    "tradingsymbol": sym, "exchange": "NFO", "name": "NIFTY", "expiry": expiry,
                    "strike": float(strike), "instrument_type": typ, "lot_size": 75,
                })
                self.prices[f"NFO:{sym}"] = 50.0

    def set(self, strike, typ, price):
        self.prices[f"NFO:NIFTY26OCT{strike}{typ}"] = price

    def contracts(self, underlying):
        return self._contracts if underlying == "NIFTY" else []

    def quote(self, keys):
        return {k: {"ltp": self.prices[k], "oi": 1000, "close": self.prices[k]} for k in keys if k in self.prices}

    def market_order(self, exchange, symbol, side, quantity, freeze_qty, product):
        if (symbol, side) in self.reject:
            raise OrderError(f"{side} {symbol} rejected")
        self.placed.append((side, symbol, quantity))
        return self.prices[f"{exchange}:{symbol}"]

    def net_quantity(self, exchange, symbol):
        return sum((-q if side == "SELL" else q) for side, sym, q in self.placed if sym == symbol)

    def cancel_open_orders(self):
        return 0

    def profile(self):
        return {"user_id": "AB1234"}

    def orders(self):
        return [{"tradingsymbol": sym, "order_type": "MARKET", "transaction_type": side, "quantity": qty,
                 "pending_quantity": 0, "average_price": 0, "status": "COMPLETE", "order_timestamp": "2026-10-01 10:00:00",
                 "order_id": str(i), "status_message": None} for i, (side, sym, qty) in enumerate(self.placed)]

    def trades(self):
        return []
