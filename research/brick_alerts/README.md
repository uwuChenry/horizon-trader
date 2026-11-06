# Following bricktrades' Discord option alerts

**Verdict: no evidence of skill, and both pre-registered tests fail.** I parsed 1,154
expired opening alerts (Dec 2024 to Oct 2026), single-stock calls held for weeks.
Held to expiry they return **+9% on average (t = 0.43)**. With one contract per alert
the total is **-3.3%**. 78% expire worthless, and the best 5% of alerts carry 664% of
the total gain. The stocks he picks do no better than QQQ once you adjust for their beta
of 1.4: **-0.1% over 20 days (t = 0.15)**. All the good results come from one stretch:
Q2-Q3 2025, the rebound after the April tariff crash, when high-beta calls doubled. The
second half (Dec 2025 onward) is **significantly negative**: option return -24% (t = -2.0),
and the stock lags beta-adjusted QQQ by 4.5% to expiry (t = -3.8). His follow-ups
favour the winners. The 401 openings he never posted a % on average -65%, and 90% of
them expire worthless.

Rules: [protocol.md](protocol.md), written before any return was computed. Code:
`src/horizon_trader/social/brick.py` (parser + study) and `social/discord.py` (export
loader). Run output: [output.txt](output.txt).

```bash
uv run python -m horizon_trader.social.brick [--export <file>] [--show-unparsed N]
```

## Data

- `brick-alerts` channel (Low Key Stonks Discord), exported 2026-11-05 with
  DiscordChatExporter 2.48 using a user token (against Discord's terms; read-only, one
  export). 8,083 messages, 7,840 by `bricktrades`. Stored in `data/discord/raw/`
  (git-ignored).
- The parser found **1,759 alerted purchases: 1,219 openings + 540 adds**. 1,739 are
  testable, meaning the stock has US bars and the price and strike are sane. 1,658 had
  expired by 2026-11-04. 143 of his messages mention a strike but gave no alert: spreads,
  cash-secured puts, flow reposts, "PATH 11/21 calls" with no strike or price, and
  watchlists.
- What he trades: 95% calls, median 37 days to expiry, median 13% out of the money.
  Mostly AI, momentum and small-cap growth names (HOOD, SMCI, SOFI, NBIS, ORCL, MRVL,
  RKLB, CRWV...). QQQ is 1% of alerts.

## Test 1: each opening held to expiry (exact, no option data)

Value at expiry = intrinsic value at the official close, split-adjusted. R = value / his
price - 1. The option's market price is the control: a buyer with no skill should expect
R < 0.

| group | n | mean R | median R | % worthless | % profit | t (weekly) | +5% fill |
|---|---|---|---|---|---|---|---|
| all openings | 1,154 | +9.1% | -100% | 78% | 18% | 0.43 | +3.9% |
| calls | 1,105 | +8.0% | -100% | 77% | 19% | 0.51 | +2.8% |
| puts | 49 | +35.5% | -100% | 86% | 12% | 0.37 | +29.0% |
| <= 7 days | 73 | +7.5% | -100% | 85% | 14% | 0.31 | +2.4% |
| 8-30 days | 389 | +0.2% | -100% | 79% | 19% | -1.14 | -4.6% |
| 31-90 days | 650 | +17.0% | -100% | 76% | 19% | 1.52 | +11.4% |
| > 90 days | 42 | -26.9% | -100% | 88% | 12% | -1.29 | -30.4% |
| `HIGH RISK PLAY` tag | 102 | -8.6% | -100% | 84% | 15% | -0.59 | -12.9% |
| edited alert | 144 | -3.7% | -100% | 79% | 15% | -0.62 | -8.3% |
| first half (to Nov 2025) | 613 | +38.6% | -100% | 74% | 22% | 1.73 | +32.0% |
| **second half (Dec 2025-)** | 541 | **-24.3%** | -100% | 82% | 14% | **-1.99** | -27.9% |

**By quarter**, with $ R = total value / total premium - 1 at one contract each:

| quarter | n | mean R | $ R | % worthless |
|---|---|---|---|---|
| 2024 Q4 | 28 | -77% | -53% | 89% |
| 2025 Q1 | 158 | -23% | -0% | 85% |
| 2025 Q2 | 171 | **+105%** | **+94%** | 64% |
| 2025 Q3 | 162 | **+94%** | **+98%** | 65% |
| 2025 Q4 | 132 | -5% | -6% | 79% |
| 2026 Q1 | 137 | -21% | -14% | 83% |
| 2026 Q2 | 237 | -20% | -15% | 81% |
| 2026 Q3 | 128 | -66% | -63% | 86% |

