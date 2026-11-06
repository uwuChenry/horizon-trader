from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from horizon_trader.social import brick as B
from horizon_trader.social import discord as D

TZ = "America/New_York"
HOLIDAYS = {date(2025, 4, 18), date(2025, 7, 4), date(2026, 6, 19), date(2025, 12, 25)}


def _cal() -> B.Calendar:
    d, days = date(2024, 12, 1), []
    while d <= date(2026, 11, 4):
        if d.weekday() < 5 and d not in HOLIDAYS:
            days.append(d)
        d += timedelta(days=1)
    return B.Calendar(days)


CAL = _cal()


def _one(line: str, posted: date) -> dict:
    specs = B.parse_line(line, posted, CAL)
    assert len(specs) == 1, specs
    return specs[0]


# ---------------------------------------------------------------- discord loader


def test_snowflake_time_is_the_channel_creation_time():
    assert D.snowflake_time("1315498906036994129") == pd.Timestamp(
        "2024-12-09 02:02:59.987", tz="UTC"
    )


def test_parse_export_reads_replies_edits_and_checks_timestamps():
    raw = {
        "messages": [
            {
                "id": "1315498906036994129",
                "timestamp": "2024-12-08T21:02:59.987-05:00",
                "timestampEdited": None,
                "content": "hi",
                "author": {"name": "a", "isBot": False},
                "attachments": [],
                "embeds": [],
            },
            {
                "id": "1315498906036994130",
                "timestamp": "2024-12-08T21:02:59.987-05:00",
                "timestampEdited": "2024-12-08T21:05:00-05:00",
                "content": "re",
                "author": {"name": "b", "isBot": True},
                "reference": {"messageId": "1315498906036994129"},
                "attachments": [{}],
                "embeds": [],
            },
        ]
    }
    df = D.parse_export(raw)
    assert list(df["reply_to"]) == [None, "1315498906036994129"]
    assert df["edited_ts"].notna().tolist() == [False, True]
    assert str(df["ts"].dt.tz) == TZ
    raw["messages"][0]["timestamp"] = "2024-12-08T22:00:00-05:00"
    with pytest.raises(ValueError):
        D.parse_export(raw)


# ---------------------------------------------------------------- formats


@pytest.mark.parametrize(
    "line,posted,want",
    [
        ("NBIS 60c 8/15 1.7", date(2025, 8, 5), ("NBIS", 60, "c", date(2025, 8, 15), 1.7)),
        ("UBER 65p 12/18 1.78", date(2026, 11, 5), ("UBER", 65, "p", date(2026, 12, 18), 1.78)),
        ("RKLB 6/18 90C 5.05 added", date(2026, 4, 15), ("RKLB", 90, "c", date(2026, 6, 18), 5.05)),
        ("CCL 22c 0.67 4/17", date(2025, 3, 21), ("CCL", 22, "c", date(2025, 4, 17), 0.67)),
        ("MP 75c 2.65 1/16/2026", date(2025, 10, 1), ("MP", 75, "c", date(2026, 1, 16), 2.65)),
        (
            "MRVL 100c 3/20 re entered @ 3.05",
            date(2026, 1, 13),
            ("MRVL", 100, "c", date(2026, 3, 20), 3.05),
        ),
        (
            "SMCI added more to the 35c 3/20 for 2.27",
            date(2026, 1, 6),
            ("SMCI", 35, "c", date(2026, 3, 20), 2.27),
        ),
        (
            "RKT reentered 18c 12/19 @ 0.87",
            date(2025, 10, 31),
            ("RKT", 18, "c", date(2025, 12, 19), 0.87),
        ),
        ("$QBTS 30 C 09/19/2025 0.5", date(2025, 7, 29), ("QBTS", 30, "c", date(2025, 9, 19), 0.5)),
        ("HIMX 12c 4/17 asses @.55", date(2026, 3, 13), ("HIMX", 12, "c", date(2026, 4, 17), 0.55)),
        ("PINS 30c 1/2026 0.97", date(2025, 11, 11), ("PINS", 30, "c", date(2026, 1, 16), 0.97)),
        ("RR 6/18 3c 0.30", date(2026, 5, 11), ("RR", 3, "c", date(2026, 6, 18), 0.30)),
        ("SMR 17.5c 8/15 0.55", date(2025, 7, 17), ("SMR", 17.5, "c", date(2025, 8, 15), 0.55)),
    ],
)
def test_parse_line_formats(line, posted, want):
    s = _one(line, posted)
    assert (s["ticker"], s["strike"], s["cp"], s["expiry"], s["price"]) == want


