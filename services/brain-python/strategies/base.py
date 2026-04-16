"""
BaseStrategy — Protocol for all AlphaWolf strategies.

Strategies are pure Python logic: receive TickSnapshot, return list[SignalIntent].
No Protobuf, no ZMQ, no I/O — the main loop handles all transport concerns.

To add a new strategy:
  1. Create strategies/your_strategy.py
  2. Implement this Protocol (on_tick + reset_daily + name + symbols)
  3. Register it in strategies/__init__.py REGISTRY
  4. Add its config block to config/strategies.yaml
"""
from typing import Protocol, runtime_checkable

from .types import TickSnapshot, SignalIntent


@runtime_checkable
class BaseStrategy(Protocol):
    """
    Minimal interface every strategy must implement.

    Contracts:
      - on_tick() must be pure (no side effects, no I/O)
      - Returns [] for no signal, [SignalIntent, ...] when signal fires
      - State is owned by the strategy object — main loop is stateless
      - reset_daily() is called once at the start of each trading session
    """

    name:    str        # unique ID — used as TradeIntent.strategy_id
    symbols: list[str]  # symbols this strategy consumes

    def on_tick(self, tick: TickSnapshot) -> list[SignalIntent]:
        """
        Process one market tick.

        Args:
            tick: Normalized market snapshot (broker-agnostic).

        Returns:
            List of trading signals. Empty list = no action.
        """
        ...

    def reset_daily(self) -> None:
        """Reset all intraday state. Called once per trading day."""
        ...
