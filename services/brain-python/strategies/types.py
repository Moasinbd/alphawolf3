"""
Strategy domain types — pure Python, zero external dependencies.

Strategies receive TickSnapshot and return list[SignalIntent].
The main loop (adapter) handles the conversion to/from Protobuf.

This decoupling means:
  - Strategies are testable with plain Python dicts or dataclasses
  - No ZMQ, no proto, no network in strategy unit tests
  - New strategies need zero knowledge of transport layer
"""
from dataclasses import dataclass
from enum import Enum, auto


class OrderSide(Enum):
    BUY  = auto()
    SELL = auto()


@dataclass(frozen=True)
class TickSnapshot:
    """
    Normalized market tick — broker-agnostic.
    Populated by main.py from pb.MarketData or any other source.
    """
    symbol: str
    price:  float
    bid:    float
    ask:    float
    volume: float
    ts_ns:  int   # nanoseconds UTC


@dataclass(frozen=True)
class SignalIntent:
    """
    Trading signal produced by a strategy.
    main.py converts this to pb.TradeIntent for ZMQ publishing.
    """
    strategy_id: str
    symbol:      str
    side:        OrderSide
    quantity:    float
    confidence:  float   # 0.0 – 1.0
    reason:      str
    ts_ns:       int
