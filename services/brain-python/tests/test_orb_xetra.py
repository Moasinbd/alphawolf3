"""
Unit tests — ORBXetraStrategy (pure Python, no ZMQ/proto dependencies)

Run from services/brain-python/:
    python -m pytest tests/test_orb_xetra.py -v
Or directly:
    python tests/test_orb_xetra.py
"""
import os
import sys
import time as time_module

# Make strategies importable from services/brain-python/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.orb_xetra import ORBXetraStrategy
from strategies.types import OrderSide, TickSnapshot

# ── Helpers ────────────────────────────────────────────────────────────────────

def make_config(**overrides) -> dict:
    base = {
        "symbols":           ["SAP", "SIE"],
        "opening_range_min": 15,
        "volume_multiplier": 1.5,
        "risk_reward":       2.0,
        "min_confidence":    0.65,
        "position_size_pct": 5.0,
    }
    base.update(overrides)
    return base


def make_tick(symbol: str, price: float, volume: float = 1000.0, ts_ns: int = 0) -> TickSnapshot:
    return TickSnapshot(
        symbol=symbol,
        price=price,
        bid=price - 0.01,
        ask=price + 0.01,
        volume=volume,
        ts_ns=ts_ns or time_module.time_ns(),
    )


def build_paper_strategy(**config_overrides) -> ORBXetraStrategy:
    """Strategy in paper mode with a very short window for fast tests."""
    os.environ["PAPER_FORCE_SIGNALS"] = "true"
    os.environ["PAPER_RANGE_SECONDS"] = "0.3"   # 300ms accumulation window
    cfg = make_config(**config_overrides)
    strat = ORBXetraStrategy(cfg)
    del os.environ["PAPER_FORCE_SIGNALS"]
    del os.environ["PAPER_RANGE_SECONDS"]
    # Patch the instance directly so env vars don't matter after construction
    strat._paper = True
    strat._paper_window_s = 0.3
    return strat


PASS = "[PASS]"
FAIL = "[FAIL]"

results: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    tag = PASS if condition else FAIL
    print(f"  {tag} {name}")
    results.append((name, condition))


# ── Test 1: BUY breakout fires correctly ──────────────────────────────────────

def test_buy_breakout():
    print("\nTest 1: BUY breakout")
    strat = build_paper_strategy()

    # Accumulate range: prices between 100–102
    for price in [100.0, 101.0, 102.0]:
        strat.on_tick(make_tick("SAP", price, volume=500.0))

    time_module.sleep(0.35)  # let window expire

    # Breakout: price above 102, high volume
    sigs = strat.on_tick(make_tick("SAP", price=103.0, volume=2000.0))

    check("returns exactly 1 signal", len(sigs) == 1)
    if sigs:
        check("signal is BUY",        sigs[0].side == OrderSide.BUY)
        check("symbol is SAP",        sigs[0].symbol == "SAP")
        check("confidence >= 0.65",    sigs[0].confidence >= 0.65)
        conf_str = f"{sigs[0].confidence:.3f}"
        print(f"    confidence={conf_str}")


# ── Test 2: SELL breakout fires correctly ─────────────────────────────────────

def test_sell_breakout():
    print("\nTest 2: SELL breakout")
    strat = build_paper_strategy()

    for price in [100.0, 101.0, 102.0]:
        strat.on_tick(make_tick("SAP", price, volume=500.0))

    time_module.sleep(0.35)

    sigs = strat.on_tick(make_tick("SAP", price=98.0, volume=2000.0))

    check("returns exactly 1 signal", len(sigs) == 1)
    if sigs:
        check("signal is SELL",       sigs[0].side == OrderSide.SELL)
        check("symbol is SAP",        sigs[0].symbol == "SAP")


# ── Test 3: No signal below volume multiplier ─────────────────────────────────

