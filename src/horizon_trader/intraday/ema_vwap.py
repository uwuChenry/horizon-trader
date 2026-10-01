"""Two indicator rules from the internet, tested honestly: 12-EMA trend and EMA9 x VWAP.

    uv run python -m horizon_trader.intraday.ema_vwap [--tickers SPY QQQ]

Pre-registered 2026-09-28 (the owner's ideas; the settings are theirs, nothing tuned):
  bars       5-minute candles built from Massive minute bars, regular session only. EMAs carry
             across days (a regular-trading-hours chart); VWAP resets each session.
  E12        EMA(12) of 5-minute closes. SAR: long when the close is above it, short below,
             reversing at every cross ("keep going"). LONG: long above, flat below ("exit
             early").
  V9         EMA(9) of 5-minute closes vs the session VWAP with source (O+H+L+C)/4 on the
             5-minute bars. SAR: long when EMA9 > VWAP, short below. LONG: long / flat.
  timing     signal on each 5-minute close (e.g. the 9:30-9:34 candle closes at 9:35), fill at
             the next minute's open; everything flat at the close (market-on-close).
  size       1x equity, no leverage; $5k and $100k.
  costs      IBKR Pro Tiered + 1 cent/share slippage on every fill except the close; and 0c.
  control    always long from 9:35 to the close: any rule must beat plain intraday drift.
  pass       net profitable AND a higher Sharpe than the control, in both 2021-23 and 2024-26.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from horizon_trader.backtest.metrics import summarize
from horizon_trader.intraday import market_momentum as MM

BLOCK = 5
PERIODS = {"all": (None, None), "2021-23": (None, "2023-12-31"), "2024-26": ("2024-01-01", None)}
RULES = ("E12 SAR", "E12 LONG", "V9 SAR", "V9 LONG", "control: long 9:35-close")


def five_min(minute: pd.DataFrame, bars: MM.Bars) -> dict[str, pd.DataFrame]:
    """Day x 5-minute-block OHLCV (block b = minutes 5b .. 5b+4 after 9:30)."""
    m = minute.copy()
    since = m["ts"] - m["date"].dt.tz_localize(m["ts"].dt.tz) - pd.Timedelta(hours=9.5)
    m["j"] = (since // pd.Timedelta(minutes=1)).astype(int)
    m = m[(m["j"] >= 0) & (m["j"] < MM.SESSION)]
    m["b"] = m["j"] // BLOCK
    g = m.sort_values("ts").groupby(["date", "b"])
    agg = g.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    out = {
        k: agg[k].unstack("b").reindex(index=bars.close.index, columns=range(MM.SESSION // BLOCK))
        for k in agg.columns
    }
    n_blocks = (bars.daily["session_len"] // BLOCK).to_numpy()[:, None]
    live = np.arange(MM.SESSION // BLOCK)[None, :] < n_blocks
    out["close"] = out["close"].ffill(axis=1).where(live)
    return out


def ema_across_days(close: pd.DataFrame, span: int) -> pd.DataFrame:
    """EMA over the session blocks in time order, carried from one day to the next. Causal:
    the value at a block uses that block's close and earlier ones only."""
    flat = close.stack(future_stack=True)
    ema = flat.dropna().ewm(span=span, adjust=False).mean().reindex(flat.index)
    return ema.unstack().reindex_like(close)


def session_vwap(b: dict[str, pd.DataFrame]) -> pd.DataFrame:
    typical = (b["open"] + b["high"] + b["low"] + b["close"]) / 4
    pv = (typical * b["volume"]).fillna(0).cumsum(axis=1)
    v = b["volume"].fillna(0).cumsum(axis=1)
    return (pv / v.where(v > 0)).where(b["close"].notna())


def targets(b: dict[str, pd.DataFrame], rule: str) -> pd.DataFrame:
    """Target position after each block's close: +1 / -1 / 0 (NaN inputs -> flat)."""
    c = b["close"]
    if rule.startswith("control"):
        return pd.DataFrame(1, index=c.index, columns=c.columns).where(c.notna(), 0)
    if rule.startswith("E12"):
        up = c > ema_across_days(c, 12)
        down = c < ema_across_days(c, 12)
    else:
        ema9, vwap = ema_across_days(c, 9), session_vwap(b)
        up, down = ema9 > vwap, ema9 < vwap
    short = -1 if rule.endswith("SAR") else 0
    return pd.DataFrame(np.where(up, 1, np.where(down, short, 0)), index=c.index, columns=c.columns)


