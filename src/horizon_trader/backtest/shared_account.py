"""One cash account for multiple strategy intents, with whole-share net orders.

This is a research accounting model, not an IBKR margin engine. Marks and order
prices are supplied by a causal event replay. Cash receivables count toward NAV
but not purchasing power. Rejected quantities remain unfilled; no queued orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from horizon_trader.execution.costs import CostModel


@dataclass
class SharedAccount:
    cash: float
    costs: CostModel
    gross_limit: float = 2.0
    allow_short: bool = True
    reserved_gross: float = 0.0
    sleeves: dict[str, dict[str, float]] = field(default_factory=dict)
    receivables: list[tuple[object, float]] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    flows: list[dict] = field(default_factory=list)

    def positions(self):
        result = {}
        for holdings in self.sleeves.values():
            for symbol, quantity in holdings.items():
                result[symbol] = result.get(symbol, 0.0) + quantity
        return {s: q for s, q in result.items() if abs(q) > 1e-9}

    def equity(self, marks):
        return (
            self.cash
            + sum(q * marks[s] for s, q in self.positions().items())
            + sum(amount for _, amount in self.receivables)
        )

    def gross(self, marks):
        return sum(abs(q * marks[s]) for s, q in self.positions().items())

    def split(self, symbol, ratio):
        if ratio <= 0 or not np.isfinite(ratio):
            raise ValueError("invalid split ratio")
        for holdings in self.sleeves.values():
            if symbol in holdings:
                holdings[symbol] *= ratio

    def dividend(self, day, symbol, per_share, pay_date, withholding=0.0):
        if pay_date < day or not 0 <= withholding < 1:
            raise ValueError("invalid payment date or withholding")
        quantity = self.positions().get(symbol, 0.0)
        gross = quantity * per_share
        amount = gross * (1 - withholding) if gross > 0 else gross
        if amount:
            self.receivables.append((pay_date, amount))
            self.flows.append(
                dict(
                    date=day,
                    kind="dividend_receivable",
                    symbol=symbol,
                    amount=amount,
                    pay_date=pay_date,
                )
            )

    def settle(self, day):
        due = sum(amount for pay_date, amount in self.receivables if pay_date <= day)
        self.receivables = [(d, a) for d, a in self.receivables if d > day]
        self.cash += due
        if due:
            self.flows.append(dict(date=day, kind="dividend_payment", amount=due))

    def rebalance(self, intents, marks, timestamp, *, slips=None, reason="signal", force=False):
        """Update supplied sleeve/symbol targets; unspecified holdings stay as-is.

        Net before commissions. Process risk reductions first. Each filled order
        immediately reserves cash and gross buying power for subsequent orders.
        Partial external fills retain internal crossing, then reduce unfilled
        same-direction requests in reverse sleeve insertion order. Force is only
        for mandatory liquidation; callers must log any resulting margin breach.
        """
        slips = slips or {}
        desired = {name: dict(q) for name, q in self.sleeves.items()}
        for name, updates in intents.items():
            desired.setdefault(name, {}).update(updates)
        old = self.positions()
        symbols = sorted({s for updates in intents.values() for s in updates})
        total = {s: sum(q.get(s, 0.0) for q in desired.values()) for s in symbols}
        for s in symbols:
            if not np.isfinite(marks[s]) or marks[s] <= 0:
                raise ValueError(f"invalid mark: {s}")
            if any(not np.isfinite(q.get(s, 0.0)) for q in desired.values()):
                raise ValueError("nonfinite quantity")
            if abs(total[s] - round(total[s])) > 1e-8:
                raise ValueError(
                    "orders require integer shares; cash-in-lieu needed for split dust"
                )
        symbols.sort(key=lambda s: (abs(total[s]) >= abs(old.get(s, 0)), s))
        for symbol in symbols:
            current = self.positions().get(symbol, 0.0)
            requested = total[symbol] - current
            target = total[symbol]
            reference = marks[symbol]
            slip = float(slips.get(symbol, 0.0))
            if not np.isfinite(slip) or slip < 0:
                raise ValueError("invalid adverse slippage")
            other_gross = self.gross(marks) - abs(current * reference) + self.reserved_gross
            tradable_nav = self.equity(marks) - sum(a for _, a in self.receivables)

            def feasible(
                final,
                current=current,
                reference=reference,
                slip=slip,
                tradable_nav=tradable_nav,
                other_gross=other_gross,
            ):
                delta = final - current
                fee = self.costs.total(delta, reference + np.sign(delta) * slip) if delta else 0
                after = tradable_nav - fee - abs(delta) * slip
                return (
                    after > 0
                    and other_gross + abs(final * reference) <= self.gross_limit * after + 1e-8
                )

            if not force and requested:
                if not self.allow_short:
                    target = max(0.0, target)
                if not feasible(target):
                    # Risk can be reduced even if the account already breached by drifting.
                    if abs(target) < abs(current) and target * current >= 0:
                        pass
                    else:
                        sign = np.sign(target)
                        low, high = 0, int(abs(target))
                        while low < high:
                            middle = (low + high + 1) // 2
                            if feasible(sign * middle):
                                low = middle
                            else:
                                high = middle - 1
                        target = sign * low
                        # An infeasible new target must not manufacture a liquidation.
                        if requested * (target - current) < 0:
                            target = current
            filled = target - current
            unfilled = requested - filled
            if unfilled:
                residual = unfilled
                for name in reversed(list(desired)):
                    before = self.sleeves.get(name, {}).get(symbol, 0.0)
                    delta = desired[name].get(symbol, 0.0) - before
                    if delta * residual > 0:
                        reduction = np.sign(residual) * min(abs(delta), abs(residual))
                        desired[name][symbol] -= reduction
                        residual -= reduction
                if abs(residual) > 1e-8:
                    raise RuntimeError("cannot attribute unfilled quantity")
            if filled:
                fill = reference + np.sign(filled) * slip
                if fill <= 0:
                    raise ValueError("nonpositive fill")
                fee = self.costs.total(filled, fill)
                self.cash -= filled * fill + fee
                self.orders.append(
                    dict(
                        time=timestamp,
                        symbol=symbol,
                        quantity=filled,
                        reference=reference,
                        price=fill,
                        fee=fee,
                        slippage=abs(filled) * slip,
                        reason=reason,
                    )
                )
            for name in desired:
                self.sleeves.setdefault(name, {})[symbol] = desired[name].get(symbol, 0.0)
            if requested or any(symbol in x for x in intents.values()):
                self.decisions.append(
                    dict(
                        time=timestamp,
                        symbol=symbol,
                        requested=requested,
                        filled=filled,
                        unfilled=unfilled,
                        reason=reason,
                        equity=self.equity(marks),
                        gross=self.gross(marks),
                        cash=self.cash,
                        force=force,
                    )
                )
        self.sleeves = {
            name: {s: q for s, q in holdings.items() if abs(q) > 1e-9}
            for name, holdings in self.sleeves.items()
        }
        return self.orders