def test_no_signal_low_volume():
    print("\nTest 3: No signal — volume too low")
    strat = build_paper_strategy()

    for price in [100.0, 101.0, 102.0]:
        strat.on_tick(make_tick("SAP", price, volume=500.0))

    time_module.sleep(0.35)

    # Volume below 1.5x threshold (avg=500 → need ≥750, sending 600)
    sigs = strat.on_tick(make_tick("SAP", price=103.0, volume=600.0))

    check("no signal on low volume", len(sigs) == 0)


# ── Test 4: No re-entry after signal fires ────────────────────────────────────

def test_no_reentry():
    print("\nTest 4: No re-entry after BUY fires")
    strat = build_paper_strategy()

    for price in [100.0, 101.0, 102.0]:
        strat.on_tick(make_tick("SAP", price, volume=500.0))

    time_module.sleep(0.35)

    sig1 = strat.on_tick(make_tick("SAP", price=103.0, volume=2000.0))
    sig2 = strat.on_tick(make_tick("SAP", price=104.0, volume=2000.0))

    check("first tick fires signal",   len(sig1) == 1)
    check("second tick fires nothing", len(sig2) == 0)


# ── Test 5: Unknown symbol is ignored ─────────────────────────────────────────

def test_unknown_symbol():
    print("\nTest 5: Unknown symbol is ignored")
    strat = build_paper_strategy()

    sigs = strat.on_tick(make_tick("UNKNOWN", price=100.0, volume=9999.0))
    check("unknown symbol returns []", len(sigs) == 0)


# ── Test 6: reset_daily clears state ─────────────────────────────────────────

def test_reset_daily():
    print("\nTest 6: reset_daily clears fired flags")
    strat = build_paper_strategy()

    for price in [100.0, 101.0, 102.0]:
        strat.on_tick(make_tick("SAP", price, volume=500.0))

    time_module.sleep(0.35)
    strat.on_tick(make_tick("SAP", price=103.0, volume=2000.0))  # fires BUY

    strat.reset_daily()

    for price in [100.0, 101.0, 102.0]:
        strat.on_tick(make_tick("SAP", price, volume=500.0))

    time_module.sleep(0.35)
    sigs = strat.on_tick(make_tick("SAP", price=103.0, volume=2000.0))

    check("BUY fires again after reset", len(sigs) == 1)


# ── Test 7: Late-start symbol window restart ──────────────────────────────────

def test_late_start_symbol():
    """
    Symbols that receive their first tick AFTER the accumulation window has
    expired must restart the window from that first tick, not get stuck.
    """
    print("\nTest 7: Late-start symbol window restart")
    strat = build_paper_strategy(symbols=["SIE"])

    # Wait for the paper window to expire with NO ticks for SIE
    time_module.sleep(0.35)

    # First tick arrives AFTER window expiry — should restart window
    strat.on_tick(make_tick("SIE", price=100.0, volume=500.0))
    strat.on_tick(make_tick("SIE", price=101.0, volume=500.0))

    time_module.sleep(0.35)  # new window expires

    sigs = strat.on_tick(make_tick("SIE", price=102.0, volume=2000.0))

    check("late-start symbol eventually fires BUY", len(sigs) == 1)
    if sigs:
        check("signal is BUY", sigs[0].side == OrderSide.BUY)
        conf_str = f"{sigs[0].confidence:.3f}"
        print(f"    confidence={conf_str}")


# ── Runner ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("ORBXetraStrategy — Unit Test Suite")
    print("=" * 60)

    tests = [
        test_buy_breakout,
        test_sell_breakout,
        test_no_signal_low_volume,
        test_no_reentry,
        test_unknown_symbol,
        test_reset_daily,
        test_late_start_symbol,
    ]

    for t in tests:
        try:
            t()
        except Exception as exc:
            print(f"  {FAIL} EXCEPTION: {exc}")
            results.append((t.__name__, False))

    passed = sum(1 for _, ok in results if ok)
    total  = len(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed")

    if passed == total:
        print("ALL TESTS PASSED")
        return 0
    else:
        print("FAILURES:")
        for name, ok in results:
            if not ok:
                print(f"  - {name}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
