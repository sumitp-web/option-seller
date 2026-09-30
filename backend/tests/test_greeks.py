import pytest

from app.greeks import black_scholes, implied_vol


def test_put_call_parity():
    s, k, t, r, v = 25000, 25200, 30 / 365, 0.065, 0.14
    call = black_scholes(s, k, t, r, v, True)
    put = black_scholes(s, k, t, r, v, False)
    import math
    assert call.price - put.price == pytest.approx(s - k * math.exp(-r * t), abs=1e-6)
    assert call.delta - put.delta == pytest.approx(1.0)
    assert call.gamma == pytest.approx(put.gamma)


def test_short_dated_otm_call_has_small_delta_and_negative_theta():
    g = black_scholes(25000, 26000, 7 / 365, 0.065, 0.12, True)
    assert 0 < g.delta < 0.1
    assert g.theta < 0


def test_implied_vol_round_trip():
    price = black_scholes(55900, 54500, 21 / 365, 0.065, 0.18, False).price
    assert implied_vol(price, 55900, 54500, 21 / 365, 0.065, False) == pytest.approx(0.18, abs=1e-4)


def test_implied_vol_rejects_price_below_intrinsic():
    assert implied_vol(10, 25000, 26000, 7 / 365, 0.065, False) is None


def test_expired_option_is_intrinsic():
    g = black_scholes(25100, 25000, 0, 0.065, 0.15, True)
    assert g.price == 100 and g.delta == 1.0
