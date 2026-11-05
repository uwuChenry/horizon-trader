# Inverted ORB: fading the opening-range breakout

Run 2026-09-27 with `uv run python -m horizon_trader.intraday.orb_inverted`. Code:
`src/horizon_trader/intraday/orb_inverted.py`. Follows [ORB on Stocks in Play](orb_stocks_in_play.md)
and [ORB experiments](orb_experiments.md).

**The question:** ORB loses on most days, so would doing the opposite win more often, with
smaller gains?

## Answer first

- **Yes, it wins more often, and it still loses money.** The exact mirror of ORB (sell where
  ORB buys, take profit where ORB's stop was) wins **53% of trades** instead of ORB's 46%. But
  its average win is +0.72R while its average loss is −1.05R, and its worst trade is −13.9R.
  At $5k (top 1, IBKR Tiered) it made **−26% a year with a −79% drawdown**. ORB over the same
  days made +18.8% (no slippage) or +7.4% (4c on stop fills).
- **The mirror is minus ORB, and can't be anything else.** Each of its trades is exactly the
  negative of an ORB trade before costs (the code checks this on every one of the 997 trades),
  and it pays commissions on top. ORB's edge comes from a few huge winners: MRNA +13.9R, and
  the best 5% of trades carry more than the whole profit. The mirror turns those into huge
  losers, with no stop to cap them.
- **Adding risk control doesn't rescue the fade either.** Fade with a 1 ATR stop: −9.6% a year.
  Fade with a 1 ATR stop and a 1 ATR target: −11.9%. Both fail in both halves.
- **The literal "short when the first candle closes up"** (breakdown of the range low) was the
  least bad: −0.2% a year with no slippage, −5.9% with it. It was positive only in 2024–26
  (+7.7%, Sharpe 0.63). It still fails the pre-registered test, and after slippage it loses.
- **Why the intuition misleads:** win rate says nothing about profit. What matters is
  win rate × average win − loss rate × average loss. A strategy that loses 54% of the time can
  be good (ORB) if the wins are larger than the losses. Its mirror, winning 53% of the time, is
  bad for exactly that reason.

## Variants (pre-registered, fixed before running)

All use ORB's candidates and sizing: top N by relative volume, 5-minute opening range,
1 ATR stop distance for sizing, 1% risk, at most 4x, $5k IBKR Pro Tiered.

| | entry | stop | target | exit |
|---|---|---|---|---|
| ORB (baseline) | stop order at the breakout level | 1 ATR | none | close |
| M. mirror | limit sell/buy at the breakout level (the other side of ORB) | none | 1 ATR (ORB's stop) | close |
| F. fade with stop | limit at the breakout level | 1 ATR | none | close |
| B. fade bracket | limit at the breakout level | 1 ATR | 1 ATR | close |
| X. flipped direction | stop order at the opposite side of the range | 1 ATR | none | close |

Pass rule: beat ORB's Sharpe in both 2021–23 and 2024–26.

**Fill model:** minute bars are walked open → low → high → close (up bars) or open → high →
low → close (down bars). This is ORB's own "path" convention, and the new simulator matches
ORB's backtest on all 19,934 top-20 trades, exits included.
- Limit orders fill whenever the price touches them. That's optimistic for fades: a real
  limit at the breakout level often won't fill when the price only touches it and reverses,
  and those are the fade's best trades.
- The "4c" rows charge the measured stop-market slippage on stop-order fills. Limit fills and
  close exits pay none.

## Results

### Trade shape before costs (top 1, 997 trades, Oct 2021 – Sep 2026)

| variant | win rate | avg win | avg loss | avg R | worst | best | total R |
|---|---|---|---|---|---|---|---|
| ORB | 46% | +1.06R | −0.71R | +0.11R | −1.5R | +13.9R | +110 |
| M. mirror | 53% | +0.72R | −1.05R | −0.11R | −13.9R | +1.5R | −110 |
| F. fade, stop | 42% | +0.97R | −0.73R | −0.02R | −2.1R | +10.8R | −19 |
| B. fade bracket | 48% | +0.72R | −0.72R | −0.04R | −1.6R | +1.5R | −36 |
| X. flipped | 46% | +0.80R | −0.64R | +0.03R | −1.2R | +8.0R | +17 |

With the top 20 candidates the picture is the same: ORB +0.03R per trade, mirror −0.03R,
fades −0.02 to −0.03R, flipped +0.00R.

### $5k, top 1, IBKR Tiered

| variant | CAGR, 0c | Sharpe, 0c | max DD, 0c | CAGR, 4c stop fills | Sharpe, 4c | 2021-23 / 2024-26 Sharpe (0c) |
|---|---|---|---|---|---|---|
| ORB | +18.8% | 1.03 | −20% | +7.4% | 0.48 | 0.95 / 1.05 |
| M. mirror | −26.4% | −1.62 | −79% | −26.4% | −1.62 | −1.48 / −1.53 |
| F. fade, stop | −9.6% | −0.52 | −43% | −12.2% | −0.69 | −1.23 / −0.04 |
| B. fade bracket | −11.9% | −1.07 | −50% | −14.2% | −1.28 | −0.84 / −1.18 |
| X. flipped | −0.2% | 0.04 | −22% | −5.9% | −0.46 | −0.94 / +0.63 |

All four inverted variants **fail** the pass rule, with or without slippage. The mirror pays
no slippage in this model (limit entry, limit target, close exit), and it's still the worst.

## Exploratory: fade brackets at other risk:reward ratios

Added after the main test, because the owner asked whether a 2:1 bracket would fix the fade
(`orb_inverted --brackets`). These are 9 configurations chosen after seeing results, so any
winner would need out-of-sample confirmation. None won. Each trade risks 1% at its own stop.
$5k, top 1, IBKR Tiered.

| risk : reward (ATR) | win rate | break-even win rate | avg R before costs | worst R | CAGR, 0c | CAGR, 4c stop fills | Sharpe 21-23 / 24-26 (0c) |
|---|---|---|---|---|---|---|---|
| 0.5 : 0.5 | 47.5% | 50% | −0.06 | −3.2 | −17.4% | −23.4% | −0.86 / −1.71 |
| 0.5 : 1 | 37.5% | 33% | −0.04 | −3.2 | −15.0% | −22.2% | −0.45 / −1.15 |
| 0.5 : 2 | 33.6% | 20% | −0.02 | −3.2 | −12.5% | −20.3% | −0.30 / −0.68 |
| 1 : 0.5 | 58.8% | 67% | −0.03 | −1.6 | −11.3% | −13.2% | −1.32 / −1.21 |
| 1 : 1 | 47.5% | 50% | −0.04 | −1.6 | −11.9% | −14.2% | −0.84 / −1.18 |
| 1 : 2 | 43.3% | 33% | −0.02 | −1.6 | −10.0% | −12.4% | −0.73 / −0.64 |
| 2 : 0.5 | 62.9% | 80% | −0.03 | −1.2 | −9.0% | −9.3% | −2.05 / −1.23 |
| 2 : 1 | 52.0% | 67% | −0.03 | −1.2 | −10.6% | −11.0% | −1.60 / −1.45 |
| 2 : 2 | 47.6% | 50% | −0.03 | −1.2 | −10.6% | −11.1% | −1.34 / −1.25 |

- **Every bracket has the same slightly negative expectancy** (−0.02 to −0.06R per trade before
  costs), and every one loses money in both halves. Moving the stop and target trades win rate
  against win size, but it can't change the sign. After a breakout on a Stock in Play, the
  price drifts in the breakout direction (that drift is ORB's +0.11R), so any position against
  it starts with negative drift.
- **Tight targets raise the win rate, but never to break-even.** A 2 ATR stop with a 0.5 ATR
  target wins 63% of the time and needs 80%.
- **Wide targets beat their break-even win rate and still lose** (1 : 2 wins 43% against a 33%
  break-even). Many trades end at the close having hit neither level, so the average "win" is
  much smaller than the target. The break-even formula assumes every trade hits one of the two.
- **Tight stops lose more than 1R on gaps.** With a 0.5 ATR stop the worst trade was −3.2R: a
  one-minute jump straight through the stop.

## Takeaways

- "It loses most days, so do the opposite" only works for a strategy with *negative*
  expectancy. ORB's expectancy before costs is positive, so its mirror is negative by
  construction.
- More wins with smaller gains is the shape of **selling insurance**: steady small profits
  and occasional disasters. Here the disasters are the Stocks in Play days that run 40%
  (MRNA on 2026-08-19 would have been −13.9R, which is −14% of the account in one trade at 1%
  risk).
- ORB's weakness at $5k is costs (the per-order minimum and slippage), not its win rate.
  Inverting doesn't avoid the costs.
