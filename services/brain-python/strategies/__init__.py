"""
Strategy Registry — add new strategies here, nothing else needs to change.

To add a new strategy:
  1. Create services/brain-python/strategies/your_strategy.py
  2. Implement the BaseStrategy protocol (on_tick + reset_daily + name + symbols)
  3. Import it below and add to REGISTRY
  4. Add its config block to config/strategies.yaml
  5. Set STRATEGY=your_strategy_name in docker-compose.yml or .env

The main.py uses REGISTRY to instantiate strategies — zero changes needed there.
"""
from .orb_xetra import ORBXetraStrategy

# ── Strategy Registry ────────────────────────────────────────────────────
# key:   STRATEGY env var value (used in docker-compose and strategies.yaml)
# value: class to instantiate with config dict
REGISTRY: dict[str, type] = {
    "orb_xetra": ORBXetraStrategy,
    # "mean_reversion": MeanReversionStrategy,   ← future strategies here
    # "vwap_breakout":  VWAPBreakoutStrategy,
    # "earnings_gap":   EarningsGapStrategy,
}

__all__ = ["ORBXetraStrategy", "REGISTRY"]
