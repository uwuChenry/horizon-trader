"""Trading cost models for IBKR Pro US stock/ETF pricing.

Fixed:  $0.005/share, $1.00 min, max 1% of trade value, exchange/regulatory fees included.
Tiered: $0.0035/share (<=300k shares/month), $0.35 min, max 1%, plus exchange, clearing,
        and regulatory fees. Those pass-through fees aren't modeled here, so tiered is
        slightly optimistic for small orders.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class CostModel:
    per_share: float = 0.005
    min_per_order: float = 1.0
    max_pct_of_value: float = 0.01
    slippage_bps: float = 5.0

    def commission(self, quantity: float, price: float) -> float:
        value = abs(quantity) * price
        fee = max(self.min_per_order, abs(quantity) * self.per_share)
        return min(fee, self.max_pct_of_value * value)

    def fill_price(self, quantity: float, price: float) -> float:
        """Buys fill above the reference price and sells below it."""
        side = 1 if quantity > 0 else -1
        return price * (1 + side * self.slippage_bps / 10_000)


IBKR_PLANS = {
    "fixed": CostModel(per_share=0.005, min_per_order=1.0),
    "tiered": CostModel(per_share=0.0035, min_per_order=0.35),
}

ZERO_COSTS = CostModel(per_share=0.0, min_per_order=0.0, slippage_bps=0.0)


def ibkr_costs(plan: str, slippage_bps: float) -> CostModel:
    return replace(IBKR_PLANS[plan], slippage_bps=slippage_bps)
