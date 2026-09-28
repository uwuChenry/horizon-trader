# Copy-trading Congress: does buying what members disclose beat SPY?

Run 2026-09-28 with `uv run python -m horizon_trader.congress.event_study`. Code:
`src/horizon_trader/congress/` (archive.py downloads, event_study.py tests). Data:
[kadoa-org/congress-trading-monitor](https://github.com/kadoa-org/congress-trading-monitor)
(MIT, pinned commit `ef9e1cf`), which parses the House Clerk's periodic transaction reports,
the Senate eFD system and OGE filings. That's 69,403 trades by 447 filers, 2014–2026; the
test uses the 10,115 stock/ETF purchases filed Oct 2021 – Sep 2026, when our Massive prices
are point-in-time.

## Answer first

- **The filing lag is real.** Members may disclose up to **45 days** after trading (STOCK
  Act), and a third file late. Median trade-to-disclosure: **32 days**; 10% took more than
  **156 days**.
- **Copying all of Congress lost to SPY.** Buying every disclosed purchase the day after it
  became public and holding 60 days made **6.5% a year** ($100k, after IBKR costs). SPY made
  12.4%. Sharpe 0.39 vs 0.77, alpha **−6.7%/yr**.
- **The typical disclosed purchase goes nowhere special.** Over 60 days it averaged **−0.4% vs
  SPY** (median −1.8%, 45% beat SPY, t = −0.25). That holds for the House, Democrats,
  Republicans and small trades alike.
- **Pelosi, copied as stock, is a leveraged tech bet, not an edge.** Holding her disclosed buys
  until she discloses a sale: **14.1% a year**, Sharpe 0.60, a **−49% drawdown**, beta 1.42.
  QQQ over the same days made 16.1% with Sharpe 0.77 and a −36% drawdown. Her alpha after
  adjusting for beta is +1.2%/yr, which is noise over 43 purchases.
- **The trade-date "lookahead" isn't what makes trackers look good here.** Buying on the trade
  date (which a copier can't do) was *not* better: all of Congress 7.6% vs 6.5%, Pelosi 13.2%
  vs 14.1%. The "200%" results more likely come from copying her **call options** (leverage in
  a tech bull market), cherry-picked start dates (2023 NVDA), or ranking members by past
  returns.
- **The live product agrees.** NANC, the ETF that buys Democrats' disclosed trades, made
  **22.6% a year vs SPY 20.2%** since Feb 2023 (Sharpe 1.31 vs 1.31, beta 1.07, alpha
  +0.9%/yr). QQQ made 28.1%. That's a tech-tilted index fund, not an insider edge.
- **Two things worth a closer look (not significant after this many groups):** Senate purchases
  (+1.2% vs SPY at 60 days, t = 2.07; +0.7% at 20 days, t = 3.12, n ≈ 1,000), and the largest
  purchases (≥ $250k: +6.6% at 120 days, t = 1.89, only 80 events). Both fit the academic
  finding that leaders and big trades keep some edge, and both need out-of-sample confirmation.

## Rules (pre-registered in the module docstring)

- **Events:** each disclosed purchase of a US-listed stock or ETF, one per (member, ticker,
  filing date). Option purchases are copied as stock in the underlying.
- **Honest timing:** the filing is public by the end of its date, so the copy buys at the next
  open.
- **Lookahead timing, for contrast:** buy at the next open after the *trade* date.
- **Returns:** open to close, split-adjusted, price only, minus SPY over the same days.
  t-stats cluster by entry week.
- **Portfolios:** equal weight across the names held, run through the daily book's simulator
  with IBKR Pro Tiered costs and 5 bps slippage.
  - A. all of Congress, each buy held 60 days ($100k).
  - B. buys of $250k or more, held 60 days ($100k).
  - C. Pelosi, held until her next disclosed sale of the name or 1 year, at most 20% per
    name ($5k).
- **Scope:** the dataset also covers executive-branch officials (cabinet, OGE forms). They
  were accidentally included in the first run. They're now reported as their own group and
  excluded from A and B.

## Results

### Returns vs SPY after a disclosed purchase (filing-date entry)

| group | events (60d) | 20d mean | 60d mean | 60d median | 60d % beat SPY | 60d t | 120d mean |
|---|---|---|---|---|---|---|---|
| all Congress | 7,728 | +0.1% | −0.4% | −1.8% | 45% | −0.25 | −1.2% |
| purchases $250k+ | 84 | +1.3% | +0.9% | −0.6% | 46% | 0.82 | +6.6% (t 1.89) |
| purchases $1k–15k | 6,248 | +0.0% | −0.5% | −1.9% | 44% | −0.18 | −1.1% |
| House | 6,736 | −0.1% | −0.6% | −1.9% | 45% | −0.29 | −1.6% |
| Senate | 992 | +0.7% (t 3.12) | +1.2% | −0.7% | 47% | 2.07 | +1.4% |
| Democrats | 3,448 | −0.0% | −0.5% | −1.9% | 45% | −0.71 | −1.7% |
| Republicans | 4,253 | +0.1% | −0.3% | −1.6% | 45% | −0.97 | −0.8% |
| Pelosi | 43 | +2.5% | −3.5% | −4.6% | 37% | 0.32 | +2.6% |

The medians are below zero for almost every group: most copied buys trail SPY, and a few big
winners pull the means up.

### Portfolios (Oct 2021 – Sep 2026)

| portfolio | CAGR, net | Sharpe | max DD | beta | alpha/yr |
|---|---|---|---|---|---|
| A. all of Congress, 60 days ($100k) | 6.5% | 0.39 | −36% | 1.20 | −6.7% |
| A*. same, LOOKAHEAD | 7.6% | 0.44 | −33% | 1.18 | −5.9% |
| B. $250k+ purchases ($100k; ~3.5 names held) | 11.2% | 0.51 | −38% | 1.25 | −0.2% |
| C. Pelosi until her sale ($5k) | 14.1% | 0.60 | −49% | 1.42 | +1.2% |
| C*. Pelosi, LOOKAHEAD | 13.2% | 0.57 | −53% | 1.42 | −0.6% |
| SPY | 12.4% | 0.77 | −25% | 1.00 | 0 |
| QQQ | 16.1% | 0.77 | −36% | 1.27 | +0.9% |

Live, since Feb 2023: NANC 22.6%/yr (Sharpe 1.31, −21%), SPY 20.2% (1.31, −19%), QQQ 28.1%
(1.34, −23%). KRUZ, the Republican version, returned no data from yfinance (apparently
delisted).

## Caveats

- Amounts are ranges, so trades are equal-weighted rather than sized.
- Pelosi's filings are mostly her husband's trades and largely **call options**. A stock copy
  understates both the gains and the risk. Copying the options at her strikes and expiries
  isn't possible from the filings: the details are often incomplete, and they're weeks old by
  disclosure.
- About 20% of all rows have no ticker, and the dataset parses free-text PDFs. Parsing errors
  are possible.
- Five years of mostly bull market. The 2022 bear market is in the sample.

## Literature

- Belmont, Sacerdote, Sehgal & Van Hoek (2022), [Do senators and house members beat the stock
  market? Evidence from the STOCK
  Act](https://www.sciencedirect.com/science/article/abs/pii/S0047272722000044), *Journal of
  Public Economics*: members' trades don't beat the market on average after the STOCK Act.
- Shang-Jin Wei et al. (NBER w34524), ["Captain Gains" on Capitol
  Hill](https://www.nber.org/system/files/working_papers/w34524/w34524.pdf): congressional
  *leaders* keep positive risk-adjusted returns even when portfolios use public disclosure
  dates. That fits the Senate and $250k+ hints above.
- [U.S. Congress members' trading activities: a case of NANC and
  KRUZ](https://www.sciencedirect.com/science/article/abs/pii/S0165176525001004), *Economics
  Letters* (2025).

## Next

- Test "leaders only" (party leaders and committee chairs) as the NBER "Captain Gains" paper suggests.
  It needs a list of who held those roles when, and it must be pre-registered first, because
  picking members after seeing returns is exactly the selection bias that inflates tracker
  results.
- Add new filings to the feeds project, so any rule gets a forward test from today.
