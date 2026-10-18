"""Causal, fixed-share competitor-pairs research engine; never submits orders.

See research/pairs_2026_10_12/protocol.md. Signal prices are total-return adjusted;
execution prices and dividend cash flows are in historical, as-traded share units.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.backtest.bundle import TRADE_COLUMNS
from horizon_trader.execution.costs import ZERO_COSTS, ibkr_costs

PRIMARY = (("KO", "PEP"), ("HD", "LOW"), ("MCD", "YUM"))
EXPANDED = (*PRIMARY, ("V", "MA"), ("XOM", "CVX"))


@dataclass(frozen=True)
class PairConfig:
    pairs: tuple[tuple[str, str], ...] = PRIMARY
    lookback: int = 60
    entry_z: float = 2.0
    stop_z: float = 4.0
    max_hold: int = 40
    capital: float = 5_000.0
    slippage_bps: float = 5.0
    borrow_rate: float = 0.01
    withholding: float = 0.30
    plan: str = "tiered"
    whole_shares: bool = True
    min_correlation: float = -1.0
    max_imbalance: float = 0.15
    min_equity: float = 2_000.0
    # Only charged if long positions exceed equity; normally zero at 1x gross.
    debit_rate: float = 0.08

    def __post_init__(self):
        names = [s for p in self.pairs for s in p]
        if not self.pairs or len(set(names)) != len(names):
            raise ValueError("Pairs must be nonempty and have disjoint symbols")
        if self.lookback < 3 or not 0 < self.entry_z < self.stop_z or self.max_hold < 1:
            raise ValueError("Invalid signal parameters")
        if min(self.capital, self.min_equity) <= 0:
            raise ValueError("Capital/minimum equity must be positive")
        if min(self.slippage_bps, self.borrow_rate, self.debit_rate) < 0:
            raise ValueError("Costs must be nonnegative")
        if not 0 <= self.withholding <= 1:
            raise ValueError("Invalid withholding")


@dataclass
class PairResult:
    daily: pd.DataFrame
    trades: pd.DataFrame
    fills: pd.DataFrame
    holdings: pd.DataFrame
    open_positions: pd.DataFrame
    signals: dict[str, pd.DataFrame]
    rejected: pd.DataFrame


def prepare_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Undo Yahoo's retrospective split basis before slicing the historical sample.

    Yahoo unadjusted OHLC/dividends still use today's share units. Only *future*
    splits multiply earlier prices; an ex-split day's prices use the new units.
    Total-return closes stay on their vendor basis, which cancels in log z-scores.
    """
    f = raw.copy().sort_index()
    f.index = pd.DatetimeIndex(f.index).tz_localize(None).normalize()
    split = f["Stock Splits"].fillna(0).replace(0, 1)
    factor = split.iloc[::-1].cumprod().iloc[::-1] / split
    return pd.DataFrame(
        {
            "open": f["Open"] * factor,
            "close": f["Close"] * factor,
            "signal": f["Adj Close"],
            "dividend": f["Dividends"].fillna(0) * factor,
            "split": split,
            "volume": f["Volume"],
        },
        index=f.index,
    )


def load_data(folder: Path, end: str = "2026-10-09") -> dict[str, pd.DataFrame]:
    symbols = sorted({s for p in EXPANDED for s in p} | {"SPY"})
    frames = {s: prepare_frame(pd.read_parquet(folder / f"{s}.parquet")) for s in symbols}
    last = min(pd.Timestamp(end), *(f.index.max() for f in frames.values()))
    calendar = frames["SPY"].loc["2016-01-01":last].index
    out = {
        k: pd.DataFrame({s: f[k].reindex(calendar) for s, f in frames.items()})
        for k in next(iter(frames.values())).columns
    }
    for k in ("open", "close", "signal", "split", "volume"):
        if out[k].isna().any().any() or (out[k] <= 0).any().any():
            raise ValueError(f"Missing/nonpositive {k}; do not silently fill market data")
    return out


def make_signals(bars: dict[str, pd.DataFrame], cfg: PairConfig) -> dict[str, pd.DataFrame]:
    out = {}
    for a, b in cfg.pairs:
        p = bars["signal"][[a, b]]
        s = np.log(p[a] / p[b])
        past = s.shift(1).rolling(cfg.lookback)
        mean, std = past.mean(), past.std()
        r = p.pct_change(fill_method=None)
        corr = r[a].shift(1).rolling(cfg.lookback).corr(r[b].shift(1))
        out[f"{a}/{b}"] = pd.DataFrame(
            {
                "spread": s,
                "mean": mean,
                "std": std,
                "z": (s - mean) / std.where(std > 1e-10),
                "correlation": corr,
            }
        )
    return out


@dataclass
class _Position:
    name: str
    symbols: tuple[str, str]
    q: np.ndarray
    direction: float
    mean: float
    std: float
    entry_z: float
    entry_date: pd.Timestamp
    signal_date: pd.Timestamp
    entry_i: int
    initial_signed_value: float
    entry_gross: float
    dividends: float = 0.0
    costs: dict = field(
        default_factory=lambda: dict.fromkeys(
            ["commission", "slippage", "borrow", "withholding", "financing"], 0.0
        )
    )


