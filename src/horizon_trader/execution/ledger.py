"""A virtual sub-account for one strategy, persisted under <data_dir>/live/<name>/.

Several strategies share one IBKR account, and the paper account holds $1M, so nothing is ever
sized from the account's net liquidation value (which also earns interest on cash a $5k
account wouldn't have). Each strategy keeps its own cash, positions and fill log instead:

    state.json   cash, positions, orders awaiting a fill, execution ids already booked
    fills.csv    one row per fill: price, actual commission, the cost model's commission
    equity.csv   one row per run date

Known gap: dividends are not credited, so the ledger trails a real account by the yield.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from horizon_trader.config import data_dir
from horizon_trader.execution.broker import Order
from horizon_trader.execution.costs import CostModel

FILL_COLUMNS = [
    "time", "strategy", "source", "symbol", "quantity", "price", "ref_price", "open_price",
    "commission", "modeled_commission", "exec_id",
]  # fmt: skip


@dataclass
class Pending:
    symbol: str
    quantity: float
    ref_price: float  # the close the order was sized on
    asof: str  # signal date (YYYY-MM-DD); the order fills at the next open


@dataclass
class Ledger:
    name: str
    cash: float
    holdings: dict[str, float] = field(default_factory=dict)
    pending: list[Pending] = field(default_factory=list)
    seen_exec_ids: list[str] = field(default_factory=list)
    root: Path | None = None

    # -- persistence ---------------------------------------------------------------------
    @staticmethod
    def directory(name: str, root: Path | None = None) -> Path:
        return (root or data_dir() / "live") / name

    @classmethod
    def load(cls, name: str, starting_cash: float, root: Path | None = None) -> Ledger:
        path = cls.directory(name, root) / "state.json"
        if not path.exists():
            return cls(name=name, cash=starting_cash, root=root)
        state = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            name=name,
            cash=state["cash"],
            holdings=state["holdings"],
            pending=[Pending(**p) for p in state["pending"]],
            seen_exec_ids=state["seen_exec_ids"],
            root=root,
        )

    def save(self) -> None:
        folder = self.directory(self.name, self.root)
        folder.mkdir(parents=True, exist_ok=True)
        state = {
            "cash": self.cash,
            "holdings": self.holdings,
            "pending": [asdict(p) for p in self.pending],
            "seen_exec_ids": self.seen_exec_ids[-5000:],
        }
        tmp = folder / "state.json.tmp"
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(folder / "state.json")

    # -- Broker-like views ---------------------------------------------------------------
    def positions(self) -> dict[str, float]:
        return dict(self.holdings)

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(q * prices[s] for s, q in self.holdings.items())

    # -- bookkeeping ---------------------------------------------------------------------
    def add_pending(self, orders: list[Order], prices: dict[str, float], asof: str) -> None:
        self.pending += [Pending(o.symbol, o.quantity, prices[o.symbol], asof) for o in orders]

    def apply_fill(
        self,
        *,
        time: str,
        source: str,
        symbol: str,
        quantity: float,
        price: float,
        commission: float,
        modeled_commission: float,
        ref_price: float = float("nan"),
        open_price: float = float("nan"),
        exec_id: str = "",
    ) -> None:
        """Book one fill: cash, position and a row in fills.csv. `quantity` is signed."""
        self.cash -= quantity * price + commission
        new_qty = self.holdings.get(symbol, 0.0) + quantity
        if abs(new_qty) < 1e-9:
            self.holdings.pop(symbol, None)
        else:
            self.holdings[symbol] = new_qty
        if exec_id:
            self.seen_exec_ids.append(exec_id)
        row = dict(
            time=time, strategy=self.name, source=source, symbol=symbol, quantity=quantity,
            price=price, ref_price=ref_price, open_price=open_price, commission=commission,
            modeled_commission=modeled_commission, exec_id=exec_id,
        )  # fmt: skip
        self._append("fills.csv", pd.DataFrame([row], columns=FILL_COLUMNS))

    def record_equity(self, date: str, prices: dict[str, float]) -> float:
        """Upsert today's equity row (a second run on the same date replaces the first)."""
        equity = self.equity(prices)
        path = self.directory(self.name, self.root) / "equity.csv"
        row = pd.DataFrame([{"date": date, "equity": equity, "cash": self.cash}])
        if path.exists():
            old = pd.read_csv(path, dtype={"date": str})
            row = pd.concat([old[old["date"] != date], row], ignore_index=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        row.to_csv(path, index=False)
        return equity

    def fills(self) -> pd.DataFrame:
        path = self.directory(self.name, self.root) / "fills.csv"
        return pd.read_csv(path) if path.exists() else pd.DataFrame(columns=FILL_COLUMNS)

    def _append(self, filename: str, df: pd.DataFrame) -> None:
        path = self.directory(self.name, self.root) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, mode="a", header=not path.exists(), index=False)


def fill_pending_at_open(ledger: Ledger, opens: pd.DataFrame, costs: CostModel) -> int:
    """Shadow fills: each pending order fills at the first open after its signal date,
    with the cost model's slippage and fees, exactly as backtest/sim.py does.

    Orders whose next open isn't in `opens` yet (e.g. a pre-market run) stay pending.
    Returns the number of fills booked.
    """
    still_pending, booked = [], 0
    for p in ledger.pending:
        after = opens.index[opens.index > pd.Timestamp(p.asof)]
        if len(after) == 0 or p.symbol not in opens or pd.isna(opens.at[after[0], p.symbol]):
            still_pending.append(p)
            continue
        day, open_price = after[0], float(opens.at[after[0], p.symbol])
        price = costs.fill_price(p.quantity, open_price)
        modeled = costs.total(p.quantity, price)
        ledger.apply_fill(
            time=day.strftime("%Y-%m-%d 09:30"), source="shadow", symbol=p.symbol,
            quantity=p.quantity, price=price, commission=modeled, modeled_commission=modeled,
            ref_price=p.ref_price, open_price=open_price,
        )  # fmt: skip
        booked += 1
    ledger.pending = still_pending
    return booked
