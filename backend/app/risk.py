"""Risk rules evaluated against a built portfolio. Each rule yields alerts."""
from .config import settings


def _alert(level: str, rule: str, message: str, underlying: str | None = None, symbol: str | None = None) -> dict:
    return {"level": level, "rule": rule, "message": message, "underlying": underlying, "symbol": symbol}


def evaluate(portfolio: dict) -> list[dict]:
    alerts = []
    total = portfolio["totals"]["pnl"]
    if total <= -settings.max_portfolio_loss:
        alerts.append(_alert("critical", "max_portfolio_loss",
                             f"Portfolio loss ₹{-total:,.0f} is past the ₹{settings.max_portfolio_loss:,.0f} limit"))

    for u in portfolio["underlyings"]:
        name, spot = u["underlying"], u["spot"]
        if u["pnl"] <= -settings.max_loss_per_underlying:
            alerts.append(_alert("critical", "max_loss_per_underlying",
                                 f"{name} loss ₹{-u['pnl']:,.0f} is past the ₹{settings.max_loss_per_underlying:,.0f} limit", name))
        if abs(u["delta"]) > settings.max_abs_delta_per_underlying:
            side = "long" if u["delta"] > 0 else "short"
            alerts.append(_alert("warning", "delta_limit",
                                 f"{name} net delta {u['delta']:+.0f} is too {side} (limit ±{settings.max_abs_delta_per_underlying:.0f})", name))

        for leg in u["legs"]:
            if leg["type"] not in ("CE", "PE") or leg["quantity"] >= 0:
                continue
            sym, strike = leg["symbol"], leg["strike"]
            if spot:
                # Distance of spot past the short strike, positive when breached.
                past = (spot - strike) if leg["type"] == "CE" else (strike - spot)
                buffer = strike * settings.breach_buffer_pct / 100
                if past >= 0:
                    alerts.append(_alert("critical", "short_strike_breached",
                                         f"{sym} is in the money: spot {spot:,.1f} vs strike {strike:,.0f}", name, sym))
                elif past > -buffer:
                    alerts.append(_alert("warning", "short_strike_near",
                                         f"{sym} strike is within {settings.breach_buffer_pct}% of spot {spot:,.1f}", name, sym))
            if leg["average_price"] > 0 and leg["ltp"] >= settings.premium_multiple_alert * leg["average_price"]:
                alerts.append(_alert("critical", "premium_multiple",
                                     f"{sym} premium {leg['ltp']:.1f} is {leg['ltp'] / leg['average_price']:.1f}x the {leg['average_price']:.1f} sold at", name, sym))
            if leg["days_to_expiry"] == 0:
                alerts.append(_alert("info", "expiry_today", f"{sym} expires today", name, sym))

    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(alerts, key=lambda a: order[a["level"]])
