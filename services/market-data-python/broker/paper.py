"""
PaperBroker — simulated market data.

Generates realistic tick data locally without any broker connection.
Used in Phase 1-6 development and CI/CD pipelines.
"""
import asyncio
import math
import random
import time
import logging
from typing import AsyncIterator

from .protocol import MarketDataBroker, TickData

logger = logging.getLogger(__name__)

# Base prices for simulation
# XETRA (EUR) — DAX 40 blue chips
# US markets — legacy / alternative universe
_BASE_PRICES: dict[str, float] = {
    # ── XETRA / DAX 40 ────────────────────────────────
    "SAP":    185.0,    # SAP SE
    "SIE":    180.0,    # Siemens AG
    "ALV":    295.0,    # Allianz SE
    "DTE":     22.5,    # Deutsche Telekom AG
    "BAS":     46.0,    # BASF SE
    "VOW3":   115.0,    # Volkswagen AG (preference shares)
    "DBK":     15.5,    # Deutsche Bank AG
    "MBG":     66.0,    # Mercedes-Benz Group AG
    "BMW":     85.0,    # BMW AG
    "ADS":    215.0,    # Adidas AG
    "EOAN":    12.5,    # E.ON SE
    "RWE":     30.0,    # RWE AG
    "BAYN":    29.0,    # Bayer AG
    "MRK":    165.0,    # Merck KGaA
    "HEI":    185.0,    # Heidelberg Materials AG
    # ── XETRA ETFs (EURO STOXX / DAX trackers) ───────
    "EXW1":   160.0,    # iShares Core DAX UCITS ETF
    "EXSA":   540.0,    # iShares Core EURO STOXX 50 UCITS ETF
    "CSSX5E": 542.0,    # Amundi EURO STOXX 50 II ETF
    "EXV1":    13.0,    # iShares STOXX Europe 600 Banks
    # ── US markets (legacy) ───────────────────────────
    "AAPL":   185.0,
    "TSLA":   250.0,
    "NVDA":   850.0,
    "SPY":    520.0,
    "QQQ":    450.0,
    "BTCUSD": 67000.0,
    "ETHUSD":  3500.0,
}

_DEFAULT_PRICE = 100.0


class PaperBroker(MarketDataBroker):
    """
    Simulated market data broker.

    Generates Brownian-motion price ticks for any symbol.
    Suitable for full end-to-end pipeline testing without IB.
    """

    def __init__(self, tick_interval_s: float = 1.0, volatility: float = 0.001):
        self._connected = False
        self._tick_interval = tick_interval_s
        self._volatility = volatility

    async def connect(self) -> None:
        self._connected = True
        logger.info("PaperBroker connected (simulated market data)")

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("PaperBroker disconnected")

    def is_connected(self) -> bool:
        return self._connected

    async def stream_ticks(self, symbols: list[str]) -> AsyncIterator[TickData]:
        prices = {s: _BASE_PRICES.get(s, _DEFAULT_PRICE) for s in symbols}

        while self._connected:
            for symbol in symbols:
                # Geometric Brownian Motion step
                shock = random.gauss(0, self._volatility)
                prices[symbol] *= math.exp(shock)
                price = round(prices[symbol], 4)
                spread = round(price * 0.0002, 4)  # 2bps spread

                yield TickData(
                    symbol=symbol,
                    price=price,
                    bid=round(price - spread / 2, 4),
                    ask=round(price + spread / 2, 4),
                    volume=random.randint(100, 5000),
                    ts_ns=time.time_ns(),
                )

            await asyncio.sleep(self._tick_interval)

    async def get_snapshot(self, symbol: str) -> TickData:
        price = _BASE_PRICES.get(symbol, _DEFAULT_PRICE)
        spread = price * 0.0002
        return TickData(
            symbol=symbol,
            price=price,
            bid=round(price - spread / 2, 4),
            ask=round(price + spread / 2, 4),
            volume=1000,
            ts_ns=time.time_ns(),
        )