- **It's a lottery.** Without the 10 best alerts (out of 1,154), the mean is -11%. The
  best was a QQQ 440p bought 2025-04-01 at $0.56, three days before the tariff crash
  (30x). Then AMD 180c (28x, the OpenAI deal), NVTS, OKLO and RBLX.
- **The two good quarters** were the market's V-shaped rebound after April 2025.
  Out-of-the-money calls on 1.4-beta stocks are leveraged beta, and that is the best
  setting there is for them. Every other quarter loses.
- **Pricier contracts later.** The premium per alert in Q2 2026 was 2.6x Q2 2025's. All
  the 2026 quarters lose, so one contract per alert loses 3.3% overall even though the
  equal-weight mean is +9%.
- **Adds** (averaging down or up) held to expiry: +16.9% (n = 503). They are also
  concentrated in 2025.
- Edited alerts and the `HIGH RISK` tag are both worse than the rest. The export only
  shows the final text, so we can't tell what changed in the 144 edited alerts.

**PASS needed:** mean > 0, t > 2, and positive in both halves. **FAIL** (t = 0.43; the
second half is -24%).

## Test 2: does he pick the stock's direction?

The stock is bought 1 minute after the alert, or at the next open; puts count as shorts.
Returns are compared with QQQ bought at the same moment, and with beta x QQQ (120-day
beta before the alert, median 1.40).

| horizon | group | n | stock (signed) | vs QQQ | beta-adj vs QQQ | % beat | t (weekly) |
|---|---|---|---|---|---|---|---|
| 5 days | all | 1,205 | +0.5% | +0.3% | +0.2% | 47% | 0.23 |
| 20 days | all | 1,188 | +0.7% | -0.0% | **-0.1%** | 45% | **0.15** |
| 20 days | first half | 614 | +2.4% | +1.4% | +1.1% | 46% | 1.07 |
| 20 days | second half | 574 | -1.1% | -1.6% | -1.4% | 43% | -1.11 |
| to expiry | all | 1,155 | -0.0% | -1.4% | -1.6% | 40% | -1.75 |
| to expiry | second half | 541 | -2.7% | -4.3% | **-4.5%** | 36% | **-3.84** |

- After adjusting for beta, the stocks he alerts do what QQQ does, or worse. Only 40-47%
  beat their beta-adjusted benchmark.
- **Timing is negative:** the 20-day return after an alert is 2.7% below the same
  stock's average 20-day return over the sample (t = -1.77). He tends to buy names after
  they've run.
- **PASS needed:** 20-day beta-adjusted > 0, t > 2, positive in both halves. **FAIL**.

## His own follow-ups (self-reported)

He replies to alerts with figures like "UPST 105% first trim" or "MP -80% took loss".

- 754 of the 1,155 expired openings got a % follow-up. 611 of those claim a gain, with
  a median best claim of **+80%**.
- 406 of the 610 alerts that claimed a gain **expired worthless**. That isn't a
  contradiction, since an option can be up 80% in mid-life and still die, but it means
  the follower has to sell when he posts.
- **The 401 openings with no % follow-up average -65% held to expiry, and 90% expire
  worthless.** The silence is where the losers are. A channel read for its wins shows
  mostly winners.

Whether selling at his trim messages makes money is the one question left open. It
needs the option's price at each follow-up, and we have no option history. Two ways to
answer it:

- Approximate it: back out the implied vol from his entry price, then reprice at the
  follow-up time using the stock's minute bar. That's rough, because it misses IV crush
  around earnings.
- Measure it forward: an IBKR job that snapshots the bid/ask of every open alert's
  contract each day, plus the price at each follow-up.

## Caveats

- **Deleted alerts are missing**, which flatters him. The size of this bias is unknown.
  From now on, re-exporting with `--after` and comparing against the previous export
  will show deletions.
- The parser is rule-based and tested on every format seen (`tests/test_brick.py`). A few
  percent of alerts are lost (see the 143 unparsed), and an occasional mis-parse is
  possible. The biggest winners in `output.txt` were checked against the known moves
  behind them (QQQ in the April 2025 crash, AMD after the OpenAI deal).
- His price is taken as given. A follower filling 5% worse loses another ~5 points of R
  (column "+5% fill"). Commissions are ignored.
- 23 months covering one tariff crash and one AI rally, so a small sample of market
  regimes.
