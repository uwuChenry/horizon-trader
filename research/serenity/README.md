# Following Serenity (@aleabitoreddit): does it pay?

Run 2026-09-27 with `uv run python -m horizon_trader.social.event_study`. Code:
`src/horizon_trader/social/archive.py` (posts and cashtags) and
`src/horizon_trader/social/event_study.py` (prices, returns, portfolios). Related:
[Catching the next Nvidia](../winners_momentum/README.md).

## Answer first

- **Following his posts made money, but less than simply owning the semiconductor ETF.** From
  July 2025 to September 2026, a $5k account that bought every newly mentioned ticker and held
  it for 60 trading days made **+34% a year after costs (Sharpe 0.94, −38% max drawdown)**. SMH,
  the semiconductor ETF, made **+88% a year (Sharpe 1.90, −25%)** over the same days. SPY made
  +19% and QQQ +28%.
- **His most-talked-about names did best, but still trailed SMH:** the 10 tickers he mentioned on
  the most days in the last 20 made **+68% a year net (Sharpe 1.22)**. This rule was added
  *after* seeing the other three results, so treat it as optimistic.
- **The average pick lagged SMH.** 60 trading days after a post, the mean stock was up 15%, but
  SMH bought at the same minute was up more: **−8.2% vs SMH on average, median −17%, and only
  29% of calls beat SMH**. The mean is carried by a few huge winners (MXL +364%, AXTI +255%, AAOI
  +200%, SNDK +180% in 60 days). Losers were just as big (BIRD −83%, NAKA −72%, NKLR −69%).
- **His posts don't move prices, so front-running isn't the problem.** One minute after an
  in-session post the price was, on the median, exactly where it was when he posted; the p90 move
  was +0.2%. Overnight posts gapped +0.3% (median) by the next open. From his price, the
  average 20-day return was 6.6%; from the follower's, 5.9%.
- **The 4,500% can't be checked.** It's his own, unaudited, leveraged number. The four rules tested
  here made 44–90% in total over the 14 months. The rest would have to come
  from options, leverage, concentration and timing that the posts don't reveal.

## Update: with bullish / bearish / neutral labels (2026-09-27)

Run with `uv run python -m horizon_trader.social.event_study --stance`. Claude (Sonnet) labelled
all 13,010 (post, ticker) mentions from the text alone: 6,736 bullish, 5,280 neutral, 994
bearish (`social/stance.py`, labels in `data/social/serenity/stance/labels/`). The trading rule is
the owner's: **bullish = buy, bearish = sell if held, neutral = nothing; long only.**

- **The labels carry real information, mostly in his bearish calls.** Sixty days after a
  bearish call the stock trailed SMH by 23.5% on average (median −30%, only 18% beat SMH,
  weekly-clustered t = −7.5). Bullish calls trailed SMH by 2.4% (median −14%). Neutral mentions
  trailed by 8.5%. So the bullish calls beat his neutral mentions, and the sells help most.
- **Stance-aware rules beat the stance-blind ones and beat random labels, but still trail SMH.**

| rule ($5k net, Jul 2025 – Sep 2026) | CAGR | Sharpe | max DD | beta to SMH | shuffles as good (Sharpe) |
|---|---|---|---|---|---|
| bA. first bullish call, 60 days, sold on bearish | 32.4% | 0.90 | −30% | 0.75 | 42% (fails) |
| bB. bullish in last 20 days, no bearish since | 55.4% | 1.18 | −32% | 0.99 | 0% (passes) |
| bC. bullish until bearish (the owner's rule) | 48.0% | 1.01 | −33% | 1.14 | 0% (passes) |
| bD. top 10 by bullish days in last 20 | 79.0% | 1.24 | −40% | 1.32 | 6% (just fails) |
| (stance-blind B / C / D) | 41.1% / 36.7% / 68.2% | 0.96 / 0.82 / 1.22 | | | |
| SMH buy and hold | 88.0% | 1.90 | −25% | 1.00 | |

  "Shuffles as good" is the share of 50 random reshufflings of the same labels (across
  mentions) that did at least as well. The pre-registered bar is under 5%. Shuffles cut the
  stance-blind rules' returns too, so the right comparison is real vs shuffled, not bB vs B.
- **Selling on a bearish call is the part that works.** bC holds everything he's bullish on
  until he turns bearish. It made 48% against 37% for holding everything he mentions, and 16%
  for the median shuffle.
- **Still not better than the ETF.** Even the best rule (bD, 79% a year) ran at 1.3x SMH's
  beta with a −40% drawdown and a Sharpe of 1.24 against SMH's 1.90.

**Hindsight check.** The labelling model may know how 2025–26 turned out. Posts from June to
September 2026 are probably beyond its training data. There, bearish calls still trailed SMH
by 5.1% over 20 days, but that's only 32 calls. Bullish calls did no better than neutral
mentions (−1.7% vs −1.6%). So the bearish signal looks real but thin, and the bullish edge is
unproven out of sample.

**Label quality.** A hand check of 20 random labels found about 18 clearly right and the rest
defensible. Known questionable calls:
- A hypothetical "Serenity Doomsday ETF" hedge basket was labelled bullish on SQQQ, UVIX, FAZ
  and GUSH, and bearish on NVDA and SPY.
- Relative put-downs ("not sure how $POET is worth $2.6B") count as bearish.
- One labeller hit the output-token limit, and the check caught another reading only part of
  two posts. Every batch passed the completeness check before this run.

## What was tested (pre-registered in the module docstring)

- **Posts:** 6,592 posts, 2025-07-02 to 2026-09-17, from the fan-maintained archive
  [yan-labs/serenity-aleabitoreddit](https://github.com/yan-labs/serenity-aleabitoreddit) (pinned
  commit `20e9e90`). The account was created on 2025-07-02 (decoded from its user id), so the
  archive covers his whole history, and a "first mention" is really his first.
- **Timestamps:** decoded from each post's id (X sets it when the post is created; it can't be
  backdated), not the scraped date. The scraped dates were off by up to 10 minutes.
