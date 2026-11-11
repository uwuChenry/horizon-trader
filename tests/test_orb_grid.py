from datetime import time

import pandas as pd

from horizon_trader.intraday import orb_grid as G


def test_labels_name_every_parameter():
    assert (
        G.label(1.0, None, 1.0, None) == "stop 1 ATR · hold to close · any relvol · any entry time"
    )
    assert (
        G.label(0.5, 2.0, 8.0, time(10, 30))
        == "stop 0.5 ATR · target 2R · relvol >= 8 · entries by 10:30"
    )


def test_filters_apply_relvol_and_entry_cutoff():
    t0 = pd.Timestamp("2024-03-01 09:40", tz="America/New_York")
    sim = pd.DataFrame(
        {
            "relvol": [3.0, 9.0, 20.0],
            "entry_time": [t0, t0 + pd.Timedelta(hours=1), t0 + pd.Timedelta(minutes=10)],
        }
    )
    assert len(G.filtered(sim, 1.0, None)) == 3
    assert list(G.filtered(sim, 8.0, None)["relvol"]) == [9.0, 20.0]
    assert list(G.filtered(sim, 1.0, time(10))["relvol"]) == [3.0, 20.0]  # 10:40 entry dropped


def test_grid_size_and_baseline_is_in_the_grid():
    assert G.N_CONFIGS == 480
    b = G.BASELINE
    assert b["stop"] in G.STOPS and b["target"] in G.TARGETS
    assert b["relvol"] in G.RELVOLS and b["cutoff"] in G.CUTOFFS
