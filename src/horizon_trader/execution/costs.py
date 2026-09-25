"""Trading cost models for IBKR Pro US stock/ETF pricing (rates verified 2026-09-24).

Fixed:  $0.005/share, $1.00 min, max 1% of trade value. Exchange and clearing fees are
        included; the SEC and FINRA transaction fees on sells are passed through.
Tiered: $0.0035/share (<=300k shares/month), $0.35 min, max 1%, plus clearing ($0.0002/share),
        exchange fees and the same regulatory fees on sells. Exchange fees depend on venue and
        on whether the order adds or removes liquidity; TIERED_EXCHANGE is an ASSUMED flat
        remove-liquidity rate (marketable orders), not a verified number.

`commission()` is the broker's commission alone; `fees()` the pass-through and regulatory
fees; `total()` both, which is what a fill actually costs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

SEC_FEE = 0.0000206  # $ per $ of value sold
FINRA_TAF = 0.000195  # $ per share sold
CLEARING = 0.0002  # $ per share, Tiered (NSCC/DTC)
TIERED_EXCHANGE = 0.003  # $ per share, ASSUMED remove-liquidity fee


@dataclass(frozen=True)
class CostModel:
    per_share: float = 0.005
    min_per_order: float = 1.0
    max_pct_of_value: float = 0.01
    slippage_bps: float = 5.0
    pass_through_per_share: float = 0.0  # exchange + clearing, charged on every fill
    sec_fee_rate: float = 0.0  # on sells
    taf_per_share: float = 0.0  # on sells

    def commission(self, quantity: float, price: float) -> float:
        value = abs(quantity) * price
        fee = max(self.min_per_order, abs(quantity) * self.per_share)
        return min(fee, self.max_pct_of_value * value)

    def fees(self, quantity: float, price: float) -> float:
        """Pass-through fees on every fill plus regulatory fees when selling (quantity < 0)."""
        shares = abs(quantity)
        fee = shares * self.pass_through_per_share
        if quantity < 0:
            fee += shares * price * self.sec_fee_rate + shares * self.taf_per_share
        return fee

    def total(self, quantity: float, price: float) -> float:
        return self.commission(quantity, price) + self.fees(quantity, price)

    def fill_price(self, quantity: float, price: float) -> float:
        """Buys fill above the reference price and sells below it."""
        side = 1 if quantity > 0 else -1
        return price * (1 + side * self.slippage_bps / 10_000)


_REGULATORY = dict(sec_fee_rate=SEC_FEE, taf_per_share=FINRA_TAF)
IBKR_PLANS = {
    "fixed": CostModel(per_share=0.005, min_per_order=1.0, **_REGULATORY),
    "tiered": CostModel(
        per_share=0.0035,
        min_per_order=0.35,
        pass_through_per_share=CLEARING + TIERED_EXCHANGE,
        **_REGULATORY,
    ),
}

ZERO_COSTS = CostModel(per_share=0.0, min_per_order=0.0, slippage_bps=0.0)


def ibkr_costs(plan: str, slippage_bps: float) -> CostModel:
    return replace(IBKR_PLANS[plan], slippage_bps=slippage_bps)
