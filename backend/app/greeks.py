"""Black-Scholes pricing, Greeks and implied volatility for European options."""
import math
from dataclasses import dataclass

SQRT_2PI = math.sqrt(2 * math.pi)


def _cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


@dataclass
class Greeks:
    price: float
    delta: float
    gamma: float
    theta: float  # per calendar day
    vega: float  # per 1 vol point (1%)


def black_scholes(spot: float, strike: float, t: float, r: float, vol: float, is_call: bool) -> Greeks:
    if t <= 0 or vol <= 0:
        intrinsic = max(spot - strike, 0) if is_call else max(strike - spot, 0)
        itm = intrinsic > 0
        delta = (1.0 if is_call else -1.0) if itm else 0.0
        return Greeks(intrinsic, delta, 0.0, 0.0, 0.0)

    sq = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t) / sq
    d2 = d1 - sq
    disc = math.exp(-r * t)
    if is_call:
        price = spot * _cdf(d1) - strike * disc * _cdf(d2)
        delta = _cdf(d1)
        theta = -spot * _pdf(d1) * vol / (2 * math.sqrt(t)) - r * strike * disc * _cdf(d2)
    else:
        price = strike * disc * _cdf(-d2) - spot * _cdf(-d1)
        delta = _cdf(d1) - 1
        theta = -spot * _pdf(d1) * vol / (2 * math.sqrt(t)) + r * strike * disc * _cdf(-d2)
    gamma = _pdf(d1) / (spot * sq)
    vega = spot * _pdf(d1) * math.sqrt(t)
    return Greeks(price, delta, gamma, theta / 365, vega / 100)


def implied_vol(price: float, spot: float, strike: float, t: float, r: float, is_call: bool) -> float | None:
    """Solve for IV by bisection. Returns None when the price is outside the no-arbitrage range."""
    if t <= 0 or price <= 0:
        return None
    lo, hi = 1e-4, 5.0
    if price < black_scholes(spot, strike, t, r, lo, is_call).price:
        return None
    if price > black_scholes(spot, strike, t, r, hi, is_call).price:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if black_scholes(spot, strike, t, r, mid, is_call).price > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-6:
            break
    return (lo + hi) / 2