def test_relative_expiries():
    # Thursday 2025-04-10: next week's Friday is 4/18 = Good Friday -> Thursday 4/17
    s = _one("AMZN 200C nexxt week 0.94", date(2025, 4, 10))
    assert s["expiry"] == date(2025, 4, 17) and s["price"] == 0.94
    assert _one("ARM 185c next week 1.39", date(2025, 1, 30))["expiry"] == date(2025, 2, 7)
    # a Sunday post: 'next week' is the coming week
    assert _one("ARM 185c next week 1.39", date(2025, 2, 2))["expiry"] == date(2025, 2, 7)
    assert _one("BABA 95P 1DTE 0.7", date(2025, 4, 10))["expiry"] == date(2025, 4, 11)
    assert _one("QQQ 500c this week 1.1", date(2025, 6, 2))["expiry"] == date(2025, 6, 6)


def test_month_day_rolls_into_next_year():
    assert _one("MP 60c 1/16 1.80", date(2025, 12, 22))["expiry"] == date(2026, 1, 16)


def test_strangle_gives_two_legs_and_spreads_are_excluded():
    msg = "QQQ 490c 0.52 4/11\nQQQ 410p 0.51 4/11 @Brick Alerts\nQQQ STRANGLE"
    p = B.parse_message(msg, date(2025, 4, 3), CAL)
    legs = [s for specs, _ in p["lines"] for s in specs]
    assert [(s["strike"], s["cp"], s["price"]) for s in legs] == [
        (490, "c", 0.52),
        (410, "p", 0.51),
    ]
    assert (
        B.parse_line("MRK 100/120 long debit spread + a naked 3/20 call", date(2025, 11, 24), CAL)
        == []
    )
    assert B.parse_line("NBIS 160c covered call gonna let this assign", date(2026, 5, 6), CAL) == []


def test_plain_adds():
    assert B.plain_add("MRVL add @ 2.4") == ("MRVL", None, 2.4)
    assert B.plain_add("UBER added 2.25") == ("UBER", None, 2.25)
    assert B.plain_add("AI double down @ 0.6") == ("AI", None, 0.6)
    assert B.plain_add("Avgd up @ 3.00", fallback="WMT") == ("WMT", None, 3.0)
    assert B.plain_add("HIMX 500x added @ 10") is None  # shares
    assert B.plain_add("8x FN shares added @ 496") is None
    assert B.plain_add("UPST 50% first trim") is None


# ---------------------------------------------------------------- openings vs adds


def _msgs(rows):
    out = []
    for i, (ts, text, reply) in enumerate(rows):
        out.append(
            {
                "id": str(1000 + i),
                "ts": pd.Timestamp(ts, tz=TZ),
                "author": "bricktrades",
                "is_bot": False,
                "content": text,
                "reply_to": reply,
                "edited_ts": None,
                "n_attachments": 0,
                "n_embeds": 0,
            }
        )
    return pd.DataFrame(out)


