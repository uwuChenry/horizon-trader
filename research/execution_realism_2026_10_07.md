# Alpaca paper versus IBKR Pro live execution

Reviewed 2026-10-07. Documentation review and inspection of existing research only;
no broker latency benchmark, new strategy backtest, or orders were run.

## Assessment

Alpaca paper is useful for testing order handling and a simulated competition. Its
P&L does not establish that an intraday strategy will retain its edge at IBKR Pro.
For our five-minute opening-range strategy, execution sensitivity is already
visible in the historical research. Subsecond scalping would require much more
credible execution evidence. Slower intraday and swing signals remain candidates,
subject to costs, data consistency, and actual order behavior.

## Documented differences

- Alpaca paper matches against current national best bid/offer (NBBO), regardless
  of the account's data feed. It omits latency-related slippage, market impact,
  queue position, price improvement, and regulatory fees. Order size is not
  checked against displayed liquidity. A passive limit must become marketable;
  partial fills are randomly injected 10% of the time. These omissions can bias
  results in either direction. [Paper specifications](https://docs.alpaca.markets/us/docs/paper-trading)
- Alpaca staff describe market buys at the ask and sells at the bid. Spread costs
  are therefore present; this is not a universal zero-cost or midpoint-fill
  simulator. [Staff explanation](https://forum.alpaca.markets/t/paper-trading-order-fulfillment-delay/13324/5)
- In April 2026, Alpaca staff attributed an example's paper delay to injected
  partial fills. Their sample of **Alpaca live** orders had a 7 ms median and
  195 ms mean from broker creation to completed fill. This excludes the full
  client/data path, is not an IBKR benchmark, and is not a service guarantee.
  [Staff response](https://forum.alpaca.markets/t/paper-trading-market-orders-fill-delay/18681/5)
- IBKR Pro SmartRouting searches multiple exchanges and dark pools and can
  reroute orders. It does not guarantee a particular fill price or latency.
  [IBKR routing](https://www.interactivebrokers.com/en/trading/smart_routing.php)
- IBKR paper also simulates execution: top-of-book fills, no deep-book access,
  and simulated stops/complex orders. It is not live execution ground truth.
  [IBKR paper limitations](https://www.ibkrguides.com/advisorportal/aboutpapertradingaccount.htm)

## Data can change the strategy

Alpaca Basic supplies IEX-only stock data and indicative options data. Algo Trader
Plus is listed at $99/month and includes consolidated stock coverage and OPRA
options. Indicative options trades are delayed and quotes modified.
[Subscription documentation](https://docs.alpaca.markets/us/docs/about-market-data-api),
[options quote definition](https://docs.alpaca.markets/us/v1.4.2/reference/optionlatestquotes).

Inference for this repo: substituting IEX-only bars for the full-market data used
in ORB research changes opening ranges, volume rankings, and potentially entries.
It is not an equivalent replication. Use consistent consolidated data for signals
and their historical baselines. Options execution analysis needs actual quotes;
indicative prices cannot establish executable spreads.

## Existing repo evidence

[ORB experiments, experiment 3](orb_experiments.md): on 1,980 top-two entries and
574 stop-outs, the next-second trade-price proxy was 4.5 cents/share worse on
entry on average and 4.0 cents/share worse on stop-out. These are historical
trade-bar estimates against the original modeled prices, **not measured IBKR
fills**, and they do not include bid/ask or queue information. They are specific
to those selected stocks and triggers, not a universal slippage allowance.

[Later ORB/EMA research](orb_ema.md) uses the owner's assumed 1 cent/share costs.
That remains an assumption, not broker validation. Earlier notes calling paper
trading a measurement of "real slippage" should be interpreted as measuring
simulator behavior; only live execution observations reveal live fills.

[ORB executor](../src/horizon_trader/intraday/orb_live.py) starts its scanner step
at 09:35:05, then collects bars and submits a stop-limit bracket. Scanner and bar
acquisition delays must be measured too. Once accepted, broker-managed orders
reduce dependence on a local price-monitoring loop; stop-limit orders can still
miss trades and protective stops can slip.

## Proposed validation before relying on intraday performance

1. Timestamp market events, local receipt, signal creation, order send,
   acknowledgement, first/last fill, and cancellation acknowledgement. Synchronize
   clocks and distinguish broker timestamps from local receipt times. Report
   median, p95, p99, and missed fills separately for the open and later trading.
2. Replay executable quotes after delay scenarios of 100 ms, 500 ms, 1 second,
   and 5 seconds. These are stress scenarios, not estimated broker latencies.
   Preserve unfilled limits and partial positions; do not fill from last trade or
   midpoint by default. One-second bars cannot validate subsecond scenarios.
3. Apply IBKR commissions and route-dependent fees to a separate evaluation
   ledger. Its published US Tiered starting rate is $0.0035/share with a $0.35
   order minimum (subject to its cap), plus applicable third-party fees.
   [IBKR fees](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php)
4. Evaluate after-cost expectancy and missed winners, including held-out periods.
   Passing simulation establishes a candidate, not live equivalence. Keep the
   competition's broker P&L intact and report realism adjustments separately.

No changes to execution configuration or the competition plan were made.
