"""
ExecutionBroker Protocol — generic order execution interface.

Separates the execution concern from market data.
Every broker implementation must fulfill this contract.
"""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ExecutionResult:
    order_id: str
    status: str        # "submitted" | "filled" | "rejected" | "cancelled"
    filled_qty: float
    avg_price: float
    commission: float
    error: str = ""


@dataclass
class AccountSnapshot:
    account_id: str
    net_liquidation: float
    available_funds: float
    unrealized_pnl: float
    realized_pnl: float
    gross_position: float


@runtime_checkable
class ExecutionBroker(Protocol):
    """
    Protocol for order execution.

    Implemented by:
    - IBGatewayExecutor  (real orders via ib_insync)
    - PaperExecutor      (simulated fills, no IB needed)
    """

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...

    async def place_order(
        self,
        symbol: str,
        action: str,       # "BUY" | "SELL"
        quantity: float,
        order_type: str,   # "MKT" | "LMT" | "STP"
        limit_price: float = 0.0,
        stop_price: float  = 0.0,
    ) -> ExecutionResult: ...

    async def cancel_order(self, order_id: str) -> bool: ...

    async def get_account(self) -> AccountSnapshot: ...
