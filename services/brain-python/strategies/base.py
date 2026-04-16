"""
BaseStrategy — Protocol for all AlphaWolf strategies.

Every strategy receives MarketData ticks and returns a list of TradeIntents.
The brain-python main loop handles ZMQ I/O; strategies are pure logic.
"""
from typing import Protocol, runtime_checkable
import sys
sys.path.insert(0, ".")
from proto import messages_pb2 as pb


@runtime_checkable
class BaseStrategy(Protocol):
    """
    Minimal interface every strategy must implement.

    Contract:
      - on_tick() is called for every incoming MarketData message.
      - Returns [] if no signal, or a list of TradeIntents to publish.
      - Must be stateless across strategy instances (state lives inside the object).
      - Must NOT call ZMQ or any I/O directly — return intents, let main loop publish.
    """

    name: str       # unique strategy identifier (used in TradeIntent.strategy_id)
    symbols: list   # symbols this strategy is interested in

    def on_tick(self, tick: "pb.MarketData") -> "list[pb.TradeIntent]":
        """
        Process one market tick.

        Args:
            tick: Deserialized MarketData protobuf message.

        Returns:
            List of TradeIntent messages to publish (empty = no signal).
        """
        ...

    def reset_daily(self) -> None:
        """Reset intraday state. Called at start of each trading day."""
        ...