def test_extract_alerts_openings_adds_flow_and_watchlist():
    msgs = _msgs(
        [
            ("2025-06-02 10:00", "OKTA 100c 7/18 2.10 @Brick Alerts", None),
            ("2025-06-03 10:00", "OKTA added @ 1.57 @Brick Alerts", "1000"),
            ("2025-06-04 10:00", "UBER added 2.25\nPOET 20c 7/18 2.00 @Brick Alerts", None),
            ("2025-06-05 10:00", "$TWLO 120 C 07/18/2025\nPrem: $1,119,132", None),
            ("2025-06-05 11:00", "$GAP 28 C 07/18/2025\nPrem: $782,847\nFollowed @ 0.59", None),
            ("2025-06-06 20:00", "**Watchlist tmrw**\nAVGO 300c 7/18 2.5", None),
            ("2025-06-09 10:00", "OKTA 100c 7/18 1.20 again @HIGH RISK PLAY⚠️", None),
            ("2025-06-10 10:00", "OKTA 50% trim @Brick Alerts", "1000"),
        ]
    )
    a = B.extract_alerts(msgs, CAL)
    got = list(zip(a["contract"], a["kind"], a["price"], strict=True))
    assert got == [
        ("OKTA 100c 2025-07-18", "open", 2.10),
        ("OKTA 100c 2025-07-18", "add", 1.57),
        ("POET 20c 2025-07-18", "open", 2.00),  # UBER has no open contract: dropped
        ("GAP 28c 2025-07-18", "open", 0.59),  # followed flow; TWLO flow alone isn't his
        ("OKTA 100c 2025-07-18", "add", 1.20),
    ]
    assert a["high_risk"].tolist() == [False, False, False, False, True]
    cl = B.claims(msgs, a)
    assert cl.to_dict("records") == [
        {
            "contract": "OKTA 100c 2025-07-18",
            "ts": pd.Timestamp("2025-06-10 10:00", tz=TZ),
            "claim": 0.5,
        }
    ]


def test_claims_skip_stop_loss_percentages():
    assert B.CLAIM.findall("-40% SL") == []
    assert B.CLAIM.findall("UPST 105% first trim") == ["105"]
    assert B.CLAIM.findall("MP -80% took loss") == ["-80"]


# ---------------------------------------------------------------- pricing


def test_payoff_and_split_basis():
    assert B.payoff("c", 100, 112.5) == 12.5
    assert B.payoff("c", 100, 90) == 0
    assert B.payoff("p", 100, 90) == 10
    # a 2:1 split before expiry: the close of 60 is 120 in the alert's share basis, and the
    # adjusted contract (200 shares at strike 50) is worth exactly 100 x (120 - 100)
    close_exp, f_exp, f_alert = 60.0, 1.0, 0.5
    assert B.payoff("c", 100, close_exp * f_exp / f_alert) == 20


def test_third_friday_and_friday_of_week():
    assert B.third_friday(2026, 1) == date(2026, 1, 16)
    assert B.third_friday(2025, 8) == date(2025, 8, 15)
    assert B.friday_of_week(date(2025, 1, 30), 1) == date(2025, 2, 7)
    assert B.friday_of_week(date(2025, 2, 1), 0) == date(2025, 2, 7)  # Saturday


def test_betas_use_only_returns_before_the_alert():
    idx = pd.bdate_range("2025-01-01", periods=200)
    rng = np.random.default_rng(0)
    q = 100 * np.cumprod(1 + rng.normal(0, 0.01, 200))
    rq = np.r_[0, q[1:] / q[:-1] - 1]
    s = 50 * np.cumprod(1 + 2 * rq)
    adj = pd.DataFrame({"QQQ": q, "S": s}, index=idx)
    b = B.betas(adj, pd.Series([150]), pd.Series(["S"]))
    assert b[0] == pytest.approx(2.0, rel=1e-6)
    # changing the future doesn't change the beta at row 150
    adj2 = adj.copy()
    adj2.iloc[150:, 1] *= 3
    assert B.betas(adj2, pd.Series([150]), pd.Series(["S"]))[0] == pytest.approx(b[0])
    # too little history: beta 1
    assert B.betas(adj, pd.Series([30]), pd.Series(["S"]))[0] == 1.0


def test_own_alert_next_to_a_flow_repost_and_ticker_fallback():
    msgs = _msgs(
        [
            (
                "2025-02-04 14:57",
                "SOUN 20c 2/21 0.50\nhugging 50day MA\nSOUN 18 C 03/21/2025\nPrem: $258,808",
                None,
            ),
            ("2025-01-24 13:24", "TSLA -60% sold this single con\nRolled to 300p 3/21 3.35", None),
        ]
    )
    a = B.extract_alerts(msgs, CAL)
    assert list(a["contract"]) == ["SOUN 20c 2025-02-21", "TSLA 300p 2025-03-21"]
    assert list(a["price"]) == [0.50, 3.35]
