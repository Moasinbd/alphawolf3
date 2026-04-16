"""
BrokerClient Protocol — generic broker interface.

Every broker implementation (IB Gateway, Paper, future Alpaca)
must implement this protocol. Services use this type — never
the concrete implementation directly.
"""
from typing import AsyncIterator, Protocol, runtime_checkable
from dataclasses import dataclass


@dataclass
class TickData:
    """Normalized tick from any broker."""
    symbol: str
    price: float
    bid: float
    ask: float
    volume: float
    ts_ns: int


@dataclass
class OrderResult:
    """Result of a placed order."""
    order_id: str
    status: str        # "submitted" | "filled" | "rejected"
    filled_qty: float
    avg_price: float
    commission: float
    error: str = ""


@runtime_checkable
class MarketDataBroker(Protocol):
    """
    Protocol for market data sources.

    Implemented by:
    - IBGatewayBroker  (real IB data via ib_insync)
    - PaperBroker      (simulated data, no IB needed)
    """

    async def connect(self) -> None:
        """Establish connection to data source."""
        ...

    async def disconnect(self) -> None:
        """Close connection cleanly."""
        ...

    def is_connected(self) -> bool:
        """True if connection is active and healthy."""
        ...

    async def stream_ticks(self, symbols: list[str]) -> AsyncIterator[TickData]:
        """
        Yields TickData for the given symbols continuously.

        Never raises — on connection loss yields nothing and reconnects.
        """
        ...

    async def get_snapshot(self, symbol: str) -> TickData:
        """Single price snapshot for a symbol."""
        ...
