from datetime import datetime

import pytest

from app.engine import IST, Engine, TradeParams
from tests.fakes import FakeBroker


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 1, 10, 0, tzinfo=IST)

    def __call__(self):
        return self.now


def params(**kw):
    base = dict(underlying="NIFTY", expiry="2026-10-06", lots=2,
                leg_sl_points=30, max_loss=10000, tsl_start=0, tsl_lock=0, tsl_step=0, square_off="15:15")
    base.update(kw)
    return TradeParams(**base)


@pytest.fixture
def env():
    b, clock = FakeBroker(), Clock()
    e = Engine(b, freeze_qty={"NIFTY": 1800}, clock=clock)
    return b, e, clock


def tick(b, e):
    e.on_prices({k: q["ltp"] for k, q in b.quote(e.open_keys()).items()})


def strangle(e, ce=26000, pe=25000, **kw):
    p = params(**kw)
    e.sell(p, "CE", ce)
    e.sell(p, "PE", pe)


def open_legs(e):
    return [(l.strike, l.type) for l in e.trade.legs if l.status == "open"]


def test_entry_sells_both_legs_with_sl(env):
    b, e, _ = env
    b.set(26000, "CE", 60); b.set(25000, "PE", 55)
    strangle(e)
    assert b.placed == [("SELL", "NIFTY26OCT26000CE", 150), ("SELL", "NIFTY26OCT25000PE", 150)]
    assert [l.sl_price for l in e.trade.legs] == [90, 85]


def test_leg_sl_hit_buys_back_and_sells_four_strikes_further(env):
    b, e, _ = env
    b.set(25000, "PE", 55)
    strangle(e)
    b.set(25000, "PE", 86); b.set(24800, "PE", 40)
    tick(b, e)
    assert b.placed[-2:] == [("BUY", "NIFTY26OCT25000PE", 150), ("SELL", "NIFTY26OCT24800PE", 150)]
    assert open_legs(e) == [(26000, "CE"), (24800, "PE")]
    new = e.trade.legs[-1]
    assert new.sl_price == 70 and new.shift_no == 1


def test_call_shifts_up_and_repeats(env):
    b, e, _ = env
    b.set(26000, "CE", 60)
    strangle(e, max_loss=50000)
    b.set(26000, "CE", 95); b.set(26200, "CE", 50)
    tick(b, e)
    b.set(26200, "CE", 85); b.set(26400, "CE", 30)
    tick(b, e)
    assert open_legs(e) == [(25000, "PE"), (26400, "CE")]
    assert e.trade.legs[-1].shift_no == 2


def test_max_loss_includes_booked_losses_and_exits_everything(env):
    b, e, _ = env
    b.set(26000, "CE", 60); b.set(25000, "PE", 55)
    strangle(e, max_loss=5000, leg_sl_points=20)
    b.set(25000, "PE", 80); b.set(24800, "PE", 40)  # SL: -25*150 = -3750 booked
    tick(b, e)
    assert e.trade.status == "running"
    b.set(24800, "PE", 50)  # another -1500 open -> -5250
    tick(b, e)
    assert e.trade.status == "closed"
    assert "Max loss" in e.trade.exit_reason
    assert not open_legs(e)


def test_tsl_locks_profit_trails_and_exits(env):
    b, e, _ = env
    b.set(26000, "CE", 60); b.set(25000, "PE", 60)
    strangle(e, tsl_start=3000, tsl_lock=1500, tsl_step=500, max_loss=50000)
    b.set(26000, "CE", 50); b.set(25000, "PE", 50)  # +3000
    tick(b, e)
    assert e.trade.tsl_floor == 1500
    b.set(26000, "CE", 45); b.set(25000, "PE", 45)  # +4500 -> floor 1500 + 3*500
    tick(b, e)
    assert e.trade.tsl_floor == 3000
    b.set(26000, "CE", 52); b.set(25000, "PE", 50)  # +2700 <= 3000
    tick(b, e)
    assert e.trade.status == "closed" and "TSL" in e.trade.exit_reason


def test_square_off_time_exits(env):
    b, e, clock = env
    strangle(e, square_off="15:15")
    clock.now = clock.now.replace(hour=15, minute=15)
    tick(b, e)
    assert e.trade.status == "closed" and "Square-off" in e.trade.exit_reason


def test_failed_exit_is_retried_next_tick(env):
    b, e, _ = env
    strangle(e)
    b.reject.add(("NIFTY26OCT26000CE", "BUY"))
    e.exit_all("Manual")
    assert e.trade.status == "exiting"
    b.reject.clear()
    tick(b, e)
    assert e.trade.status == "closed"


def test_rejects_second_trade_and_bad_inputs(env):
    b, e, clock = env
    with pytest.raises(ValueError, match="not listed"):
        e.sell(params(), "CE", 26025)
    strangle(e)
    with pytest.raises(ValueError, match="is running"):
        e.sell(params(expiry="2026-10-13"), "CE", 26000)
    e.exit_all()
    clock.now = clock.now.replace(hour=15, minute=20)
    with pytest.raises(ValueError, match="square-off"):
        strangle(e)


def test_state_survives_restart(tmp_path):
    b = FakeBroker()
    path = str(tmp_path / "state.json")
    clock = Clock()
    strangle(Engine(b, {"NIFTY": 1800}, path, clock))
    again = Engine(b, {"NIFTY": 1800}, path, clock)
    assert again.trade.status == "running" and len(again.trade.legs) == 2


def test_buy_call_buys_back_open_calls_only(env):
    b, e, _ = env
    strangle(e)
    e.buy("CE")
    assert b.placed[-1] == ("BUY", "NIFTY26OCT26000CE", 150)
    assert open_legs(e) == [(25000, "PE")]
    with pytest.raises(ValueError, match="no open short call"):
        e.buy("CE")
    e.buy("PE")
    assert e.trade.status == "closed"


def test_second_sell_adds_a_leg_to_the_running_trade(env):
    b, e, _ = env
    strangle(e)
    e.sell(params(lots=1), "CE", 26100)
    assert open_legs(e) == [(26000, "CE"), (25000, "PE"), (26100, "CE")]
    assert e.trade.legs[-1].quantity == 75


def test_leg_closed_in_kite_is_not_bought_again(env):
    b, e, _ = env
    strangle(e)
    b.placed.append(("BUY", "NIFTY26OCT26000CE", 150))  # user closed the call in Kite
    e.exit_all("Manual")
    buys = [o for o in b.placed if o[0] == "BUY" and o[1] == "NIFTY26OCT26000CE"]
    assert len(buys) == 1
    assert e.trade.legs[0].exit_reason == "Closed outside app"
    assert e.trade.status == "closed"


def test_start_sells_both_selected_strikes(env):
    b, e, _ = env
    e.start(params(lots=3), 26000, 25000)
    assert b.placed == [("SELL", "NIFTY26OCT26000CE", 225), ("SELL", "NIFTY26OCT25000PE", 225)]


def test_start_places_nothing_if_a_strike_is_not_listed(env):
    b, e, _ = env
    with pytest.raises(ValueError, match="25010 PE is not listed"):
        e.start(params(), 26000, 25010)
    assert b.placed == []
