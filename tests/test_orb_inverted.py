import numpy as np
import pytest

from horizon_trader.intraday import orb
from horizon_trader.intraday import orb_inverted as I


def _random_bars(seed: int, n: int = 120):
    rng = np.random.default_rng(seed)
    c = 10 + np.cumsum(rng.normal(0, 0.05, n))
    o = np.r_[10.0, c[:-1]] + rng.normal(0, 0.02, n) * (rng.random(n) < 0.1)  # some gaps
    h = np.maximum(o, c) + rng.uniform(0, 0.06, n)
    lo = np.minimum(o, c) - rng.uniform(0, 0.06, n)
    return o, h, lo, c


@pytest.mark.parametrize("seed", range(40))
def test_walker_reproduces_orb_path_mode(seed):
    o, h, lo, c = _random_bars(seed)
    for side in (1, -1):
        level = 10.05 if side > 0 else 9.95
        ref = orb.simulate_trade(o, h, lo, c, side, level, 0.1, 10.5)
        mine = I.simulate(o, h, lo, c, side, level, side > 0, 0.1, None, 10.5)
        assert (ref is None) == (mine is None)
        if ref is not None:
            assert mine["entry_idx"] == ref["entry_idx"]
            assert mine["entry_px"] == pytest.approx(ref["entry_px"])
            assert mine["exit_px"] == pytest.approx(ref["exit_px_path"])
            assert mine["exit_idx"] == ref["exit_idx_path"]


@pytest.mark.parametrize("seed", range(40))
def test_mirror_is_exactly_minus_orb(seed):
    o, h, lo, c = _random_bars(seed)
    level = 10.05
    fwd = I.simulate(o, h, lo, c, 1, level, True, 0.1, None, 10.5)
    inv = I.simulate(o, h, lo, c, -1, level, True, None, 0.1, 10.5)
    assert (fwd is None) == (inv is None)
    if fwd is not None:
        assert inv["entry_px"] == fwd["entry_px"] and inv["exit_px"] == pytest.approx(
            fwd["exit_px"]
        )


def test_fade_short_with_stop_and_target():
    # breakout to 10.5, fade short there; bar 2 drops through the 10.0 target
    o = np.array([10.3, 10.5, 10.2])
    h = np.array([10.45, 10.6, 10.25])
    lo = np.array([10.25, 10.4, 9.9])
    c = np.array([10.4, 10.45, 9.95])
    res = I.simulate(o, h, lo, c, -1, 10.5, True, 0.5, 0.5, 9.0)
    assert res["entry_idx"] == 1 and res["entry_px"] == 10.5  # gapped to exactly the level
    assert res["reason"] == "target" and res["exit_px"] == 10.0 and res["exit_idx"] == 2


def test_a_gap_through_the_target_fills_at_the_better_open():
    o = np.array([10.4, 9.7])
    h = np.array([10.55, 9.8])
    lo = np.array([10.35, 9.6])
    c = np.array([10.5, 9.75])
    res = I.simulate(o, h, lo, c, -1, 10.5, True, 1.0, 0.5, 9.0)
    assert res["reason"] == "target" and res["exit_px"] == 9.7  # better than the 10.0 limit


def test_no_trigger_returns_none():
    o, h, lo, c = (np.full(5, 10.0) for _ in range(4))
    assert I.simulate(o, h, lo, c, -1, 11.0, True, 1.0, None, 10.0) is None
