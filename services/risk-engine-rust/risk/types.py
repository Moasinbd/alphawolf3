"""
Risk domain value objects — pure Python, immutable, no external dependencies.

TradeRequest : what the strategy wants to do
RiskDecision : what the risk engine decided (and why)
RiskLimits   : configuration snapshot loaded from risk_limits.yaml
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TradeRequest:
    """Transport-agnostic representation of a trade signal from brain-python."""
    strategy_id: str
    symbol:      str
    side:        str    # "BUY" | "SELL"
    quantity:    float
    confidence:  float
    reason:      str
    ts_ns:       int


@dataclass(frozen=True)
class RiskDecision:
    """
    Result of risk evaluation — returned by RiskEngine.evaluate().

    approved_qty    : 0.0 if rejected; may differ from requested qty in future
                      (partial fills — Phase 5+).
    rejection_reason: empty string when approved.
    latency_ns      : wall-clock time spent inside _validate().
    """
    approved:         bool
    approved_qty:     float
    rejection_reason: str
    latency_ns:       int


@dataclass
class RiskLimits:
    """
    Hard limits loaded once at startup from risk_limits.yaml.

    Immutable after construction — never read the YAML file inside the engine.
    """
    # Portfolio-level
    max_daily_loss_eur:     float
    max_drawdown_pct:       float
    max_gross_exposure_pct: float

    # Per-position
    max_size_pct:       float
    max_qty_per_order:  int
    min_confidence:     float

    # Per-order
    min_order_value_eur: float
    max_order_value_eur: float

    # Symbol filters (empty list = no restriction)
    whitelist: list[str] = field(default_factory=list)
    blacklist: list[str] = field(default_factory=list)
