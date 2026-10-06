"""Self-financing daily ETF account for research; not connected to live execution.

Signals dated t execute at the open of t + ``delay`` observations. Orders use
previous-close NAV and prices, with a 1% sizing buffer on unlevered targets.
Opening gaps can require purchases to be resized after the open to respect the
capital limit; these approximate executions are flagged by ``cash_clipped`` and
are not claimed as exact market-on-open fills. ``sizing='open'`` is a sensitivity
with same-opening-price sizing, not an executable opening-auction instruction.
An all-NaN
target row makes no decision. Holdings then drift, so buy-and-hold is one initial
decision rather than daily rebalancing.

Positions are units of a dividend/split-adjusted total-return fund. The ratio of
adjusted to raw opening price converts fund units to actual shares for fees and
whole-share orders. This assumes frictionless gross dividend reinvestment,
including fractional DRIP shares; withholding and dividend payment-date cash
timing are unmodeled. Liquidation may dispose of a fractional DRIP remainder.
Raw opens must be on the actual historical share basis, including historical
splits, for whole-share sizing to mean actual executable shares.

All prices must be complete. Missing opens raise rather than inventing fills.
Margin interest is charged on actual negative cash, ACT/360 across calendar days,
using the preceding observation's annual rate. Rates are decimal (0.05 = 5%).
Cash earns zero by default. ``broker`` is an explicit sensitivity model:
interest above a $10k cash threshold, scaled by NAV/$100k, at max(rate - 0.5%, 0).
It is an approximation, not a broker quotation or a tax model.

Intentional long exposure is limited to 1.5x. Open and close exposure above 2x is
flagged as a margin breach; intraday highs/lows, forced liquidation prices and
broker-specific house margins cannot be inferred from daily opens and closes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from horizon_trader.execution.costs import IBKR_PLANS, CostModel


@dataclass
class AccountResult:
    daily: pd.DataFrame
    trades: pd.DataFrame


_TRADE_COLUMNS = [
    "date",
    "signal_date",
    "symbol",
    "quantity",
    "adjusted_quantity",
    "raw_price",
    "adjusted_price",
    "fill_price",
    "notional",
    "fee",
    "slippage",
    "reason",
    "planned_quantity",
]


def _validate_panel(panel: pd.DataFrame, reference: pd.DataFrame, label: str) -> np.ndarray:
    if not panel.index.equals(reference.index) or not panel.columns.equals(reference.columns):
        raise ValueError(f"{label} must have exactly the target index and columns")
    values = panel.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError(f"{label} contains missing, nonfinite, or nonpositive prices")
    return values


def _purchase_quantity(
    quantity: float, price: float, available: float, costs: CostModel, cap: float = 1.0
) -> float:
    """Max shares respecting gross <= cap * postcost NAV; caller rounds shares."""
    if available <= 0:
        return 0.0
    fill = costs.fill_price(1, price)
    effective_price = price + cap * (fill - price)
    if quantity * effective_price + cap * costs.total(quantity, fill) <= available + 1e-10:
        return quantity
    low, high = 0.0, min(quantity, available / effective_price)
    for _ in range(45):
        middle = (low + high) / 2
        if middle * effective_price + cap * costs.total(middle, fill) <= available:
            low = middle
        else:
            high = middle
    return low


def run_account(
    targets: pd.DataFrame,
    adjusted_opens: pd.DataFrame,
    adjusted_closes: pd.DataFrame,
    raw_opens: pd.DataFrame,
    annual_rates: pd.Series | None = None,
    *,
    starting_cash: float = 5_000.0,
    costs: CostModel = IBKR_PLANS["tiered"],
    delay: int = 1,
    whole_shares: bool = True,
    borrow_spread: float = 0.015,
    rebalance_band: float = 0.02,
    cash_rate_mode: str = "zero",
    sizing: str = "previous_close",
    cash_buffer: float = 0.01,
) -> AccountResult:
    """Run a long-only research account, returning daily NAV and executed orders.

    Every target row is either entirely NaN or entirely finite nonnegative
    weights with sum <= 1.5. A zero row liquidates. Trading costs reduce capital
    before sizing, sells execute first, and purchases at <=1x targets cannot
    borrow to pay costs. ``turnover`` is absolute traded reference notional / NAV
    (one-way, not divided by two). ``interest`` is the signed change in cash.
    The first dated row always retains the original starting NAV because delay
    must be at least one; include this row in all benchmark comparisons.
    """
    if not isinstance(targets.index, pd.DatetimeIndex) or len(targets) < 2:
        raise ValueError("targets require at least two dated observations")
    if not targets.index.is_monotonic_increasing or not targets.index.is_unique:
        raise ValueError("target dates must be unique and increasing")
    if not targets.columns.is_unique or not len(targets.columns):
        raise ValueError("target symbols must be nonempty and unique")
    if not isinstance(delay, int) or delay < 1:
        raise ValueError("delay must be a positive integer: same-day execution is forbidden")
    if starting_cash <= 0 or borrow_spread < 0 or not 0 <= rebalance_band < 1:
        raise ValueError("invalid cash, borrow spread, or rebalance band")
    if cash_rate_mode not in {"zero", "broker", "broker_scaled"}:
        raise ValueError("cash_rate_mode must be zero or broker")
    if sizing not in {"previous_close", "open"} or not 0 <= cash_buffer < 1:
        raise ValueError("invalid sizing mode or cash buffer")
    target = targets.to_numpy(dtype=float)
    decisions = ~np.isnan(target).all(axis=1)
    active = target[decisions]
    if not np.isfinite(active).all() or (active < 0).any():
        raise ValueError("decision rows must contain complete finite long-only weights")
    if (active.sum(axis=1) > 1.5 + 1e-10).any():
        raise ValueError("intentional target gross must not exceed 1.5")
    opens = _validate_panel(adjusted_opens, targets, "adjusted_opens")
    closes = _validate_panel(adjusted_closes, targets, "adjusted_closes")
    raw = _validate_panel(raw_opens, targets, "raw_opens")
    if annual_rates is None:
        rates = np.zeros(len(targets))
    else:
        if not annual_rates.index.equals(targets.index):
            raise ValueError("annual_rates must have exactly the target index")
        rates = annual_rates.to_numpy(dtype=float)
        if not np.isfinite(rates).all():
            raise ValueError("annual_rates contains missing or nonfinite values")
    symbols = list(targets.columns)
    dates = targets.index
    qqq_index = symbols.index("QQQ") if "QQQ" in symbols else None
    units = np.zeros(len(symbols))
    cash = float(starting_cash)
    previous_nav = float(starting_cash)
    rows = []
    trades = []

    for i, date in enumerate(dates):
        borrow_cost = cash_income = 0.0
        if i:
            calendar_days = (date - dates[i - 1]).total_seconds() / 86_400
            if cash < 0:
                borrow_cost = -cash * max(rates[i - 1] + borrow_spread, 0) * calendar_days / 360
                cash -= borrow_cost
            elif cash_rate_mode in {"broker", "broker_scaled"}:
                cash_income = (
                    max(cash - 10_000, 0)
                    * min(previous_nav / 100_000, 1)
                    * max(rates[i - 1] - 0.005, 0)
                    * calendar_days
                    / 360
                )
                cash += cash_income
        values = units * opens[i]
        opening_nav = cash + values.sum()
        if opening_nav <= 0:
            raise RuntimeError(f"account insolvent at {date}: opening NAV {opening_nav}")
        open_gross = values.sum() / opening_nav
        fee_total = slippage_total = traded_notional = 0.0
        count = 0
        cash_clipped = 0
        signal_i = i - delay

        def execute(
            j: int,
            shares: float,
            reason: str = "target",
            planned: float | None = None,
            *,
            row_i: int = i,
            fill_date: pd.Timestamp = date,
            signal_row: int = signal_i,
        ) -> None:
            nonlocal cash, fee_total, slippage_total, traded_notional, count
            if abs(shares) < 1e-10:
                return
            price = raw[row_i, j]
            fill = costs.fill_price(shares, price)
            fee = costs.total(shares, fill)
            slippage = abs(shares) * abs(fill - price)
            adjusted_quantity = shares * price / opens[row_i, j]
            units[j] += adjusted_quantity
            if abs(units[j]) < 1e-10:
                units[j] = 0.0
            cash -= shares * fill + fee
            fee_total += fee
            slippage_total += slippage
            notional = abs(shares) * price
            traded_notional += notional
            count += 1
            trades.append(
                [
                    fill_date,
                    dates[signal_row],
                    symbols[j],
                    shares,
                    adjusted_quantity,
                    price,
                    opens[row_i, j],
                    fill,
                    notional,
                    fee,
                    slippage,
                    reason,
                    shares if planned is None else planned,
                ]
            )

        if signal_i >= 0 and decisions[signal_i]:
            weights = target[signal_i]
            unlevered = weights.sum() <= 1 + 1e-10
            sizing_nav = previous_nav if sizing == "previous_close" else opening_nav
            sizing_adjusted = closes[i - 1] if sizing == "previous_close" else opens[i]
            sizing_values = units * sizing_adjusted
            # raw/adjusted ratio represents the known corporate-action unit basis;
            # stochastic opening price cancels. No opening return enters sizing.
            sizing_raw = sizing_adjusted * raw[i] / opens[i]
            buffered_weights = weights * (1 - cash_buffer if unlevered else 1)
            # Reserve both fees and adverse slippage before setting dollar targets.
            # Taking the maximum reserve avoids oscillation at whole-share boundaries.
            reserve = 0.0
            order_shares = np.zeros(len(symbols))
            for _ in range(8):
                changes = buffered_weights * max(sizing_nav - reserve, 0) - sizing_values
                active_trade = abs(changes) / sizing_nav > rebalance_band
                active_trade |= (weights == 0) & (units > 0)
                if unlevered and cash < 0:
                    active_trade |= changes < 0
                order_shares = np.where(active_trade, changes / sizing_raw, 0.0)
                if whole_shares:
                    order_shares = np.sign(order_shares) * np.floor(abs(order_shares) + 1e-10)
                # Total-return units can contain fractional dividend reinvestments.
                exits = (weights == 0) & (units > 0)
                order_shares[exits] = -values[exits] / raw[i, exits]
                estimated_cost = 0.0
                for j in np.flatnonzero(abs(order_shares) > 1e-10):
                    shares = order_shares[j]
                    fill = costs.fill_price(shares, sizing_raw[j])
                    estimated_cost += costs.total(shares, fill)
                    estimated_cost += abs(shares) * abs(fill - sizing_raw[j])
                if estimated_cost <= reserve + 1e-9:
                    break
                reserve = estimated_cost
            for j in np.flatnonzero(order_shares < -1e-10):
                execute(j, order_shares[j])
            for j in np.flatnonzero(order_shares > 1e-10):
                shares = order_shares[j]
                current_values = (units * opens[i]).sum()
                current_nav = cash + current_values
                cap = weights.sum()
                available = cap * current_nav - current_values
                shares = _purchase_quantity(shares, raw[i, j], available, costs, cap)
                if whole_shares:
                    shares = np.floor(shares + 1e-10)
                clipped = shares < order_shares[j] - 1e-8
                cash_clipped += int(clipped)
                execute(
                    j,
                    shares,
                    "opening_gap_resize" if clipped else "target",
                    planned=order_shares[j],
                )
            # A band or whole-share truncation must not silently preserve a debit
            # after a deliberate return to an unlevered target.
            if unlevered and cash < -1e-8:
                for j in np.argsort(-(units * opens[i])):
                    available = units[j] * opens[i, j] / raw[i, j]
                    if available < 1e-10 or cash >= -1e-8:
                        continue
                    low, high = 0.0, available
                    for _ in range(45):
                        middle = (low + high) / 2
                        fill = costs.fill_price(-middle, raw[i, j])
                        proceeds = middle * fill - costs.total(-middle, fill)
                        if proceeds >= -cash:
                            high = middle
                        else:
                            low = middle
                    shares = min(np.ceil(high) if whole_shares else high, available)
                    execute(j, -shares, "remove_unintended_debit")
                if cash < -1e-7:
                    raise RuntimeError(f"could not remove unintended debit at {date}")
            if abs(cash) < 1e-8:
                cash = 0.0

        after_open_nav = cash + (units * opens[i]).sum()
        open_gross = max(open_gross, (units * opens[i]).sum() / after_open_nav)
        close_values = units * closes[i]
        nav = cash + close_values.sum()
        if nav <= 0 or after_open_nav <= 0:
            raise RuntimeError(f"account insolvent at {date}: closing NAV {nav}")
        gross = close_values.sum() / nav
        rows.append(
            {
                "equity": nav,
                "cash": cash,
                "opening_equity": opening_nav,
                "gross_exposure": gross,
                "qqq_exposure": close_values[qqq_index] / nav if qqq_index is not None else 0,
                "open_gross_exposure": open_gross,
                "fees": fee_total,
                "slippage": slippage_total,
                "costs": fee_total + slippage_total,
                "interest": cash_income - borrow_cost,
                "borrow_cost": borrow_cost,
                "cash_income": cash_income,
                "notional_turnover": traded_notional,
                "turnover": traded_notional / opening_nav,
                "order_count": count,
                "margin_breach": open_gross > 2 + 1e-10 or gross > 2 + 1e-10,
                "cash_clipped": cash_clipped,
            }
        )
        previous_nav = nav
    return AccountResult(
        pd.DataFrame(rows, index=dates), pd.DataFrame(trades, columns=_TRADE_COLUMNS)
    )
