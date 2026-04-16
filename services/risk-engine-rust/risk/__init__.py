"""
Risk domain — pure Python, zero external dependencies.

risk/types.py  — domain value objects (TradeRequest, RiskDecision, RiskLimits)
risk/engine.py — RiskEngine validation logic

The main.py adapter layer handles all proto/ZMQ concerns.
"""
from .engine import RiskEngine
from .types import RiskDecision, RiskLimits, TradeRequest

__all__ = ["RiskEngine", "RiskDecision", "RiskLimits", "TradeRequest"]
