"""
PaperExecutor — simulated order execution.

Fills orders instantly at the last known price with realistic
commission simulation. No IB required.
Used in Phase 4-6.
"""
import logging
import time
import uuid

from .protocol import ExecutionBroker, ExecutionResult, AccountSnapshot

logger = logging.getLogger(__name__)

_COMMISSION_PER_SHARE = 0.005  # $0.005/share, min $1.00


class PaperExecutor(ExecutionBroker):
    """
    Simulates order execution without any broker connection.

    Maintains a virtual account to track fills and P&L.
    """

    def __init__(self, initial_capital: float = 100_000.0):
        self._connected = False
        self._cash = initial_capital
        self._positions: dict[str, float] = {}  # symbol → qty
        self._avg_prices: dict[str, float] = {}  # symbol → avg cost
        self._realized_pnl = 0.0
        self._fills: list[ExecutionResult] = []

    async def connect(self) -> None:
        self._connected = True
        logger.info(f"PaperExecutor connected | capital: ${self._cash:,.2f}")

    async def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    async def place_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        order_type: str,
        limit_price: float = 0.0,
        stop_price: float  = 0.0,
    ) -> ExecutionResult:
        # Use limit_price as fill price for LMT, otherwise use a mock
        fill_price = limit_price if limit_price > 0 else 100.0  # placeholder
        commission = max(1.0, quantity * _COMMISSION_PER_SHARE)
        order_id = str(uuid.uuid4())[:8]

        if action == "BUY":
            cost = fill_price * quantity + commission
            if cost > self._cash:
                logger.warning(f"PaperExecutor: insufficient funds for {symbol} BUY")
                return ExecutionResult(
                    order_id=order_id, status="rejected",
                    filled_qty=0, avg_price=0, commission=0,
                    error="Insufficient funds",
                )
            self._cash -= cost
            prev_qty = self._positions.get(symbol, 0.0)
            prev_avg = self._avg_prices.get(symbol, 0.0)
            new_qty = prev_qty + quantity
            self._positions[symbol] = new_qty
            self._avg_prices[symbol] = (prev_avg * prev_qty + fill_price * quantity) / new_qty

        elif action == "SELL":
            pos = self._positions.get(symbol, 0.0)
            qty = min(quantity, pos)
            if qty <= 0:
                return ExecutionResult(
                    order_id=order_id, status="rejected",
                    filled_qty=0, avg_price=0, commission=0,
                    error="No position to sell",
                )
            avg_cost = self._avg_prices.get(symbol, 0.0)
            self._realized_pnl += (fill_price - avg_cost) * qty - commission
            self._cash += fill_price * qty - commission
            self._positions[symbol] = pos - qty

        result = ExecutionResult(
            order_id=order_id,
            status="filled",
            filled_qty=quantity,
            avg_price=fill_price,
            commission=commission,
        )
        self._fills.append(result)
        logger.info(f"PaperExecutor FILL: {action} {quantity} {symbol} @ {fill_price:.4f} | commission: ${commission:.2f}")
        return result

    async def cancel_order(self, order_id: str) -> bool:
        return True  # Paper orders fill immediately — nothing to cancel

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="PAPER-001",
            net_liquidation=self._cash,
            available_funds=self._cash,
            unrealized_pnl=0.0,
            realized_pnl=self._realized_pnl,
            gross_position=sum(abs(q) for q in self._positions.values()),
        )
