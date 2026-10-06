import numpy as np
import pandas as pd

from horizon_trader.intraday.orb_shortlist import coverage, in_list, restrict

DAYS = pd.to_datetime(["2026-01-05", "2026-01-06"])


def test_in_list_ranks_each_day_and_ignores_ineligible():
    score = pd.DataFrame({"A": [3.0, 1.0], "B": [2.0, np.nan], "C": [1.0, 5.0]}, index=DAYS)
    member = in_list(score, 2)
    assert member.loc[DAYS[0]].tolist() == [True, True, False]
    assert member.loc[DAYS[1]].tolist() == [True, False, True]  # NaN = not eligible


def test_restrict_reranks_and_coverage_counts_top1():
    trades = pd.DataFrame(
        {"date": [DAYS[0]] * 3 + [DAYS[1]], "ticker": ["A", "B", "C", "A"], "rank": [1, 2, 3, 1]}
    )
    member = pd.DataFrame({"A": [False, True], "B": [True, False], "C": [True, False]}, index=DAYS)
    t = restrict(trades, member)
    assert t[t["date"] == DAYS[0]].set_index("ticker")["rank"].to_dict() == {"B": 1, "C": 2}
    assert t[t["date"] == DAYS[1]]["ticker"].tolist() == ["A"]
    assert coverage(trades[trades["rank"] == 1], member) == 0.5  # day 1 misses A, day 2 has it
