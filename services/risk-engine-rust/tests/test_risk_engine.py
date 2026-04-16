"""
Unit tests — RiskEngine (pure Python, no ZMQ/proto dependencies)

Run from services/risk-engine-rust/:
    python tests/test_risk_engine.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk.engine import RiskEngine
from risk.types import RiskLimits, TradeRequest

# ── Helpers ────────────────────────────────────────────────────────────────────

def make_limits(**overrides) -> RiskLimits:
    # max_daily_loss_eur=500 is test-friendly — only tests that specifically
    # test the daily limit will override this to a lower value.
    base = RiskLimits(
        max_daily_loss_eur=500.0,
        max_drawdown_pct=15.0,
        max_gross_exposure_pct=60.0,
        max_size_pct=15.0,
        max_qty_per_order=500,
        min_confidence=0.65,
        min_order_value_eur=10.0,
        max_order_value_eur=50.0,
        whitelist=["SAP", "SIE", "ALV"],
        blacklist=[],
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def make_request(**overrides) -> TradeRequest:
    base = dict(
        strategy_id="orb_xetra",
        symbol="SAP",
        side="BUY",
        quantity=1.0,
        confidence=0.80,
        reason="ORB UP",
        ts_ns=1_000_000_000,
    )
    base.update(overrides)
    return TradeRequest(**base)


def make_engine_with_price(
    price: float = 20.0,
    symbol: str = "SAP",
    **limit_overrides,
) -> RiskEngine:
    """Engine with a pre-loaded price so order-value checks can run."""
    engine = RiskEngine(make_limits(**limit_overrides))
    engine.update_price(symbol, price)
    return engine


PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}")
    results.append((name, condition))


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_valid_trade_approved():
    print("\nTest 1: Valid trade is approved")
    engine = make_engine_with_price(price=20.0)   # 1 qty * 20 = EUR20 (within EUR10-50)
    req = make_request(quantity=1.0, confidence=0.80)
    d = engine.evaluate(req)

    check("approved=True",       d.approved)
    check("approved_qty=1.0",    d.approved_qty == 1.0)
    check("no rejection_reason", d.rejection_reason == "")
    check("latency_ns >= 0",     d.latency_ns >= 0)


def test_confidence_below_threshold():
    print("\nTest 2: Confidence below min_confidence -> REJECT")
    engine = make_engine_with_price()
    req = make_request(confidence=0.60)   # below 0.65
    d = engine.evaluate(req)

    check("approved=False",           not d.approved)
    check("approved_qty=0.0",         d.approved_qty == 0.0)
    check("reason mentions conf",     "confidence" in d.rejection_reason)


def test_blacklisted_symbol():
    print("\nTest 3: Blacklisted symbol -> REJECT")
    engine = make_engine_with_price(blacklist=["SAP"])
    req = make_request(symbol="SAP")
    d = engine.evaluate(req)

    check("approved=False",           not d.approved)
    check("reason mentions blacklist","blacklist" in d.rejection_reason.lower()
                                       or "blacklisted" in d.rejection_reason.lower())


def test_symbol_not_in_whitelist():
    print("\nTest 4: Symbol not in whitelist -> REJECT")
    engine = make_engine_with_price(whitelist=["SAP", "SIE"])
    engine.update_price("BMW", 80.0)
    req = make_request(symbol="BMW")
    d = engine.evaluate(req)

    check("approved=False",          not d.approved)
    check("reason mentions whitelist","whitelist" in d.rejection_reason.lower())


def test_empty_whitelist_allows_all():
    print("\nTest 5: Empty whitelist allows any symbol")
    engine = make_engine_with_price(whitelist=[], price=20.0, symbol="NVDA")
    req = make_request(symbol="NVDA")
    d = engine.evaluate(req)

    check("approved=True", d.approved)


def test_no_price_data():
    print("\nTest 6: No price data -> REJECT")
    engine = RiskEngine(make_limits())
    # No update_price() call — price cache is empty
    req = make_request(symbol="SAP")
    d = engine.evaluate(req)

    check("approved=False",      not d.approved)
    check("reason mentions price","price" in d.rejection_reason.lower())


def test_order_value_too_small():
    print("\nTest 7: Order value below min -> REJECT")
    # price=5.0, qty=1 → EUR5 < min_order_value_eur=10
    engine = make_engine_with_price(price=5.0)
    req = make_request(quantity=1.0)
    d = engine.evaluate(req)

    check("approved=False",      not d.approved)
    check("reason mentions min", "min" in d.rejection_reason.lower())


def test_order_value_too_large():
    print("\nTest 8: Order value above max -> REJECT")
    # price=30.0, qty=3 → EUR90 > max_order_value_eur=50
    engine = make_engine_with_price(price=30.0)
    req = make_request(quantity=3.0)
    d = engine.evaluate(req)

    check("approved=False",      not d.approved)
    check("reason mentions max", "max" in d.rejection_reason.lower())


def test_daily_commitment_limit():
    print("\nTest 9: Daily commitment limit -> REJECT after threshold")
    # max_daily_loss_eur=15, price=12, qty=1 → EUR12/order
    engine = make_engine_with_price(price=12.0, max_daily_loss_eur=15.0)

    req = make_request(quantity=1.0)
    d1 = engine.evaluate(req)   # EUR12 → committed=12
    d2 = engine.evaluate(req)   # EUR12 → projected=24 > 15 → REJECT

    check("first order approved",    d1.approved)
    check("second order rejected",   not d2.approved)
    check("reason mentions daily",   "daily" in d2.rejection_reason.lower())


def test_reset_daily_clears_committed():
    print("\nTest 10: reset_daily clears committed amount")
    engine = make_engine_with_price(price=12.0, max_daily_loss_eur=15.0)

    req = make_request(quantity=1.0)
    engine.evaluate(req)          # EUR12 committed
    engine.reset_daily()          # reset
    d = engine.evaluate(req)      # should be approved again

    check("approved after reset", d.approved)


def test_quantity_zero_rejected():
    print("\nTest 11: Zero quantity -> REJECT")
    engine = make_engine_with_price()
    req = make_request(quantity=0.0)
    d = engine.evaluate(req)

    check("approved=False",         not d.approved)
    check("reason mentions quantity","quantity" in d.rejection_reason.lower())


def test_quantity_over_hard_cap():
    print("\nTest 12: Quantity above max_qty_per_order -> REJECT")
    engine = make_engine_with_price(max_qty_per_order=10)
    req = make_request(quantity=11.0)
    d = engine.evaluate(req)

    check("approved=False",          not d.approved)
    check("reason mentions quantity", "quantity" in d.rejection_reason.lower())


def test_price_update_overwrites():
    print("\nTest 13: Price update overwrites stale price")
    engine = RiskEngine(make_limits(whitelist=[]))
    engine.update_price("SAP", 5.0)    # EUR5 — too small
    engine.update_price("SAP", 20.0)   # EUR20 — valid

    req = make_request(symbol="SAP", quantity=1.0)
    d = engine.evaluate(req)

    check("approved with updated price", d.approved)


def test_blacklist_overrides_whitelist():
    print("\nTest 14: Blacklist checked before whitelist")
    # SAP is in both whitelist and blacklist — blacklist wins
    engine = make_engine_with_price(
        whitelist=["SAP"], blacklist=["SAP"]
    )
    req = make_request(symbol="SAP")
    d = engine.evaluate(req)

    check("approved=False",                not d.approved)
    check("reason mentions blacklist",
          "blacklist" in d.rejection_reason.lower()
          or "blacklisted" in d.rejection_reason.lower())


# ── Runner ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("RiskEngine — Unit Test Suite")
    print("=" * 60)

    tests = [
        test_valid_trade_approved,
        test_confidence_below_threshold,
        test_blacklisted_symbol,
        test_symbol_not_in_whitelist,
        test_empty_whitelist_allows_all,
        test_no_price_data,
        test_order_value_too_small,
        test_order_value_too_large,
        test_daily_commitment_limit,
        test_reset_daily_clears_committed,
        test_quantity_zero_rejected,
        test_quantity_over_hard_cap,
        test_price_update_overwrites,
        test_blacklist_overrides_whitelist,
    ]

    for t in tests:
        try:
            t()
        except Exception as exc:
            print(f"  {FAIL} EXCEPTION in {t.__name__}: {exc}")
            results.append((t.__name__, False))

    passed = sum(1 for _, ok in results if ok)
    total  = len(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed")

    if passed == total:
        print("ALL TESTS PASSED")
        return 0

    print("FAILURES:")
    for name, ok in results:
        if not ok:
            print(f"  - {name}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
