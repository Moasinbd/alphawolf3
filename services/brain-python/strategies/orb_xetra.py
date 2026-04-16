"""
ORBXetraStrategy — Opening Range Breakout for XETRA (Deutsche Börse)

Logic:
  - Opening Range: 09:00–09:15 CET (first 15 minutes of XETRA session)
  - Signal BUY:  price > range_high AND volume > avg_volume * volume_multiplier
  - Signal SELL: price < range_low  AND volume > avg_volume * volume_multiplier
  - One signal per direction per symbol per day (no re-entries)
  - Stop loss:   range_low (BUY) / range_high (SELL) — held by risk engine
  - Take profit: entry ± (range_size * risk_reward) — tracked externally

Why this works on XETRA:
  - XETRA opening is highly liquid (institutional orders flood in)
  - The 09:00–09:15 range captures overnight gaps + pre-market imbalance
  - Volume confirmation filters noise (false breakouts drop ~40%)
  - DAX 40 components trend well intraday when breaking range on volume
  - Latency from Europe < 10ms vs 90ms from EEUU → better fills

Paper mode:
  - Set PAPER_FORCE_SIGNALS=true to bypass market-hours check
  - Strategy simulates a rolling 15-min range window for CI/testing
"""
import logging
import os
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

import sys
sys.path.insert(0, ".")
from proto import messages_pb2 as pb

logger = logging.getLogger("strategy.orb_xetra")

BERLIN_TZ = ZoneInfo("Europe/Berlin")

# ──────────────────────────────────────────────
# Per-symbol intraday state
# ──────────────────────────────────────────────
@dataclass
class SymbolState:
    range_high: float = 0.0
    range_low: float = float("inf")
    range_established: bool = False
    buy_fired: bool = False
    sell_fired: bool = False
    volume_accumulator: float = 0.0
    tick_count: int = 0
    avg_volume_per_tick: float = 0.0
    last_price: float = 0.0

    # Paper-mode rolling window
    paper_window_start_s: float = field(default_factory=time_module.time)


