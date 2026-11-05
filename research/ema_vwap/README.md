# Two internet indicator rules: 5-minute 12-EMA and EMA9 × VWAP

Run 2026-09-28 with `uv run python -m horizon_trader.intraday.ema_vwap`. Code:
`src/horizon_trader/intraday/ema_vwap.py`, built on the minute-bar machinery in
`market_momentum.py`. SPY and QQQ, Oct 2021 – Sep 2026, Massive minute bars.

## Answer first

- **The 12-EMA rule is noise that pays commissions.** Reversing at every cross of the 5-minute
  12-EMA trades **13 times a day** and earns **0.09 bp (SPY) and −0.02 bp (QQQ) per trade**
  before costs. After IBKR costs and 1¢ slippage it **loses 24% a year on SPY and 33% on QQQ**
  at $100k, and about 40% a year at $5k. The long-only version (flat below the EMA) trades half
  as often and still loses 10–14% a year.
- **EMA9 × VWAP has a small edge, but it's mostly the market's intraday drift.** Long-only
  (long when EMA9 is above the session VWAP, else flat) makes **6.1% a year gross on SPY**,
  2.7% net at $100k (Sharpe 0.32). Simply being long from 9:35 to the close makes 4.3% gross
  and 2.6% net (Sharpe 0.25).
- **Only 1 of 16 net tests passed** the pre-registered rule (profitable and better than the
  always-long control in both 2021–23 and 2024–26): **V9 long-only on SPY at $100k**, by a hair
  (Sharpe 0.34 vs 0.32 in 2024–26). The same rule on QQQ fails in 2024–26. One pass in 16 is
  what chance would produce.
- **At $5k everything loses.** The $0.35 minimum commission on 2–26 orders a day costs more
  than any of these rules earn. The always-long control itself loses 1% a year at $5k.
- **Buy and hold beats all of it:** SPY 12.4% a year (Sharpe 0.77), QQQ 16.1% (0.77), with no
  screen time.

## Rules (pre-registered; the owner's settings, nothing tuned)

- **Candles:** 5-minute, built from Massive minute bars, regular session. EMAs carry across
  days (a regular-hours chart). The VWAP resets each session.
- **E12:** EMA(12) of 5-minute closes.
  - SAR: long above, short below, reversing at each cross ("keep going").
  - LONG: long above, flat below ("exit early").
- **V9:** EMA(9) of 5-minute closes vs the session VWAP, with source (O+H+L+C)/4 on the
  5-minute bars. SAR and LONG as above.
- **Timing:** signal at each 5-minute close, fill at the next minute's open, flat at the close
  (market-on-close).
- **Size and costs:** 1x equity; IBKR Pro Tiered plus 1¢ per share on every fill except the
  close; plus a zero-cost row.
- **Control:** long from 9:35 to the close every day.
- **Pass:** net profitable **and** a higher Sharpe than the control, in both halves.

## Results (full period; per-half rows are printed by the command)

| rule | ticker | trades/day | gross bp/trade | CAGR gross | CAGR net $100k | Sharpe net $100k | CAGR net $5k |
|---|---|---|---|---|---|---|---|
| E12 SAR | SPY | 13.3 | +0.09 | +2.3% | −24.1% | −1.94 | −39.7% |
| E12 LONG | SPY | 6.7 | +0.25 | +3.8% | −10.1% | −1.02 | −36.3% |
| V9 SAR | SPY | 3.2 | +0.94 | +7.0% | +0.2% | 0.08 | −12.9% |
| **V9 LONG** | SPY | 1.6 | +1.58 | +6.1% | **+2.7%** | **0.32** | −2.9% |
| control (long 9:35–close) | SPY | 1.0 | +2.08 | +4.3% | +2.6% | 0.25 | −1.0% |
| E12 SAR | QQQ | 13.6 | −0.02 | −2.2% | −32.6% | −2.14 | −43.7% |
| E12 LONG | QQQ | 6.8 | +0.17 | +2.3% | −13.7% | −1.09 | −38.4% |
| V9 SAR | QQQ | 3.2 | +1.22 | +8.6% | +0.7% | 0.13 | −9.3% |
| V9 LONG | QQQ | 1.6 | +2.07 | +7.9% | +3.9% | 0.36 | −1.0% |
| control | QQQ | 1.0 | +2.76 | +5.4% | +3.4% | 0.27 | −0.2% |
| buy and hold | SPY / QQQ | – | – | 12.4% / 16.1% | – | 0.77 / 0.77 | – |

V9 LONG on QQQ by half, net at $100k: +9.6% (2021–23), then −0.6% (2024–26), against the
control's +4.2% / +2.7%. It looks like a 2022 bear-market effect (flat when below VWAP avoided
some down days) that didn't repeat.

## Update: a $0-commission broker (`ema_vwap --zero`)

Added after the main test, at the owner's request. Commission is $0 and SEC/FINRA fees on
sells still apply. The cost per share of each fill is unknown: the wholesaler usually improves
on the quoted price, so 0.25–0.5¢ is realistic for SPY and QQQ. SPY, $5k:

| rule | 0¢ | 0.25¢ | 0.5¢ | 1¢ | halves at 0.5¢ (2021–23 / 2024–26) |
|---|---|---|---|---|---|
| E12 SAR | −4.5% | −7.3% | −10.0% | −14.7% | −7.9% / −11.5% |
| E12 LONG | +0.2% | −1.4% | −2.7% | −5.4% | −1.6% / −3.5% |
| V9 SAR | +5.0% | +4.4% | +3.4% | +2.3% | +4.8% / +2.1% |
| V9 LONG | +5.2% (Sharpe 0.58) | +4.9% | +4.5% (0.51) | +3.8% | +5.1% / +4.1% |
| control | +3.7% | +3.6% | +3.5% (0.32) | +3.4% | +2.9% / +3.7% |

- The 12-EMA still loses even with free, perfect fills: at 13 round trips a day, the SEC fee on
  sells alone exceeds its edge.
- **V9 long-only on SPY becomes a small, consistent positive** (+4.5% a year, beats the control
  in both halves). On QQQ it's +12.3% then +0.8%, below the control in 2024–26.
- It's still about a third of buy-and-hold (SPY 12.4%, Sharpe 0.77): an intraday rule is flat
  overnight, and a large share of stock returns has historically come overnight.
- **Quirk of the rule as specified:** the EMA carries across days while VWAP resets. After a gap
  down, EMA9 (still near yesterday's prices) sits above VWAP, so the first V9 signal of the day
  is a buy. Part of V9 LONG is "buy weak opens".

## Why these rules can't work at this size

- An EMA cross on 5-minute bars mostly reacts to noise. SPY's typical 5-minute move is a few
  basis points, the same size as the spread plus slippage. With 13 round trips a day, 1¢ of
  slippage on a $600 stock is about 0.2 bp per fill, and commissions add more. The E12 edge
  before costs is 0.09 bp per trade.
- "Keep going when there's momentum" is what the SAR version does, and there's no momentum to
  keep. The long-only version cuts trades in half but still trades far too often for its edge.
- The VWAP filter cuts trading to 1.6 round trips a day and earns about 1.6–2.1 bp per trade.
  That's real but small, and it's no better than being long all day.

## A bug caught before this note

This test was run once with a bug: its "gross" rows still paid commissions, because the cost
plan was chosen by account size. It was fixed before this note. The net rows were unaffected.