def trades(bars: MM.Bars, b: dict[str, pd.DataFrame], rule: str) -> pd.DataFrame:
    """Round trips via market_momentum.day_trades: the check for block k is its last minute
    (5k + 4); the fill is the next minute's open; open positions exit at the official close."""
    tgt = targets(b, rule)
    checks = [BLOCK * k + BLOCK - 1 for k in range(MM.SESSION // BLOCK)]
    rows = []
    for day in bars.close.index:
        d = bars.daily.loc[day]
        if not np.isfinite(d["close"]):
            continue
        fill = bars.fill.loc[day].to_numpy(float)
        rows += MM.day_trades(
            tgt.loc[day].to_numpy(), checks, fill, d["close"], int(d["session_len"]), day, rule
        )
    return pd.DataFrame(rows, columns=MM.TRADE_COLS)


def evaluate(t, daily, calendar, equity: float, slip: float, plan: str):
    acct = MM.Account(
        equity=equity,
        plan=plan,
        slippage=slip,
        vol_target=None,
        leverage=1.0,
    )
    out = {}
    for p, (a, z) in PERIODS.items():
        cal = calendar[(calendar >= (a or calendar[0])) & (calendar <= (z or calendar[-1]))]
        tt = t[t["date"].isin(cal)]
        eq, fills = MM.run_portfolio(tt, daily, acct, cal)
        s = summarize(eq)
        out[p] = {
            "CAGR": s.get("CAGR"),
            "Sharpe": s.get("Sharpe"),
            "max DD": s.get("max DD"),
            "trades/day": len(tt) / len(cal),
            "costs $": fills["costs"].sum() if len(fills) else 0.0,
        }
    return out


def gross_bps(t: pd.DataFrame) -> float:
    r = t["side"] * (t["exit_px"] / t["entry_px"] - 1)
    return 1e4 * r.mean()


def zero_commission(tickers: list[str]) -> None:
    """Added 2026-09-28 at the owner's request, after the main test: the same rules at a $0
    commission broker that routes to wholesalers (regulatory fees still charged), with the
    fill cost per share as the unknown: 0 / 0.25 / 0.5 / 1 cent."""
    slips = (0.0, 0.0025, 0.005, 0.01)
    for tk in tickers:
        minute, daily = MM.load_bars(tk)
        bars = MM.make_bars(minute, daily)
        b = five_min(minute, bars)
        calendar = pd.DatetimeIndex(bars.close.index)
        dd = daily.drop_duplicates("date").set_index("date")
        rows = []
        for rule in RULES:
            t = trades(bars, b, rule)
            for eq in (5_000.0, 100_000.0):
                row = {"rule": rule, "account": f"${eq / 1000:g}k"}
                for slip in slips:
                    s = evaluate(t, dd, calendar, eq, slip, "zero")
                    tag = f"{slip * 100:g}c"
                    row[f"CAGR {tag}"] = s["all"]["CAGR"]
                    row[f"Sharpe {tag}"] = s["all"]["Sharpe"]
                    row[f"21-23 / 24-26 {tag}"] = (
                        f"{s['2021-23']['CAGR']:+.1%} / {s['2024-26']['CAGR']:+.1%}"
                    )
                rows.append(row)
        df = pd.DataFrame(rows).set_index(["rule", "account"])
        for c in df.columns:
            if c.startswith("CAGR"):
                df[c] = df[c].map(lambda v: f"{v:+.1%}")
            elif c.startswith("Sharpe"):
                df[c] = df[c].map(lambda v: f"{v:+.2f}")
        print(f"=== {tk}: $0 commission (SEC/FINRA fees only), slippage per share per fill ===")
        print(df.to_string(), end="\n\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--tickers", nargs="+", default=["SPY", "QQQ"])
    p.add_argument("--zero", action="store_true", help="$0-commission broker, slippage sweep")
    args = p.parse_args()
    pd.set_option("display.width", 300)
    if args.zero:
        zero_commission(args.tickers)
        return
    for tk in args.tickers:
        minute, daily = MM.load_bars(tk)
        bars = MM.make_bars(minute, daily)
        b = five_min(minute, bars)
        calendar = pd.DatetimeIndex(bars.close.index)
        d = daily.drop_duplicates("date").set_index("date")["close"].reindex(calendar)
        hold = summarize(d / d.iloc[0])
        print(
            f"=== {tk}, {calendar[0]:%Y-%m-%d} .. {calendar[-1]:%Y-%m-%d}; buy and hold: "
            f"CAGR {hold['CAGR']:+.1%}, Sharpe {hold['Sharpe']:.2f}, max DD "
            f"{hold['max DD']:+.1%} ==="
        )
        rows, sharpe = [], {}
        for rule in RULES:
            t = trades(bars, b, rule)
            dd = daily.drop_duplicates("date").set_index("date")
            for label, eq, slip, plan in (
                ("gross", 100_000.0, 0.0, "none"),
                ("$100k net", 100_000.0, 0.01, "tiered"),
                ("$5k net", 5_000.0, 0.01, "tiered"),
            ):
                t_eval = evaluate(t, dd, calendar, eq, slip, plan)
                sharpe[(rule, label)] = {k: v["Sharpe"] for k, v in t_eval.items()}
                for per, s in t_eval.items():
                    rows.append(
                        {
                            "rule": rule,
                            "costs": label,
                            "period": per,
                            "bps/trade gross": gross_bps(t) if per == "all" else np.nan,
                        }
                        | s
                    )
        df = pd.DataFrame(rows).set_index(["rule", "costs", "period"])
        fmt = df.astype(object).copy()
        for c in ("CAGR", "max DD"):
            fmt[c] = df[c].map(lambda v: "-" if pd.isna(v) else f"{v:+.1%}")
        for c in ("Sharpe", "trades/day", "bps/trade gross"):
            fmt[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v:+.2f}")
        fmt["costs $"] = df["costs $"].map(lambda v: f"{v:,.0f}")
        print(fmt.to_string())
        verdict = []
        for rule in RULES[:-1]:
            for label in ("$100k net", "$5k net"):
                s, ctrl = sharpe[(rule, label)], sharpe[(RULES[-1], label)]
                cagr_ok = all(df.loc[(rule, label, h), "CAGR"] > 0 for h in ("2021-23", "2024-26"))
                beat = all(s[h] > ctrl[h] for h in ("2021-23", "2024-26"))
                verdict.append(f"{rule} {label}: {'PASS' if cagr_ok and beat else 'fail'}")
        print("pass (net profitable and beats the long-9:35-close control, both halves):")
        print("  " + "; ".join(verdict), "\n")


if __name__ == "__main__":
    main()