- **Events:** every `$TICKER` in his own text (not in retweets or quoted posts), one per ticker
  per entry day. Every cashtag counts as a buy: stance isn't extracted yet. That gives 5,692
  events on US-listed names.
- **Prices:** his price is the last completed minute bar before the post, or the last close
  when he posts outside market hours. A follower buys the open of the minute bar 1 minute after
  the post, or the next regular open. Returns are split-adjusted and price-only.
- **Portfolios:** $5k, IBKR Pro Tiered, 5 bps slippage, run through the daily book's
  simulator. Each name gets 1/max(N, 10) of equity. A, B and C were pre-registered; D wasn't.

## Results

### Chasing: how far the price moved from his price before a follower could buy

| posted | follower buys | events | mean | median | p90 |
|---|---|---|---|---|---|
| in session | +1 min | 1,158 | +0.1% | 0.0% | +0.2% |
| in session | +15 min | 1,127 | +0.1% | 0.0% | +1.0% |
| in session | +60 min | 972 | +0.1% | 0.0% | +1.7% |
| outside hours | next open vs last close | 4,530 | +0.8% | +0.3% | +4.5% |

80% of his ticker mentions are posted outside US market hours, so most followers buy at the next open.

### Forward returns from the follower's price

| group | horizon | events | mean | median | % up | mean vs SMH | median vs SMH | % beat SMH |
|---|---|---|---|---|---|---|---|---|
| all events | 5d | 5,671 | +1.7% | +0.6% | 53% | −0.1% | −1.1% | 44% |
| all events | 20d | 5,494 | +5.9% | +1.9% | 54% | −1.5% | −4.4% | 39% |
| all events | 60d | 5,008 | +15.4% | +2.0% | 53% | −8.2% | −17.1% | 29% |
| first mentions | 20d | 527 | +3.7% | +1.6% | 55% | −2.3% | −2.6% | 43% |
| first mentions | 60d | 518 | +10.7% | +4.0% | 55% | −9.7% | −15.2% | 34% |
| ≥ $1B/day traded | 60d | 2,741 | +12.5% | +1.5% | 53% | −10.8% | −17.4% | 26% |
| $100M–$1B/day | 60d | 1,440 | +18.0% | +3.9% | 54% | −5.3% | −16.5% | 33% |
| < $100M/day ("hidden names") | 60d | 808 | +20.6% | +3.4% | 54% | −4.1% | −16.7% | 35% |

The weekly-clustered t-stats against SMH are negative at every horizon (−4.8 for all events at
60 days). Windows of 60 days overlap across weeks, so those t-stats overstate precision. Read
them as "no evidence of beating SMH", not "reliably worse".

The small, illiquid names he's known for surfacing had the highest averages (+21% in 60 days),
but the median was +3.4%, and they still trailed SMH.

### Follower portfolios ($5k, Jul 2025 – Sep 2026)

| portfolio | CAGR net | Sharpe net | max DD | beta to SMH | alpha/yr vs SMH | costs | CAGR gross |
|---|---|---|---|---|---|---|---|
| A. first mention, held 60 days | 34.1% | 0.94 | −38% | 0.71 | −12% | $406 | 41.3% |
| B. mentioned in the last 20 days | 41.1% | 0.96 | −33% | 1.01 | −25% | $640 | 49.8% |
| C. everything mentioned so far | 36.7% | 0.82 | −46% | 1.15 | −32% | $124 | 39.2% |
| D. top 10 by days mentioned, last 20 (post hoc) | 68.2% | 1.22 | −35% | 1.14 | −13% | $526 | 75.9% |
| SMH buy and hold | 88.0% | 1.90 | −25% | 1.00 | 0 | – | – |
| QQQ buy and hold | 28.0% | 1.42 | −12% | 0.45 | – | – | – |
| SPY buy and hold | 19.2% | 1.49 | −9% | 0.25 | – | – | – |

Costs took 3–10 points a year at $5k: B traded 1,812 times in 14 months.

## Why this is if anything too kind to him

- **Deleted posts are missing.** Deleted calls are more likely to be bad ones.
- **14 months, one regime.** SMH more than doubled. Everything in AI hardware went up, so
  "beats SPY" is the wrong bar. The alternative with the same sector bet and no research is SMH.
- **Untestable names:** the most-mentioned foreign listings have no US bars: $SIVE Sivers (691
  mentions), $SOI Soitec (171), $IQE (169), $RPI Raspberry Pi (83), $LPK LPKF (52). Some of his
  best-known calls are in there, and they could cut either way.
- **The only choice made after seeing results, D, is the best row.**

Why it could be too harsh: every cashtag counts as a buy, including names he mentions only for
context or dislikes ($UVIX, a leveraged volatility ETF, is unlikely to be a buy call). Extracting stance would fix that.

## Next steps

1. ~~Stance extraction~~: done (above). Worth doing next: label new posts as they arrive, so
   every label is written before the outcome exists.
2. **Forward test** of bB / bC (the rules that passed the shuffle test): re-pull the archive (`python -m horizon_trader.social.archive --ref HEAD`)
   every week. Posts after today are untouched data for rule D and anything else. Log every
   pull with its time.
3. If anything is adopted, it's a small satellite, not the core: the sector bet is already in
   the owner's ~$100k AI-hardware account.
