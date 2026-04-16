"""
IBGatewayBroker — real market data via IB Gateway (ib_insync).

Connects to IB Gateway running in Docker.
Paper mode:  port 4002
Live mode:   port 4001

Phase 7+ only. Requires IB Gateway container running and
IBKR credentials configured in config/ib.env.
"""
import asyncio
import logging
import time
from typing import AsyncIterator

from .protocol import MarketDataBroker, TickData

logger = logging.getLogger(__name__)

try:
    from ib_insync import IB, Stock, Forex, Contract
    _IB_AVAILABLE = True
except ImportError:
    _IB_AVAILABLE = False
    logger.warning("ib_insync not installed — IBGatewayBroker unavailable")


class IBGatewayBroker(MarketDataBroker):
    """
    Market data broker backed by IB Gateway via ib_insync.

    Usage:
        broker = IBGatewayBroker(host="ib-gateway", port=4002, client_id=1)
        await broker.connect()
        async for tick in broker.stream_ticks(["AAPL", "TSLA"]):
            publish(tick)
    """

    def __init__(self, host: str, port: int, client_id: int = 1):
        if not _IB_AVAILABLE:
            raise ImportError("pip install ib-insync to use IBGatewayBroker")
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = IB()
        self._ticks: dict[str, TickData] = {}

    async def connect(self) -> None:
        await self._ib.connectAsync(self._host, self._port, self._client_id)
        logger.info(f"IBGatewayBroker connected → {self._host}:{self._port}")

    async def disconnect(self) -> None:
        self._ib.disconnect()
        logger.info("IBGatewayBroker disconnected")

    def is_connected(self) -> bool:
        return self._ib.isConnected()

    def _resolve_contract(self, symbol: str) -> Contract:
        """Resolve symbol string to IB Contract."""
        if "USD" in symbol and symbol != "AUDUSD":
            # Crypto: BTCUSD, ETHUSD
            return Forex(symbol[:3] + symbol[3:])
        return Stock(symbol, "SMART", "USD")

    async def stream_ticks(self, symbols: list[str]) -> AsyncIterator[TickData]:
        contracts = {s: self._resolve_contract(s) for s in symbols}

        # Subscribe to market data
        tickers = {}
        for symbol, contract in contracts.items():
            ticker = self._ib.reqMktData(contract, "", False, False)
            tickers[symbol] = ticker

        try:
            while self.is_connected():
                for symbol, ticker in tickers.items():
                    price = ticker.last or ticker.close or 0.0
                    if price <= 0:
                        continue
                    yield TickData(
                        symbol=symbol,
                        price=price,
                        bid=ticker.bid or price,
                        ask=ticker.ask or price,
                        volume=ticker.volume or 0,
                        ts_ns=time.time_ns(),
                    )
                await asyncio.sleep(0.5)
        finally:
            for contract in contracts.values():
                self._ib.cancelMktData(contract)
            logger.info("Market data subscriptions cancelled")

    async def get_snapshot(self, symbol: str) -> TickData:
        contract = self._resolve_contract(symbol)
        ticker = self._ib.reqMktData(contract, "", True, False)
        await asyncio.sleep(1)
        price = ticker.last or ticker.close or 0.0
        self._ib.cancelMktData(contract)
        return TickData(
            symbol=symbol,
            price=price,
            bid=ticker.bid or price,
            ask=ticker.ask or price,
            volume=ticker.volume or 0,
            ts_ns=time.time_ns(),
        )
