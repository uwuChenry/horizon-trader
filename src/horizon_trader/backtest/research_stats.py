"""Capital-consistent metrics and paired dependence-aware diagnostics for research."""

from __future__ import annotations

import numpy as np
import pandas as pd


def slice_period(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Include the previous NAV so the first return in a subperiod is not dropped."""
    chosen = frame.loc[start:end]
    if chosen.empty:
        raise ValueError(f"Empty evaluation period {start}..{end}")
    first = frame.index.get_loc(chosen.index[0])
    if first:
        chosen = pd.concat([frame.iloc[first - 1 : first], chosen])
    return chosen


def risk_free(index: pd.DatetimeIndex, annual: pd.Series) -> pd.Series:
    rate = annual.reindex(index, method="ffill").shift(1).fillna(0)
    return rate * index.to_series().diff().dt.days.fillna(0) / 360


def drawdown_days(equity: pd.Series) -> int:
    """Longest calendar time below an earlier peak, including unrecovered episodes."""
    peak = float(equity.iloc[0])
    peak_date = equity.index[0]
    longest = 0
    underwater = False
    for day, value in equity.items():
        if value < peak or underwater:
            longest = max(longest, (day - peak_date).days)
        if value >= peak:
            peak, peak_date = float(value), day
            underwater = False
        else:
            underwater = True
    return longest


def metrics(daily: pd.DataFrame, annual: pd.Series, benchmark: pd.Series) -> dict:
    eq = daily.equity
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    ret = eq.pct_change().iloc[1:]
    rf = risk_free(eq.index, annual).iloc[1:]
    excess = ret - rf
    std = excess.std(ddof=1)
    downside = np.sqrt(np.mean(np.minimum(excess, 0) ** 2))
    dd = eq / eq.cummax() - 1
    ref = benchmark.reindex(eq.index).pct_change().iloc[1:] - rf
    beta = float(excess.cov(ref) / ref.var()) if ref.var() else np.nan
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1)
    counted = daily.iloc[1:]
    return {
        "start_nav_date": str(eq.index[0].date()),
        "end": str(eq.index[-1].date()),
        "sessions": len(ret),
        "cagr": cagr,
        "max_drawdown": float(dd.min()),
        "drawdown_days": drawdown_days(eq),
        "sharpe": float(excess.mean() / std * np.sqrt(252)) if std else np.nan,
        "sharpe_zero": float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() else np.nan,
        "sortino": float(excess.mean() / downside * np.sqrt(252)) if downside else np.nan,
        "volatility": float(ret.std() * np.sqrt(252)),
        "calmar": cagr / abs(dd.min()) if dd.min() < 0 else np.nan,
        "beta_qqq": beta,
        "alpha_annual": float((excess.mean() - beta * ref.mean()) * 252),
        "mean_exposure": float(counted.gross_exposure.mean()),
        "max_exposure": float(max(counted.gross_exposure.max(), counted.open_gross_exposure.max())),
        "mean_qqq_exposure": float(counted.qqq_exposure.mean()),
        "turnover_annual": float(counted.turnover.sum() / years),
        "orders": int(counted.order_count.sum()),
        "fees": float(counted.fees.sum()),
        "slippage": float(counted.slippage.sum()),
        "borrow_cost": float(counted.borrow_cost.sum()),
        "cash_income": float(counted.cash_income.sum()),
        "margin_breach_days": int(counted.margin_breach.sum()),
        "cash_clipped": int(counted.cash_clipped.sum()),
        "final_equity": float(eq.iloc[-1]),
    }


def objective(candidate: dict, benchmark: dict) -> tuple[bool, float, float]:
    gap = candidate["cagr"] - benchmark["cagr"]
    reduction = 1 - abs(candidate["max_drawdown"]) / abs(benchmark["max_drawdown"])
    return bool(gap > 0 and reduction >= 0.10), float(gap), float(reduction)


def choose_development(table: pd.DataFrame, names: list[str], reference: str) -> dict:
    """The selection rule specified before performance was observed."""
    candidates = table.loc[names]
    limit = 0.9 * abs(table.loc[reference, "max_drawdown"])
    eligible = candidates[candidates.max_drawdown.abs() <= limit]
    fallback = eligible.empty
    ranked = candidates if fallback else eligible
    column = "calmar" if fallback else "cagr"
    selected = sorted(ranked.index, key=lambda name: (-ranked.loc[name, column], name))[0]
    return {"selected": selected, "fallback": fallback, "ranking_metric": column}


def bootstrap_diagnostics(
    returns: pd.DataFrame,
    reference: str,
    names: list[str],
    *,
    samples=2000,
    block=63,
    seed=20261001,
) -> pd.DataFrame:
    """Circular paired blocks, centered max-t across the entire candidate family.

    Confidence intervals condition on the observed sample and modeling choices.
    Resampled objective frequency is NOT a posterior probability or significance test.
    """
    rng = np.random.default_rng(seed)
    r = returns[[reference, *names]].dropna().to_numpy()
    n = len(r)
    if n < block * 2:
        raise ValueError("Insufficient observations for the registered block length")
    offsets = np.arange(block)
    starts = rng.integers(0, n, size=(samples, int(np.ceil(n / block))))
    indices = ((starts[:, :, None] + offsets) % n).reshape(samples, -1)[:, :n]
    log_r = np.log1p(r)
    observed = (log_r[:, 1:] - log_r[:, :1]).mean(axis=0) * 252
    boot = np.empty((samples, len(names)))
    probabilities = []

    def statistics(values):
        path = np.concatenate([np.ones((samples, 1)), np.exp(values.cumsum(axis=1))], axis=1)
        dd = (path / np.maximum.accumulate(path, axis=1) - 1).min(axis=1)
        return values.mean(axis=1) * 252, dd

    qgrowth, qdd = statistics(log_r[indices, 0])
    for j in range(len(names)):
        growth, dd = statistics(log_r[indices, j + 1])
        boot[:, j] = growth - qgrowth
        probabilities.append(np.mean((growth > qgrowth) & (np.abs(dd) <= 0.9 * np.abs(qdd))))
    se = boot.std(axis=0, ddof=1)
    centered_z = (boot - observed) / np.where(se > 0, se, np.inf)
    null_max = centered_z.max(axis=1)
    observed_z = observed / np.where(se > 0, se, np.inf)
    p = (1 + (null_max[:, None] >= observed_z).sum(axis=0)) / (samples + 1)
    lower, upper = np.quantile(boot, [0.025, 0.975], axis=0)
    return pd.DataFrame(
        {
            "strategy": names,
            "annual_log_growth_gap": observed,
            "ci95_low": lower,
            "ci95_high": upper,
            "familywise_one_sided_p": p,
            "resampled_joint_objective_frequency": probabilities,
            "samples": samples,
            "block_sessions": block,
        }
    )
