"""
RiskEngine — pure Python risk validation.

Zero I/O, zero external dependencies. All state is owned by this object.
The main.py adapter calls update_price() on market ticks and evaluate() on signals.

State:
  _price_cache          last known price per symbol (updated from market.data feed)
  _daily_committed_eur  total EUR committed in approved orders today
  _current_day          YYYY-MM-DD string — triggers auto-reset on new calendar day

Design notes:
  - Validation checks are ordered fail-fast (cheapest/most-likely first).
  - Daily committed tracks APPROVED order values (not P&L) — conservative but
    sufficient for Phase 3. Real P&L tracking from execution.fill comes in Phase 5.
  - Prices come from the market.data subscription in main.py. If no price is
    known for a symbol the order is REJECTED (safer than guessing).
"""
import logging
import time
from datetime import datetime, timezone

from .types import RiskDecision, RiskLimits, TradeRequest

logger = logging.getLogger("risk.engine")


class RiskEngine:
    """
    Stateful, pure-Python risk validation engine.

    Thread-safety: NOT thread-safe — designed for single-threaded asyncio use.
    """

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

        self._price_cache: dict[str, float] = {}
        self._daily_committed_eur: float = 0.0
        self._current_day: str = ""

        logger.info(
            "RiskEngine ready | conf>=%.2f | max_order=EUR%.0f | max_daily=EUR%.0f "
            "| whitelist=%d | blacklist=%d",
            limits.min_confidence,
            limits.max_order_value_eur,
            limits.max_daily_loss_eur,
            len(limits.whitelist),
            len(limits.blacklist),
        )

    # ── Public interface ───────────────────────────────────────────────────────

    def update_price(self, symbol: str, price: float) -> None:
        """
        Update the price cache from a market.data tick.
        Called by the adapter on every tick — no decision logic here.
        """
        if price > 0:
            self._price_cache[symbol] = price

    def evaluate(self, req: TradeRequest) -> RiskDecision:
        """
        Validate a trade request and return a RiskDecision.

        Side effects:
          - On approval: increments _daily_committed_eur.
          - On new calendar day: resets _daily_committed_eur.
        """
        self._check_day_reset()

        t_start = time.time_ns()
        approved, reason = self._validate(req)
        latency_ns = time.time_ns() - t_start

        if approved:
            price = self._price_cache.get(req.symbol, 0.0)
            order_value = req.quantity * price
            self._daily_committed_eur += order_value
            logger.info(
                "APPROVED  %s %s %.0fqty | value=EUR%.2f | daily_committed=EUR%.2f | lat=%dns",
                req.side, req.symbol, req.quantity,
                order_value, self._daily_committed_eur, latency_ns,
            )
        else:
            logger.info(
                "REJECTED  %s %s %.0fqty | %s",
                req.side, req.symbol, req.quantity, reason,
            )

        return RiskDecision(
            approved=approved,
            approved_qty=req.quantity if approved else 0.0,
            rejection_reason="" if approved else reason,
            latency_ns=latency_ns,
        )

    def reset_daily(self) -> None:
        """Reset daily state. Called automatically on day change; can be called externally."""
        prev = self._daily_committed_eur
        self._daily_committed_eur = 0.0
        logger.info("RiskEngine: daily reset (was EUR%.2f committed)", prev)

    # ── Validation ─────────────────────────────────────────────────────────────

    def _validate(self, req: TradeRequest) -> tuple[bool, str]:
        """
        Fail-fast validation — returns (approved, rejection_reason).
        Checks ordered: cheapest / most-likely-to-reject first.
        """

        # 1. Confidence threshold
        if req.confidence < self.limits.min_confidence:
            return False, (
                f"confidence={req.confidence:.3f} < min={self.limits.min_confidence:.3f}"
            )

        # 2. Blacklist (hard block — checked before whitelist)
        if req.symbol in self.limits.blacklist:
            return False, f"symbol '{req.symbol}' is blacklisted"

        # 3. Whitelist (empty list = all symbols allowed)
        if self.limits.whitelist and req.symbol not in self.limits.whitelist:
            return False, f"symbol '{req.symbol}' not in whitelist"

        # 4. Quantity sanity
        if req.quantity <= 0:
            return False, f"quantity={req.quantity} must be > 0"

        # 5. Quantity hard cap (protects against runaway signals)
        if req.quantity > self.limits.max_qty_per_order:
            return False, (
                f"quantity={req.quantity} > max={self.limits.max_qty_per_order}"
            )

        # 6. Price availability (reject rather than guess)
        price = self._price_cache.get(req.symbol)
        if not price or price <= 0:
            return False, f"no price data for '{req.symbol}' — order cannot be sized"

        # 7. Order value — minimum (commission ratio protection)
        order_value = req.quantity * price
        if order_value < self.limits.min_order_value_eur:
            return False, (
                f"order_value=EUR{order_value:.2f} < min=EUR{self.limits.min_order_value_eur:.2f}"
            )

        # 8. Order value — maximum (single-order capital cap)
        if order_value > self.limits.max_order_value_eur:
            return False, (
                f"order_value=EUR{order_value:.2f} > max=EUR{self.limits.max_order_value_eur:.2f}"
            )

        # 9. Daily commitment limit
        projected = self._daily_committed_eur + order_value
        if projected > self.limits.max_daily_loss_eur:
            return False, (
                f"daily_committed=EUR{self._daily_committed_eur:.2f} + "
                f"order=EUR{order_value:.2f} = EUR{projected:.2f} "
                f"> daily_max=EUR{self.limits.max_daily_loss_eur:.2f}"
            )

        return True, ""

    # ── Day management ─────────────────────────────────────────────────────────

    def _check_day_reset(self) -> None:
        day_key = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        if day_key != self._current_day:
            self._current_day = day_key
            self.reset_daily()
            logger.info("New trading day: %s", day_key)
