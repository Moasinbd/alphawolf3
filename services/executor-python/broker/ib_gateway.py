"""
IBGatewayExecutor — real order execution via IB Gateway (ib_insync).

Phase 7+ only. Requires IB Gateway container running.
"""
import asyncio
import logging

from .protocol import ExecutionBroker, ExecutionResult, AccountSnapshot

logger = logging.getLogger(__name__)

try:
    from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder
    _IB_AVAILABLE = True
except ImportError:
    _IB_AVAILABLE = False


class IBGatewayExecutor(ExecutionBroker):
    """
    Executes orders via IB Gateway using ib_insync.

    Connects to the ib-gateway Docker container.
    Port 4002 = paper trading
    Port 4001 = live trading  ← USE WITH EXTREME CAUTION
    """

    def __init__(self, host: str, port: int, client_id: int = 2):
        if not _IB_AVAILABLE:
            raise ImportError("pip install ib-insync to use IBGatewayExecutor")
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = IB()

    async def connect(self) -> None:
        await self._ib.connectAsync(self._host, self._port, self._client_id)
        mode = "PAPER" if self._port == 4002 else "⚠️  LIVE"
        logger.info(f"IBGatewayExecutor [{mode}] connected → {self._host}:{self._port}")

    async def disconnect(self) -> None:
        self._ib.disconnect()

    def is_connected(self) -> bool:
        return self._ib.isConnected()

    def _build_order(self, action: str, quantity: float, order_type: str,
                     limit_price: float, stop_price: float):
        if order_type == "MKT":
            return MarketOrder(action, quantity)
        if order_type == "LMT":
            return LimitOrder(action, quantity, limit_price)
        if order_type == "STP":
            return StopOrder(action, quantity, stop_price)
        raise ValueError(f"Unsupported order type: {order_type}")

    async def place_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        order_type: str,
        limit_price: float = 0.0,
        stop_price: float  = 0.0,
    ) -> ExecutionResult:
        contract = Stock(symbol, "SMART", "USD")
        ib_order = self._build_order(action, quantity, order_type, limit_price, stop_price)

        trade = self._ib.placeOrder(contract, ib_order)

        # Wait for fill (timeout 30s)
        for _ in range(60):
            await asyncio.sleep(0.5)
            if trade.orderStatus.status in ("Filled", "Cancelled", "Inactive"):
                break

        status = trade.orderStatus.status.lower()
        return ExecutionResult(
            order_id=str(trade.order.orderId),
            status="filled" if status == "filled" else status,
            filled_qty=trade.orderStatus.filled,
            avg_price=trade.orderStatus.avgFillPrice,
            commission=trade.orderStatus.commission or 0.0,
        )

    async def cancel_order(self, order_id: str) -> bool:
        for trade in self._ib.trades():
            if str(trade.order.orderId) == order_id:
                self._ib.cancelOrder(trade.order)
                return True
        return False

    async def get_account(self) -> AccountSnapshot:
        vals = {v.tag: v.value for v in self._ib.accountValues() if v.currency == "USD"}
        return AccountSnapshot(
            account_id=self._ib.accountValues()[0].account,
            net_liquidation=float(vals.get("NetLiquidation", 0)),
            available_funds=float(vals.get("AvailableFunds", 0)),
            unrealized_pnl=float(vals.get("UnrealizedPnL", 0)),
            realized_pnl=float(vals.get("RealizedPnL", 0)),
            gross_position=float(vals.get("GrossPositionValue", 0)),
        )
