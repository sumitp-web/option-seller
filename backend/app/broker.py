"""Broker access. KiteBroker talks to Zerodha; DemoBroker serves sample data offline."""
import json
import os
from datetime import date, timedelta
from typing import Protocol

from kiteconnect import KiteConnect

from .config import settings
from .instruments import FNO_EXCHANGES


class Broker(Protocol):
    def positions(self) -> list[dict]: ...
    def ltp(self, symbols: list[str]) -> dict[str, float]: ...
    def contracts(self) -> dict[int, dict]: ...


class NotLoggedIn(Exception):
    pass


class KiteBroker:
    def __init__(self) -> None:
        self.kite = KiteConnect(api_key=settings.kite_api_key)
        self._contracts: dict[int, dict] = {}
        self._contracts_day: date | None = None
        self._load_session()

    # --- login -----------------------------------------------------------
    def login_url(self) -> str:
        return self.kite.login_url()

    def complete_login(self, request_token: str) -> dict:
        data = self.kite.generate_session(request_token, api_secret=settings.kite_api_secret)
        self.kite.set_access_token(data["access_token"])
        with open(settings.session_file, "w") as f:
            json.dump({"access_token": data["access_token"], "day": date.today().isoformat()}, f)
        return {"user_id": data.get("user_id"), "user_name": data.get("user_name")}

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

    # --- data ------------------------------------------------------------
    def _require_login(self) -> None:
        if not self.logged_in:
            raise NotLoggedIn()

    def positions(self) -> list[dict]:
        self._require_login()
        return self.kite.positions()["net"]

    def ltp(self, symbols: list[str]) -> dict[str, float]:
        self._require_login()
        if not symbols:
            return {}
        return {k: v["last_price"] for k, v in self.kite.ltp(symbols).items()}

    def contracts(self) -> dict[int, dict]:
        """NFO + BFO instrument master keyed by instrument_token, refreshed daily."""
        self._require_login()
        if self._contracts_day != date.today():
            rows: dict[int, dict] = {}
            for exchange in FNO_EXCHANGES:
                for inst in self.kite.instruments(exchange):
                    rows[inst["instrument_token"]] = inst
            self._contracts = rows
            self._contracts_day = date.today()
        return self._contracts


def _next_weekday(weekday: int) -> date:
    today = date.today()
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


class DemoBroker:
    """A short NIFTY strangle, a BANKNIFTY iron condor and a SENSEX short put."""

    logged_in = True

    def __init__(self) -> None:
        nifty_exp = _next_weekday(1)  # Tuesday
        bn_exp = _next_weekday(1) + timedelta(days=21)
        sensex_exp = _next_weekday(3)  # Thursday
        legs = [
            (1, "NFO", "NIFTY", nifty_exp, 26000, "CE", 75, -150, 62.0, 48.5),
            (2, "NFO", "NIFTY", nifty_exp, 25000, "PE", 75, -150, 58.0, 71.0),
            (3, "NFO", "BANKNIFTY", bn_exp, 57500, "CE", 35, -70, 210.0, 185.0),
            (4, "NFO", "BANKNIFTY", bn_exp, 58500, "CE", 35, 70, 75.0, 60.0),
            (5, "NFO", "BANKNIFTY", bn_exp, 54500, "PE", 35, -70, 190.0, 240.0),
            (6, "NFO", "BANKNIFTY", bn_exp, 53500, "PE", 35, 70, 70.0, 95.0),
            (7, "BFO", "SENSEX", sensex_exp, 80500, "PE", 20, -40, 95.0, 205.0),
        ]
        self._contracts = {}
        self._positions = []
        for token, exch, name, exp, strike, typ, lot, qty, avg, ltp in legs:
            symbol = f"{name}{exp:%y%b}{strike}{typ}".upper()
            self._contracts[token] = {
                "instrument_token": token, "tradingsymbol": symbol, "name": name, "exchange": exch,
                "expiry": exp, "strike": float(strike), "instrument_type": typ, "lot_size": lot,
            }
            self._positions.append({
                "instrument_token": token, "tradingsymbol": symbol, "exchange": exch, "product": "NRML",
                "quantity": qty, "average_price": avg, "last_price": ltp, "multiplier": 1,
                "pnl": (ltp - avg) * qty,
            })
        self._spots = {"NSE:NIFTY 50": 25480.0, "NSE:NIFTY BANK": 55900.0, "BSE:SENSEX": 80650.0}

    def positions(self) -> list[dict]:
        return self._positions

    def ltp(self, symbols: list[str]) -> dict[str, float]:
        return {s: self._spots[s] for s in symbols if s in self._spots}

    def contracts(self) -> dict[int, dict]:
        return self._contracts