# ──────────────────────────────────────────────
# Strategy
# ──────────────────────────────────────────────
class ORBXetraStrategy:
    """
    Opening Range Breakout — XETRA German market.

    Config keys (from strategies.yaml):
      symbols            List of XETRA ticker symbols
      opening_range_min  Length of opening range in minutes (default: 15)
      volume_multiplier  Volume threshold multiplier vs range average (default: 1.5)
      risk_reward        Risk/reward ratio for target (default: 2.0)
      min_confidence     Minimum confidence score (default: 0.65)
      position_size_pct  Portfolio % per trade (default: 5.0)
    """

    name = "orb_xetra"

    # XETRA trading window (CET/CEST — Europe/Berlin)
    _MARKET_OPEN  = time(9, 0)
    _RANGE_END    = time(9, 15)
    _MARKET_CLOSE = time(17, 0)

    def __init__(self, config: dict) -> None:
        self.symbols: list[str] = config["symbols"]
        self._range_minutes: int  = int(config.get("opening_range_min",  15))
        self._vol_mult: float     = float(config.get("volume_multiplier", 1.5))
        self._rr: float           = float(config.get("risk_reward",       2.0))
        self._min_conf: float     = float(config.get("min_confidence",    0.65))
        self._pos_pct: float      = float(config.get("position_size_pct", 5.0))

        # Paper-mode: bypass market hours check, use rolling window
        self._paper: bool = os.getenv("PAPER_FORCE_SIGNALS", "false").lower() == "true"
        # PAPER_RANGE_SECONDS overrides window duration for fast CI/dev testing
        # Default = real 15-minute window. Set to 30 for sub-minute test cycles.
        paper_range_override = os.getenv("PAPER_RANGE_SECONDS")
        self._paper_window_s: float = (
            float(paper_range_override)
            if paper_range_override
            else self._range_minutes * 60.0
        )

        self._states: dict[str, SymbolState] = {s: SymbolState() for s in self.symbols}
        self._current_day: Optional[str] = None

        mode = "PAPER (rolling window)" if self._paper else "LIVE (CET market hours)"
        logger.info(
            f"ORBXetraStrategy ready | {len(self.symbols)} symbols | "
            f"range={self._range_minutes}min | vol={self._vol_mult}x | "
            f"R:R={self._rr} | mode={mode}"
        )
        logger.info(f"Symbols: {', '.join(self.symbols)}")

    # ──────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────

    def on_tick(self, tick: pb.MarketData) -> list[pb.TradeIntent]:
        if tick.symbol not in self._states:
            return []

        if self._paper:
            return self._on_tick_paper(tick)
        return self._on_tick_live(tick)

    def reset_daily(self) -> None:
        self._states = {s: SymbolState() for s in self.symbols}
        logger.info("ORBXetraStrategy: daily state reset")

    # ──────────────────────────────────────────
    # Live mode — real CET time
    # ──────────────────────────────────────────

    def _on_tick_live(self, tick: pb.MarketData) -> list[pb.TradeIntent]:
        dt_berlin = self._to_berlin(tick.ts_ns)
        self._check_day_reset(dt_berlin)

        t = dt_berlin.time()
        state = self._states[tick.symbol]
        state.last_price = tick.price

        # Outside trading session
        if t < self._MARKET_OPEN or t >= self._MARKET_CLOSE:
            return []

        # During opening range: accumulate stats
        range_end = time(
            self._MARKET_OPEN.hour,
            self._MARKET_OPEN.minute + self._range_minutes,
        )
        if t < range_end:
            self._accumulate(state, tick)
            return []

        # Establish range on first tick after opening window
        if not state.range_established:
            self._establish_range(state, tick.symbol)

        return self._check_breakout(state, tick)

    # ──────────────────────────────────────────
    # Paper mode — rolling window (no market hours)
    # ──────────────────────────────────────────

    def _on_tick_paper(self, tick: pb.MarketData) -> list[pb.TradeIntent]:
        state = self._states[tick.symbol]
        state.last_price = tick.price
        now = time_module.time()

        # Reset rolling window every paper_window_s * 3 seconds
        if now - state.paper_window_start_s > self._paper_window_s * 3:
            new_state = SymbolState()
            new_state.paper_window_start_s = now
            self._states[tick.symbol] = state = new_state
            logger.debug(f"[{tick.symbol}] Paper window reset")

        elapsed = now - state.paper_window_start_s

        # First paper_window_s seconds = accumulation phase
        if elapsed < self._paper_window_s:
            self._accumulate(state, tick)
            return []

        # Establish range on transition
        if not state.range_established:
            self._establish_range(state, tick.symbol)

        return self._check_breakout(state, tick)

    # ──────────────────────────────────────────
    # Shared helpers
    # ──────────────────────────────────────────

    def _accumulate(self, state: SymbolState, tick: pb.MarketData) -> None:
        state.range_high = max(state.range_high, tick.price)
        if state.range_low == float("inf"):
            state.range_low = tick.price
        else:
            state.range_low = min(state.range_low, tick.price)
        state.volume_accumulator += tick.volume
        state.tick_count += 1

    def _establish_range(self, state: SymbolState, symbol: str) -> None:
        if state.tick_count == 0:
            return
        state.range_established = True
        state.avg_volume_per_tick = state.volume_accumulator / state.tick_count
        range_size = state.range_high - state.range_low
        range_pct  = (range_size / state.range_low * 100) if state.range_low > 0 else 0
        logger.info(
            f"[{symbol}] Range locked | "
            f"H={state.range_high:.4f} L={state.range_low:.4f} "
            f"size={range_size:.4f} ({range_pct:.2f}%) "
            f"avg_vol/tick={state.avg_volume_per_tick:.0f}"
        )

    def _check_breakout(
        self, state: SymbolState, tick: pb.MarketData
    ) -> list[pb.TradeIntent]:
        if not state.range_established:
            return []

        range_size = state.range_high - state.range_low
        if range_size <= 0 or state.avg_volume_per_tick <= 0:
            return []

        vol_ratio = tick.volume / state.avg_volume_per_tick
        intents: list[pb.TradeIntent] = []

        # ── BUY breakout ──────────────────────────────
        if (
            not state.buy_fired
            and tick.price > state.range_high
            and vol_ratio >= self._vol_mult
        ):
            conf = self._confidence(vol_ratio)
            intent = pb.TradeIntent(
                strategy_id=self.name,
                symbol=tick.symbol,
                action=pb.OrderAction.BUY,
                quantity=1.0,   # risk engine adjusts to position_size_pct
                confidence=conf,
                reason=(
                    f"ORB UP | H={state.range_high:.4f} "
                    f"range={range_size:.4f} vol={vol_ratio:.1f}x"
                ),
                ts_ns=tick.ts_ns,
            )
            state.buy_fired = True
            logger.info(
                f"SIGNAL BUY  {tick.symbol} @ {tick.price:.4f} | "
                f"conf={conf:.3f} | vol={vol_ratio:.1f}x avg"
            )
            intents.append(intent)

        # ── SELL breakout ─────────────────────────────
        elif (
            not state.sell_fired
            and tick.price < state.range_low
            and vol_ratio >= self._vol_mult
        ):
            conf = self._confidence(vol_ratio)
            intent = pb.TradeIntent(
                strategy_id=self.name,
                symbol=tick.symbol,
                action=pb.OrderAction.SELL,
                quantity=1.0,
                confidence=conf,
                reason=(
                    f"ORB DOWN | L={state.range_low:.4f} "
                    f"range={range_size:.4f} vol={vol_ratio:.1f}x"
                ),
                ts_ns=tick.ts_ns,
            )
            state.sell_fired = True
            logger.info(
                f"SIGNAL SELL {tick.symbol} @ {tick.price:.4f} | "
                f"conf={conf:.3f} | vol={vol_ratio:.1f}x avg"
            )
            intents.append(intent)

        return intents

    def _confidence(self, vol_ratio: float) -> float:
        """
        Confidence scoring:
          base:          min_confidence (0.65)
          volume bonus:  up to +0.15 (linear above threshold)
          cap:           0.95 (never certain)
        """
        vol_bonus = min(0.15, (vol_ratio - self._vol_mult) * 0.05)
        return round(min(0.95, self._min_conf + vol_bonus + 0.05), 3)

    def _to_berlin(self, ts_ns: int) -> datetime:
        return datetime.fromtimestamp(ts_ns / 1e9, tz=BERLIN_TZ)

    def _check_day_reset(self, dt: datetime) -> None:
        day_key = dt.strftime("%Y-%m-%d")
        if day_key != self._current_day:
            self._current_day = day_key
            self.reset_daily()
            logger.info(f"New trading day: {day_key}")
