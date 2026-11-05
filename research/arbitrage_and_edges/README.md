# Arbitrage, parity and where returns actually come from

Written 2026-09-29, a summary of a Q&A session. No backtests here: this note explains why most
"free money" isn't, what quant funds run instead, and what this repo can copy at $5k. The
implementation plan is in [quant_reading_list.md](../quant_reading_list/README.md); the results are in
[multifactor.md](../multifactor/README.md).

## Prediction-market arbitrage (Polymarket vs Kalshi)

**Mechanics:** YES + NO on the same event pays exactly $1. If YES on one venue plus NO on the
other costs less than $1 after fees, you've locked in the difference.

**Worked example:** Polymarket YES at 55¢, Kalshi NO at 42¢, total 97¢, so a 3¢ gap.
- Kalshi's taker fee is about 0.07 × price × (1 − price) per contract, rounded up per order:
  ~1.7¢ at 42¢. Polymarket charges nothing on most markets but has been adding taker fees to
  some, so check.
- That leaves ~1.3¢ on 98.7¢. If the event resolves in 4 months, that's ~4% a year, about
  the T-bill rate, with risks T-bills don't have.

**Why gaps persist:**
1. **Resolution mismatch, the big one.** Markets that look identical can differ in deadline
   (ET vs UTC, "by" vs "on"), source, or what counts ("announced" vs "signed"). Kalshi
   settles by its CFTC contract rules; Polymarket by UMA token-holder vote, which has produced
   disputed outcomes (the March 2025 Ukraine minerals-deal market). If the two resolve
   differently you lose both legs, not just the gap. Many visible gaps are the market pricing
   this risk.
2. **Leg risk:** one side fills, the other moves.
3. **Thin books:** the top-of-book price may cover $50.
4. **Capital lock-up** until resolution. Kalshi pays interest on balances; Polymarket's USDC
   earns nothing (except some long-dated markets), and getting money in and out through
   crypto costs extra.
5. **Access:** both venues restrict countries and the list changes. Check both for the
   owner's country first.