def simulate(
    bars: dict[str, pd.DataFrame],
    cfg: PairConfig | None = None,
    start: str = "2017-01-03",
    end: str | None = None,
) -> PairResult:
    """Close signals -> next-open orders; exact cash ledger, no daily rebalancing.

    Each result starts flat with warm-up data, includes a preperiod equity anchor,
    and ends marked to market with open positions left open (no free forced exit).
    """
    cfg = cfg or PairConfig()
    dates = bars["close"].index
    first = dates.searchsorted(pd.Timestamp(start))
    last = len(dates) if end is None else dates.searchsorted(pd.Timestamp(end), side="right")
    if first < 1 or first >= last:
        raise ValueError("Need at least one warm-up date and one trading date")
    signals = make_signals(bars, cfg)
    names = [f"{a}/{b}" for a, b in cfg.pairs]
    syms = [s for p in cfg.pairs for s in p]
    px = {k: bars[k][syms].to_numpy(float) for k in bars}
    sig = {name: f.to_numpy(float) for name, f in signals.items()}
    for k in ("open", "close", "signal", "split", "volume"):
        if not np.isfinite(px[k][first - 1 : last]).all() or (px[k][first - 1 : last] <= 0).any():
            raise ValueError(f"Invalid {k} in simulation interval")
    costs = ZERO_COSTS if cfg.plan == "zero" else ibkr_costs(cfg.plan, cfg.slippage_bps)
    cash = cfg.capital
    positions: dict[int, _Position] = {}
    pending: dict[int, dict] = {}
    fills, trades, holdings, rejected = [], [], [], []
    columns = ["commission", "slippage", "borrow", "withholding", "financing"]
    rows = [
        dict(
            date=dates[first - 1],
            equity=cash,
            cash=cash,
            gross=0.0,
            net=0.0,
            dividends=0.0,
            active_pairs=0,
            **dict.fromkeys(columns, 0.0),
        )
    ]

    def mark(j: int, field: str) -> tuple[float, float, float]:
        signed = gross = longs = 0.0
        for k, p in positions.items():
            v = p.q * px[field][j, 2 * k : 2 * k + 2]
            signed += v.sum()
            gross += np.abs(v).sum()
            longs += v.clip(min=0).sum()
        return float(signed), float(gross), float(longs)

    def execute(k: int, q: np.ndarray, i: int, action: str, signal_date, p: _Position):
        nonlocal cash
        mid = px["open"][i, 2 * k : 2 * k + 2]
        for symbol, qty, price in zip(cfg.pairs[k], q, mid, strict=True):
            fill = price * (1 + np.sign(qty) * cfg.slippage_bps / 10_000)
            comm = costs.total(qty, fill)
            slip = abs(qty) * abs(fill - price)
            cash -= qty * fill + comm
            p.costs["commission"] += comm
            p.costs["slippage"] += slip
            day_cost["commission"] += comm
            day_cost["slippage"] += slip
            fills.append(
                dict(
                    date=dates[i],
                    signal_date=signal_date,
                    pair=p.name,
                    symbol=symbol,
                    quantity=qty,
                    reference_price=price,
                    fill_price=fill,
                    commission=comm,
                    slippage=slip,
                    action=action,
                )
            )

    for i in range(first, last):
        day_cost = dict.fromkeys(columns, 0.0)
        day_div = 0.0
        days = (dates[i] - dates[i - 1]).days
        prev_signed, _, prev_longs = mark(i - 1, "close")
        prev_equity = cash + prev_signed
        finance = max(prev_longs - prev_equity, 0) * cfg.debit_rate * days / 360
        for k, p in positions.items():
            sl = slice(2 * k, 2 * k + 2)
            v = p.q * px["close"][i - 1, sl]
            borrow = -v.clip(max=0).sum() * cfg.borrow_rate * days / 360
            funding = finance * v.clip(min=0).sum() / max(prev_longs, 1e-12)
            p.q *= px["split"][i, sl]
            div = p.q * px["dividend"][i, sl]
            tax = div.clip(min=0).sum() * cfg.withholding
            dividend = div.sum()
            cash += dividend - tax - borrow - funding
            p.dividends += dividend
            day_div += dividend
            for key, val in (("borrow", borrow), ("withholding", tax), ("financing", funding)):
                p.costs[key] += val
                day_cost[key] += val
        # Exit orders are processed before entries; corporate actions precede both.
        for k, order in sorted(pending.items(), key=lambda item: item[1]["action"] != "exit"):
            if order["action"] == "exit":
                p = positions[k]
                final_value = (p.q * px["open"][i, 2 * k : 2 * k + 2]).sum()
                execute(k, -p.q, i, "exit", order["signal_date"], p)
                gross = final_value - p.initial_signed_value + p.dividends
                total_cost = sum(p.costs.values())
                trades.append(
                    dict(
                        entry_time=p.entry_date,
                        exit_time=dates[i],
                        symbol=p.name,
                        side=p.direction,
                        qty=1.0,
                        entry_px=p.entry_gross,
                        exit_px=p.entry_gross + p.direction * gross,
                        gross=gross,
                        costs=total_cost,
                        pnl=gross - total_cost,
                        entry_signal_date=p.signal_date,
                        exit_signal_date=order["signal_date"],
                        direction=p.direction,
                        entry_z=p.entry_z,
                        frozen_mean=p.mean,
                        frozen_std=p.std,
                        held_sessions=i - p.entry_i,
                        exit_reason=order["reason"],
                        dividends=p.dividends,
                        **p.costs,
                    )
                )
                del positions[k]
                continue
            q = order["q"] * px["split"][i, 2 * k : 2 * k + 2]
            v = q * px["open"][i, 2 * k : 2 * k + 2]
            signed, gross, _ = mark(i, "open")
            equity = cash + signed
            imbalance = abs(v.sum()) / max(np.abs(v).mean(), 1e-12)
            reason = None
            if equity < cfg.min_equity:
                reason = "minimum_equity"
            elif (q == 0).any():
                reason = "zero_share_leg"
            elif imbalance > cfg.max_imbalance:
                reason = "hedge_imbalance"
            elif gross + np.abs(v).sum() > equity * 1.001:
                reason = "gross_capacity"
            if reason:
                rejected.append(dict(date=dates[i], pair=names[k], reason=reason))
                continue
            p = _Position(
                names[k],
                cfg.pairs[k],
                q,
                order["direction"],
                order["mean"],
                order["std"],
                order["z"],
                dates[i],
                order["signal_date"],
                i,
                v.sum(),
                np.abs(v).sum(),
            )
            execute(k, q, i, "entry", order["signal_date"], p)
            positions[k] = p
        pending = {}
        signed, gross, _ = mark(i, "close")
        equity = cash + signed
        if equity <= 0:
            raise RuntimeError(
                "Account insolvent; stop simulation rather than compound invalid NAV"
            )
        emergency = gross > 1.5 * equity or equity < cfg.min_equity
        for k, name in enumerate(names):
            spread, mean, std, z, corr = sig[name][i]
            if k in positions:
                p = positions[k]
                frozen_z = (spread - p.mean) / p.std
                reason = None
                if emergency:
                    reason = "account_risk"
                elif p.direction * frozen_z <= -cfg.stop_z:
                    reason = "divergence_stop"
                elif p.direction * frozen_z >= 0:
                    reason = "convergence"
                elif i - p.entry_i + 1 >= cfg.max_hold:
                    reason = "time_stop"
                if reason:
                    pending[k] = dict(action="exit", reason=reason, signal_date=dates[i])
                for symbol, qty, price in zip(
                    p.symbols, p.q, px["close"][i, 2 * k : 2 * k + 2], strict=True
                ):
                    holdings.append(
                        dict(
                            date=dates[i],
                            pair=name,
                            ticker=symbol,
                            shares=qty,
                            price=price,
                            value=qty * price,
                            weight=qty * price / equity,
                        )
                    )
            elif (
                not emergency
                and np.isfinite([z, corr]).all()
                and cfg.entry_z <= abs(z) < cfg.stop_z
                and corr >= cfg.min_correlation
            ):
                direction = -float(np.sign(z))
                q = equity / (2 * len(cfg.pairs)) / px["close"][i, 2 * k : 2 * k + 2]
                if cfg.whole_shares:
                    q = np.floor(q)
                q *= np.array([direction, -direction])
                pending[k] = dict(
                    action="entry",
                    q=q,
                    direction=direction,
                    mean=mean,
                    std=std,
                    z=z,
                    signal_date=dates[i],
                )
        rows.append(
            dict(
                date=dates[i],
                equity=equity,
                cash=cash,
                gross=gross / equity,
                net=signed / equity,
                active_pairs=len(positions),
                dividends=day_div,
                **day_cost,
            )
        )
    open_rows = []
    for k, p in positions.items():
        gross = (p.q * px["close"][last - 1, 2 * k : 2 * k + 2]).sum()
        gross += p.dividends - p.initial_signed_value
        open_rows.append(
            dict(
                pair=p.name,
                entry_time=p.entry_date,
                gross=gross,
                costs=sum(p.costs.values()),
                pnl=gross - sum(p.costs.values()),
                qty_a=p.q[0],
                qty_b=p.q[1],
                **p.costs,
            )
        )
    daily = pd.DataFrame(rows).set_index("date")
    trade_frame = pd.DataFrame(trades) if trades else pd.DataFrame(columns=TRADE_COLUMNS)
    open_frame = pd.DataFrame(open_rows)
    accounted = trade_frame.pnl.sum() + (open_frame.pnl.sum() if len(open_frame) else 0)
    if not np.isclose(daily.equity.iloc[-1] - cfg.capital, accounted, atol=1e-7):
        raise AssertionError("Cash/trade P&L reconciliation failed")
    return PairResult(
        daily,
        trade_frame,
        pd.DataFrame(fills),
        pd.DataFrame(holdings),
        open_frame,
        signals,
        pd.DataFrame(rejected),
    )
