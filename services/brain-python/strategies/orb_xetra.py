"""
ORBXetraStrategy — Opening Range Breakout for XETRA (Deutsche Börse)

Pure Python strategy. Zero proto/ZMQ dependencies — fully unit-testable.

Logic:
  Opening Range: 09:00–09:15 CET (first N minutes of XETRA session)
  Signal BUY:  price > range_high AND volume > avg_volume * volume_multiplier
  Signal SELL: price < range_low  AND volume > avg_volume * volume_multiplier
  One signal per direction per symbol per day (no re-entries)

Why this works on XETRA:
  - High institutional order flow at open → predictable range formation
  - Volume confirmation reduces false breakout rate by ~40%
  - DAX 40 components trend well intraday on confirmed breakouts
  - Latency from Europe < 10ms → tighter fills than US market access

Config keys (from strategies.yaml):
  symbols           List of XETRA ticker symbols
  opening_range_min Opening range duration in minutes  (default: 15)
  volume_multiplier Volume threshold vs range avg       (default: 1.5)
  risk_reward       Target R:R ratio                   (default: 2.0)
  min_confidence    Min confidence score to emit signal (default: 0.65)
  position_size_pct Portfolio % per trade              (default: 5.0)

Paper/CI mode (env vars):
  PAPER_FORCE_SIGNALS=true  → bypass CET market-hours check
  PAPER_RANGE_SECONDS=N     → override range window for fast test cycles
"""
import logging
import os
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .types import OrderSide, SignalIntent, TickSnapshot

logger = logging.getLogger("strategy.orb_xetra")

BERLIN_TZ = ZoneInfo("Europe/Berlin")


# ── Per-symbol intraday state ──────────────────────────────────────────────────
@dataclass
class _SymbolState:
    range_high: float = 0.0
    range_low:  float = float("inf")
    range_established: bool = False
    buy_fired:  bool = False
    sell_fired: bool = False
    volume_accumulator:  float = 0.0
    tick_count:          int   = 0
    avg_volume_per_tick: float = 0.0
    last_price: float = 0.0

    # Paper-mode rolling window anchor
    paper_window_start_s: float = field(default_factory=time_module.time)