**Who wins:** [Saguillo et al. 2025](https://arxiv.org/abs/2508.03474) estimate ~$40M of
arbitrage taken on Polymarket from April 2024 to April 2025, much of it inside multi-outcome
markets whose YES prices summed to less than $1, and most of it by a few automated accounts.
The easy gaps close within seconds.

## Crypto arbitrage

| Type | How | Realistic at $5k? |
|---|---|---|
| Cross-exchange | buy on A, sell on B | Rarely: gaps between major exchanges are a few basis points, below ~0.1% taker fees; needs coins pre-positioned on both exchanges. Regional premiums (Korea's "kimchi premium") persist because capital controls block the arbitrage. |
| Triangular | BTC→ETH→USDT→BTC on one venue | No: co-located bots |
| DEX↔CEX / MEV | on-chain vs exchange price gaps | No: specialised bots pay nearly all the profit away to get their transactions in first |
| **Cash-and-carry / funding** | own spot, short the perpetual, collect funding | **Yes, but it's carry, not arbitrage:** exchange failure (FTX), negative funding, liquidation of the short leg. Paid 20-40%/yr in 2021, often single digits now, sometimes below T-bills. |

## Options: put-call parity

**C + PV(K) = S + P** (European, no dividends). Conversions (long stock + long put + short
call), reversals (the opposite) and box spreads (bull call spread + bear put spread) all turn
this into a synthetic bond.

**Why it doesn't pay at the prices you can trade:** stock $100, 6-month 100-strike, rates 4%,
so PV(K) = $98.02.
- At the mid: 100.00 + 3.15 − 5.15 = 98.00, which looks like 2¢ free.
- At executable prices: 100.01 + 3.20 − 5.10 = 98.11, a 9¢ loss before ~$2 of commissions per
  100-share conversion.

Market makers price off parity, so it holds to pennies at the bid and ask. Apparent violations
are:
- **Hard-to-borrow stocks:** the gap is the borrow fee.
- **Dividends:** plus early exercise of the short call just before the ex-date.
- **American exercise:** US stock and ETF options, including SPY, can be assigned early. The
  2019 WallStreetBets SPY box spread blew up this way.
- **Stale or wide quotes.**
- **Pin risk** at expiry.

**What it's good for:**
- Reading implied borrow cost, dividends and interest rates from option prices.
- **SPX box spreads** (European, cash-settled) to lend or borrow near the T-bill rate. At $5k
  the borrowing saving is ~$50/yr. The lending side may matter more if IBKR pays nothing on
  the first $10k of cash (verify), but plain T-bills do the same job.

## Is market making the only way to beat the market?

No. Returns above the index come from five places:

| Source | Paid for | Examples |
|---|---|---|
| Risk premia | holding risks others avoid | equity, value, carry, selling volatility |
| Behavioural mispricing | others' predictable mistakes | momentum, post-earnings drift, reversals |
| Liquidity and insurance | taking the other side of forced trades | market making, merger arbitrage, index flows |
| Information | knowing or processing better | alternative data, text, fundamental research |
| Structure | rules that stop others acting | benchmark-hugging, leverage limits, short limits |

Market makers live in the third row. Mid- to long-horizon quants live mostly in the first two.

### What mid- to long-horizon quants run
1. **Multi-factor equity long/short** (AQR, Two Sigma, D.E. Shaw's and Millennium's systematic
   arms, Renaissance's institutional funds):
   - hundreds of weak signals: value, momentum, quality, low beta, revisions, short interest,
     accruals, seasonality
   - a risk model keeps the book near market-neutral, at 4-8x gross
   - each signal's Sharpe is ~0.2-0.5; combined, 1-2
2. **Managed futures / trend:** time-series momentum on 50-100+ futures
   ([Moskowitz, Ooi & Pedersen 2012](https://papers.ssrn.com/abstract=2089463)). Sharpe
   ~0.5-0.8, pays in crises.
3. **Multi-asset style premia:** value, momentum, carry and defensive in every asset class
   ([Value and Momentum Everywhere](https://pages.stern.nyu.edu/~lpederse/papers/ValMomEverywhere.pdf);
   [Carry, NBER w19325](https://www.nber.org/papers/w19325);
   [Betting Against Beta](https://www.johnhcochrane.com/s/BettingAgainstBeta.pdf)).
4. **Risk parity:** weight by risk, then lever
   ([Leverage Aversion and Risk Parity](https://www.aqr.com/Insights/Research/Journal-Article/Leverage-Aversion-and-Risk-Parity)).
5. **Systematic events:** earnings drift, index changes, merger arbitrage, text/NLP.

Their signals are mostly published. The edge is breadth (IR ≈ IC × √breadth), near-zero costs,
cheap shorting and leverage, and the discipline to sit through drawdowns (value lost most of
2018-2020). Published anomalies lose about half their return after publication
([McLean & Pontiff 2016](https://onlinelibrary.wiley.com/doi/10.1111/jofi.12365)); a new
factor needs t > 3 ([Harvey, Liu & Zhu 2016](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2249314)).
This repo saw the same decay in ORB and noise-area momentum.

### Where horizon-trader already stands
- `position_momentum`, `position_trend` and `position_volmanaged` are the retail-sized versions
  of cross-asset momentum, CTA trend and volatility management.
- The combined book (Sharpe 0.83 vs SPY 0.64, max drawdown -12% vs -52%, CAGR 6.5% vs 11.3%)
  is the typical quant profile: better risk-adjusted, lower raw return. Funds beat the index
  on raw return only by adding leverage.
- At $5k the constraint is breadth and per-order minimums, which is why single large-cap alphas
  never reached t > 2 here.
- **What a small account can do that funds can't:** no benchmark, no redemptions, patience,
  and it can use capacity too small to interest a fund.

## "Why not let a model learn the weights?"

It can, and big funds do: [Gu, Kelly & Xiu 2020](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3159577)
trained neural nets on ~900 signals over 60 years. The problem is the ratio of signal to noise
to data:
- A good monthly stock signal has IC ≈ 0.03: 97% of the variation in next month's returns is
  noise.
- With 5 signals, 200 stocks and ~36 months of training, a fitted model mostly learns that
  noise and gives weights that swing from year to year. Estimated weights usually lose to
  plain equal weights out of sample, the same lesson as DeMiguel et al.'s "1/N".
- Gu-Kelly-Xiu's gains came from huge data (30,000 stocks × 720 months), not the model alone.

So `backtest/multifactor.py` fixes equal weights in advance and runs a walk-forward ridge
regression next to them as a pre-registered comparison. See
[multifactor.md](../multifactor/README.md) for how it did.

## Suggested next steps (from the session)
- A Kalshi/Polymarket gap logger (free APIs, records executable after-fee gaps and resolution
  wording) and a historical funding-rate check for cash-and-carry. Both measure before trading.
  Not started.
- SEC fundamentals loader, multi-factor composite, Lazy Prices, risk-parity sleeve: built
  2026-09-29. Results in [multifactor.md](../multifactor/README.md) and below.
