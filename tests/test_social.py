import numpy as np
import pandas as pd
import pytest

from horizon_trader.social import archive as S
from horizon_trader.social import event_study as E

TZ = "America/New_York"


def test_snowflake_time_decodes_the_account_creation_date():
    # @aleabitoreddit's user id: the account was created on 2025-07-02
    ts = S.snowflake_time("1940360837547565056")
    assert ts == pd.Timestamp("2025-07-02 10:44:08.489", tz="UTC")


def test_cashtags_skip_amounts_and_duplicates():
    text = "Bought $150k of $nvda and $BRK.B. US$5 target, $NVDA again; $MU/$SNDK. $5.20"
    assert S.cashtags(text) == ["NVDA", "BRK.B", "MU", "SNDK"]


def test_mentions_ignore_retweets_and_quoted_text():
    raw = [
        {"id": "1940361849985458270", "text": "$UPWK", "isRetweet": False},
        {
            "id": "1950361849985458270",
            "text": "$AAA again $UPWK",
            "isRetweet": False,
            "quotedTweet": {"text": "$QQQ from someone else"},
        },  # fmt: skip
        {"id": "1960361849985458270", "text": "RT $ZZZ", "isRetweet": True},
    ]
    m = S.mentions(S.parse_posts(raw))
    assert list(m["ticker"]) == ["UPWK", "AAA", "UPWK"]
    assert list(m["first_mention"]) == [True, True, False]


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz=TZ)


def test_signal_rows_never_act_before_the_post():
    days = pd.DatetimeIndex(["2026-03-05", "2026-03-06", "2026-03-09"])  # Thu, Fri, Mon
    posts = pd.Series(
        [
            _ts("2026-03-06 08:00"),  # pre-market Fri: row Thu, trades Fri's open
            _ts("2026-03-06 09:30"),  # at Fri's open: row Fri, trades Mon
            _ts("2026-03-06 12:00"),  # in session: row Fri
            _ts("2026-03-07 12:00"),  # Saturday: row Fri, trades Mon
        ]
    )
    assert list(E.signal_rows(posts, days)) == [0, 1, 1, 1]


def test_minute_prices_use_only_completed_bars_for_his_price():
    start = _ts("2026-03-06 09:30")
    bars = pd.DataFrame(
        {
            "ts": [start + pd.Timedelta(minutes=i) for i in range(10)],
            "open": np.arange(10) + 100.0,
            "close": np.arange(10) + 100.5,
        }
    )
    out = E.minute_prices(bars, start + pd.Timedelta(minutes=3, seconds=20), lags=(1, 5, 60))
    assert out["ref"] == 102.5  # close of the 9:32 bar; the 9:33 bar isn't finished
    assert out["px_1m"] == 104.0  # open of 9:34
    assert out["px_5m"] == 108.0
    assert np.isnan(out["px_60m"])  # no bar that late


@pytest.mark.parametrize("variant", ["A", "B", "C", "D", "bA", "bB", "bC", "bD"])
def test_targets_are_causal_and_capped(variant):
    rng = np.random.default_rng(3)
    days = pd.bdate_range("2026-01-05", periods=120)
    n = 150
    ev = pd.DataFrame(
        {
            "row": rng.integers(0, 120, n),
            "ticker": rng.choice([f"T{i}" for i in range(25)], n),
        }
    ).sort_values("row", ignore_index=True)
    ev["first_mention"] = ~ev["ticker"].duplicated()
    ev["stance"] = rng.choice(["bullish", "bullish", "bearish", "neutral"], n)
    ev["ts"] = days[ev["row"]] + pd.to_timedelta(rng.integers(0, 86_000, n), unit="s")
    full = E.targets(ev, days, variant)
    assert (full.sum(axis=1) <= 1 + 1e-9).all()
    assert (full.max(axis=1) <= 1 / E.MIN_SLOTS + 1e-9).all()
    t = 70
    cut = E.targets(ev[ev["row"] <= t], days, variant)  # cutting off the future
    pd.testing.assert_series_equal(
        cut.iloc[t].reindex(full.columns, fill_value=0.0), full.iloc[t], check_names=False
    )


def test_forward_returns_measure_from_the_follower_price_with_splits():
    days = pd.bdate_range("2026-01-05", periods=8)
    close = pd.DataFrame({"X": [10, 10, 10, 20, 22, 24, 26, 28.0]}, index=days)
    close[list(E.BENCH)] = 100.0
    factor = pd.DataFrame(1.0, index=days, columns=close.columns)
    factor.loc[: days[2], "X"] = 2.0  # 2-for-1 split on day 3: $10 before = $20 after
    px = {"close": close, "factor": factor, "adj": close * factor}
    ev = pd.DataFrame(
        {"ticker": ["X"], "entry": [1], "entry_mode": ["in session"], "ref": [9.0],
         "px_1m": [10.0], **{f"px_{lag}m": [10.0] for lag in E.LAGS[1:]}}
    )  # fmt: skip
    for b in E.BENCH:
        ev[f"{b}_px_1m"] = 100.0
    out = E.forward_returns(ev, px, horizons=(0, 3))
    assert out["ret_0d"].iloc[0] == pytest.approx(0.0)  # $10 on a $10 close
    assert out["ret_3d"].iloc[0] == pytest.approx(22 / 20 - 1)  # split-adjusted
    assert out["ret_3d_from_his_price"].iloc[0] == pytest.approx(22 / 18 - 1)
    assert out["xs_SMH_3d"].iloc[0] == pytest.approx(0.1)
    assert out["chase_1m"].iloc[0] == pytest.approx(10 / 9 - 1)


def _stance_events(rows: list[tuple[int, str, str]]) -> pd.DataFrame:
    days = pd.bdate_range("2026-01-05", periods=100)
    ev = pd.DataFrame(rows, columns=["row", "ticker", "stance"])
    ev["ts"] = days[ev["row"]] + pd.to_timedelta(np.arange(len(ev)), unit="min")
    return ev


def test_stance_rules_buy_bullish_sell_bearish_ignore_neutral():
    days = pd.bdate_range("2026-01-05", periods=100)
    ev = _stance_events(
        [
            (2, "X", "neutral"),  # nothing
            (5, "X", "bullish"),  # buy
            (8, "X", "neutral"),  # nothing
            (30, "X", "bearish"),  # sell
            (40, "X", "bullish"),  # C buys again; A doesn't (first bullish call only)
            (50, "Y", "bullish"),
            (50, "Y", "bearish"),  # later the same day: the day's call is bearish
        ]
    )
    held_c = E.bullish_held(ev, days, "bC")
    assert not held_c["X"].iloc[:5].any() and held_c["X"].iloc[5:30].all()
    assert not held_c["X"].iloc[30:40].any() and held_c["X"].iloc[40:].all()
    assert not held_c["Y"].any()
    held_a = E.bullish_held(ev, days, "bA")
    assert held_a["X"].iloc[5:30].all() and not held_a["X"].iloc[30:].any()
    held_b = E.bullish_held(ev, days, "bB")
    assert held_b["X"].iloc[5:25].all() and not held_b["X"].iloc[25:40].any()
    assert held_b["X"].iloc[40:60].all() and not held_b["X"].iloc[60:].any()


def test_bullish_first_call_expires_after_the_hold():
    days = pd.bdate_range("2026-01-05", periods=100)
    held = E.bullish_held(_stance_events([(10, "X", "bullish")]), days, "bA")
    assert held["X"].sum() == E.HOLD and held["X"].iloc[10]
