"""Turns raw broker positions into legs with Greeks, grouped by underlying."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from .broker import Broker
from .config import settings
from .greeks import black_scholes, implied_vol
from .instruments import spot_symbol

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE = time(15, 30)
FALLBACK_IV = 0.15
SCENARIO_MOVES = [-3, -2, -1, 0, 1, 2, 3]


def years_to_expiry(expiry: date | datetime, now: datetime) -> float:
    if isinstance(expiry, datetime):
        expiry = expiry.date()
    close = datetime.combine(expiry, MARKET_CLOSE, tzinfo=IST)
    return max((close - now).total_seconds(), 0) / (365 * 86400)


def _leg(pos: dict, contract: dict, spot: float | None, now: datetime) -> dict:
    qty = pos["quantity"] * (pos.get("multiplier") or 1)
    kind = contract["instrument_type"]
    leg = {
        "symbol": pos["tradingsymbol"],
        "exchange": pos["exchange"],
        "underlying": contract["name"],
        "type": kind,
        "strike": contract.get("strike") or None,
        "expiry": contract["expiry"].isoformat() if contract.get("expiry") else None,
        "quantity": qty,
        "lots": qty / contract["lot_size"] if contract.get("lot_size") else None,
        "average_price": pos["average_price"],
        "ltp": pos["last_price"],
        "pnl": pos["pnl"],
        "iv": None, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0,
        "days_to_expiry": None,
    }
    if contract.get("expiry"):
        exp = contract["expiry"]
        leg["days_to_expiry"] = ((exp.date() if isinstance(exp, datetime) else exp) - now.date()).days

    if kind == "FUT":
        leg["delta"] = float(qty)
    elif kind in ("CE", "PE") and spot:
        t = years_to_expiry(contract["expiry"], now)
        is_call = kind == "CE"
        iv = implied_vol(pos["last_price"], spot, contract["strike"], t, settings.risk_free_rate, is_call)
        leg["iv"] = iv
        g = black_scholes(spot, contract["strike"], t, settings.risk_free_rate, iv or FALLBACK_IV, is_call)
        leg.update(delta=g.delta * qty, gamma=g.gamma * qty, theta=g.theta * qty, vega=g.vega * qty)
        leg["_model"] = (contract["strike"], t, iv or FALLBACK_IV, is_call)
    return leg


def _scenario_pnl(legs: list[dict], spot: float, move_pct: float) -> float:
    """P&L now if spot moved by move_pct, holding IV and time constant."""
    new_spot = spot * (1 + move_pct / 100)
    total = 0.0
    for leg in legs:
        total += leg["pnl"]
        if leg["type"] == "FUT":
            total += leg["quantity"] * (new_spot - spot)
        elif "_model" in leg:
            strike, t, iv, is_call = leg["_model"]
            new_price = black_scholes(new_spot, strike, t, settings.risk_free_rate, iv, is_call).price
            old_price = black_scholes(spot, strike, t, settings.risk_free_rate, iv, is_call).price
            total += leg["quantity"] * (new_price - old_price)
    return total


def build_portfolio(broker: Broker, now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    contracts = broker.contracts()
    positions = broker.positions()

    fno = [p for p in positions if p["instrument_token"] in contracts]
    spot_by_name = {}
    for p in fno:
        c = contracts[p["instrument_token"]]
        spot_by_name[c["name"]] = spot_symbol(c["name"], c["exchange"])
    quotes = broker.ltp(sorted(set(spot_by_name.values())))

    groups: dict[str, list[dict]] = defaultdict(list)
    realised = 0.0
    for p in fno:
        c = contracts[p["instrument_token"]]
        if p["quantity"] == 0:
            realised += p["pnl"]
            continue
        groups[c["name"]].append(_leg(p, c, quotes.get(spot_by_name[c["name"]]), now))

    underlyings = []
    for name, legs in sorted(groups.items()):
        spot = quotes.get(spot_by_name[name])
        summary = {
            "underlying": name,
            "spot": spot,
            "pnl": sum(l["pnl"] for l in legs),
            "delta": sum(l["delta"] for l in legs),
            "gamma": sum(l["gamma"] for l in legs),
            "theta": sum(l["theta"] for l in legs),
            "vega": sum(l["vega"] for l in legs),
            "scenarios": [
                {"move_pct": m, "pnl": _scenario_pnl(legs, spot, m)} for m in SCENARIO_MOVES
            ] if spot else [],
        }
        for l in legs:
            l.pop("_model", None)
        summary["legs"] = legs
        underlyings.append(summary)

    other = [p for p in positions if p["instrument_token"] not in contracts]
    open_pnl = sum(u["pnl"] for u in underlyings)
    return {
        "as_of": now.isoformat(),
        "totals": {
            "pnl": open_pnl + realised + sum(p["pnl"] for p in other),
            "open_pnl": open_pnl,
            "realised_pnl": realised,
            "theta": sum(u["theta"] for u in underlyings),
            "vega": sum(u["vega"] for u in underlyings),
        },
        "underlyings": underlyings,
        "non_fno_positions": len(other),
    }
