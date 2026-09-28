import numpy as np
import pandas as pd

from horizon_trader.congress import event_study as C

DAYS = pd.bdate_range("2026-03-02", periods=30)  # Mon 2 Mar ..


def test_signal_rows_use_the_last_trading_day_on_or_before_the_date():
    dates = pd.Series(pd.to_datetime(["2026-03-02", "2026-03-07", "2026-03-08", "2026-03-09"]))
    # Mon -> Mon; Sat and Sun -> Fri (trade Monday's open); Mon -> Mon
    assert list(C.signal_rows(dates, DAYS)) == [0, 4, 4, 5]
    before = C.signal_rows(pd.Series(pd.to_datetime(["2026-02-27"])), DAYS)
    assert before[0] == -1  # before the calendar: dropped by purchases()


def test_held_matrix_starts_at_the_signal_row_for_the_hold():
    ev = pd.DataFrame({"row": [3, 10], "ticker": ["AAA", "AAA"]})
    held = C.held_matrix(ev, DAYS, "row", 5)
    # rows 3-7 and 10-14 (the simulator trades row t at the open of t + 1)
    assert list(np.flatnonzero(held["AAA"])) == [3, 4, 5, 6, 7, 10, 11, 12, 13, 14]
    cut = C.held_matrix(ev[ev["row"] <= 8], DAYS, "row", 5)  # the future doesn't change row 8
    assert cut["AAA"].iloc[:9].equals(held["AAA"].iloc[:9])


def test_pelosi_positions_end_at_her_next_disclosed_sale():
    ev = pd.DataFrame(
        {"row": [2], "row_trade": [0], "ticker": ["NVDA"], "filing_date": [DAYS[2]],
         "transaction_date": [DAYS[0]]}
    )  # fmt: skip
    sells = pd.DataFrame(
        {"ticker": ["NVDA", "AAPL"], "filing_date": [DAYS[12], DAYS[5]],
         "transaction_date": [DAYS[8], DAYS[1]]}
    )  # fmt: skip
    honest = C.pelosi_held(ev, sells, DAYS, lookahead=False)
    assert list(np.flatnonzero(honest["NVDA"])) == list(range(2, 12))  # sale public on day 12
    peek = C.pelosi_held(ev, sells, DAYS, lookahead=True)
    assert list(np.flatnonzero(peek["NVDA"])) == list(range(0, 8))  # trade dates both ways