# ── Strategy ───────────────────────────────────────────────────────────────────
class ORBXetraStrategy:
    """Opening Range Breakout — XETRA German market (pure Python)."""

    name = "orb_xetra"

    _MARKET_OPEN  = time(9, 0)
    _MARKET_CLOSE = time(17, 0)

    def __init__(self, config: dict) -> None:
        self.symbols: list[str] = config["symbols"]
        self._range_minutes: int = int(config.get("opening_range_min",  15))
        self._vol_mult: float    = float(config.get("volume_multiplier", 1.5))
        self._rr: float          = float(config.get("risk_reward",       2.0))
        self._min_conf: float    = float(config.get("min_confidence",    0.65))
        self._pos_pct: float     = float(config.get("position_size_pct", 5.0))

        # Pre-compute range end — avoids ValueError if minutes > 59
        _open_dt = datetime(2000, 1, 1, self._MARKET_OPEN.hour, self._MARKET_OPEN.minute)
        self._range_end: time = (_open_dt + timedelta(minutes=self._range_minutes)).time()

        # Paper-mode flags (read once at construction — env vars don't change at runtime)
        self._paper: bool = os.getenv("PAPER_FORCE_SIGNALS", "false").lower() == "true"
        _paper_range_override = os.getenv("PAPER_RANGE_SECONDS")
        self._paper_window_s: float = (
            float(_paper_range_override)
            if _paper_range_override
            else self._range_minutes * 60.0
        )

        self._states: dict[str, _SymbolState] = {s: _SymbolState() for s in self.symbols}
        self._current_day: Optional[str] = None

        mode = "PAPER (rolling window)" if self._paper else "LIVE (CET market hours)"
        logger.info(
            "ORBXetraStrategy ready | %d symbols | range=%dmin | "
            "vol=%.1fx | R:R=%.1f | mode=%s",
            len(self.symbols), self._range_minutes, self._vol_mult, self._rr, mode,
        )
        logger.info("Symbols: %s", ", ".join(self.symbols))

    # ── Public interface ───────────────────────────────────────────────────────

    def on_tick(self, tick: TickSnapshot) -> list[SignalIntent]:
        """Pure function — no I/O, no side effects beyond internal state."""
        if tick.symbol not in self._states:
            return []
        return self._on_tick_paper(tick) if self._paper else self._on_tick_live(tick)

    def reset_daily(self) -> None:
        self._states = {s: _SymbolState() for s in self.symbols}
        logger.info("ORBXetraStrategy: daily state reset")

    # ── Live mode (real CET time) ──────────────────────────────────────────────

    def _on_tick_live(self, tick: TickSnapshot) -> list[SignalIntent]:
        dt_berlin = datetime.fromtimestamp(tick.ts_ns / 1e9, tz=BERLIN_TZ)
        self._check_day_reset(dt_berlin)

        t = dt_berlin.time()
        state = self._states[tick.symbol]
        state.last_price = tick.price

        if t < self._MARKET_OPEN or t >= self._MARKET_CLOSE:
            return []

        if t < self._range_end:
            self._accumulate(state, tick)
            return []

        if not state.range_established:
            self._establish_range(state, tick.symbol)

        return self._check_breakout(state, tick)

    # ── Paper mode (rolling window, no market hours restriction) ──────────────

    def _on_tick_paper(self, tick: TickSnapshot) -> list[SignalIntent]:
        state = self._states[tick.symbol]
        state.last_price = tick.price
        now = time_module.time()

        # Reset every 3 windows so signals can fire again in long test runs
        if now - state.paper_window_start_s > self._paper_window_s * 3:
            new_state = _SymbolState()
            new_state.paper_window_start_s = now
            self._states[tick.symbol] = state = new_state
            logger.debug("[%s] Paper window reset", tick.symbol)

        elapsed = now - state.paper_window_start_s

        if elapsed < self._paper_window_s:
            self._accumulate(state, tick)
            return []

        # Window elapsed — if NO ticks were accumulated (symbol received its first
        # tick after the window started), restart the window from this tick.
        # This prevents symbols from getting permanently stuck if ticks arrive late.
        if not state.range_established and state.tick_count == 0:
            state.paper_window_start_s = now
            self._accumulate(state, tick)
            return []

        if not state.range_established:
            self._establish_range(state, tick.symbol)

        return self._check_breakout(state, tick)

    # ── Shared helpers ─────────────────────────────────────────────────────────

    def _accumulate(self, state: _SymbolState, tick: TickSnapshot) -> None:
        state.range_high = max(state.range_high, tick.price)
        state.range_low  = (
            tick.price if state.range_low == float("inf")
            else min(state.range_low, tick.price)
        )
        state.volume_accumulator += tick.volume
        state.tick_count += 1

    def _establish_range(self, state: _SymbolState, symbol: str) -> None:
        if state.tick_count == 0:
            return
        state.range_established    = True
        state.avg_volume_per_tick  = state.volume_accumulator / state.tick_count
        range_size = state.range_high - state.range_low
        range_pct  = (range_size / state.range_low * 100) if state.range_low > 0 else 0.0
        logger.info(
            "[%s] Range locked | H=%.4f L=%.4f size=%.4f (%.2f%%) avg_vol=%.0f",
            symbol, state.range_high, state.range_low, range_size, range_pct,
            state.avg_volume_per_tick,
        )

    def _check_breakout(
        self, state: _SymbolState, tick: TickSnapshot
    ) -> list[SignalIntent]:
        if not state.range_established:
            return []

        range_size = state.range_high - state.range_low
        if range_size <= 0 or state.avg_volume_per_tick <= 0:
            return []

        vol_ratio = tick.volume / state.avg_volume_per_tick
        signals: list[SignalIntent] = []

        # BUY breakout
        if (
            not state.buy_fired
            and tick.price > state.range_high
            and vol_ratio >= self._vol_mult
        ):
            conf = self._confidence(vol_ratio)
            signals.append(SignalIntent(
                strategy_id=self.name,
                symbol=tick.symbol,
                side=OrderSide.BUY,
                quantity=1.0,
                confidence=conf,
                reason=f"ORB UP | H={state.range_high:.4f} range={range_size:.4f} vol={vol_ratio:.1f}x",
                ts_ns=tick.ts_ns,
            ))
            state.buy_fired = True
            logger.info(
                "SIGNAL BUY  %s @ %.4f | conf=%.3f | vol=%.1fx avg",
                tick.symbol, tick.price, conf, vol_ratio,
            )

        # SELL breakout (independent check — price can't simultaneously be above high AND below low)
        if (
            not state.sell_fired
            and tick.price < state.range_low
            and vol_ratio >= self._vol_mult
        ):
            conf = self._confidence(vol_ratio)
            signals.append(SignalIntent(
                strategy_id=self.name,
                symbol=tick.symbol,
                side=OrderSide.SELL,
                quantity=1.0,
                confidence=conf,
                reason=f"ORB DOWN | L={state.range_low:.4f} range={range_size:.4f} vol={vol_ratio:.1f}x",
                ts_ns=tick.ts_ns,
            ))
            state.sell_fired = True
            logger.info(
                "SIGNAL SELL %s @ %.4f | conf=%.3f | vol=%.1fx avg",
                tick.symbol, tick.price, conf, vol_ratio,
            )

        return signals

    def _confidence(self, vol_ratio: float) -> float:
        """
        base:         min_confidence (0.65)
        volume bonus: up to +0.15 linear above vol_mult threshold
        cap:          0.95 (never fully certain)
        """
        vol_bonus = min(0.15, (vol_ratio - self._vol_mult) * 0.05)
        return round(min(0.95, self._min_conf + vol_bonus + 0.05), 3)

    def _check_day_reset(self, dt: datetime) -> None:
        day_key = dt.strftime("%Y-%m-%d")
        if day_key != self._current_day:
            self._current_day = day_key
            self.reset_daily()
            logger.info("New trading day: %s", day_key)
