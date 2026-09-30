from datetime import datetime

from app.broker import DemoBroker
from app.portfolio import IST, build_portfolio
from app.risk import evaluate

NOW = datetime.now(IST).replace(hour=10, minute=0)


def test_groups_legs_by_underlying():
    p = build_portfolio(DemoBroker(), NOW)
    names = [u["underlying"] for u in p["underlyings"]]
    assert names == ["BANKNIFTY", "NIFTY", "SENSEX"]
    assert len(p["underlyings"][0]["legs"]) == 4


def test_short_options_collect_theta():
    p = build_portfolio(DemoBroker(), NOW)
    assert p["totals"]["theta"] > 0
    assert p["totals"]["vega"] < 0


def test_short_strangle_loses_on_big_moves():
    nifty = next(u for u in build_portfolio(DemoBroker(), NOW)["underlyings"] if u["underlying"] == "NIFTY")
    by_move = {s["move_pct"]: s["pnl"] for s in nifty["scenarios"]}
    assert by_move[3] < by_move[0] and by_move[-3] < by_move[0]


def test_alerts_flag_sensex_put_premium_doubling():
    alerts = evaluate(build_portfolio(DemoBroker(), NOW))
    rules = {(a["rule"], a["underlying"]) for a in alerts}
    assert ("premium_multiple", "SENSEX") in rules
    assert alerts[0]["level"] == "critical"
