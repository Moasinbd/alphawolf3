"""
brain-python — AlphaWolf 3.0v

Adapter layer between ZMQ/Protobuf transport and strategy logic.

Responsibilities:
  1. Subscribe to ZMQ market.data ticks
  2. Convert pb.MarketData → TickSnapshot (transport-agnostic type)
  3. Feed each tick to the active strategy
  4. Convert SignalIntent → pb.TradeIntent and publish on ZMQ
  5. Publish heartbeats

Strategies are pure Python (no proto/ZMQ). All transport is handled here.
"""
import asyncio
import logging
import os
import sys
import time

# Windows: use SelectorEventLoop for ZMQ asyncio compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import yaml
import zmq
import zmq.asyncio

sys.path.insert(0, ".")
from proto import messages_pb2 as pb
from strategies import REGISTRY
from strategies.types import OrderSide, SignalIntent, TickSnapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("brain")

# ── Config ─────────────────────────────────────────────────────────────────────
ZMQ_SUB_HOST    = os.getenv("ZMQ_SUB_HOST", "market-data")
ZMQ_SUB_PORT    = int(os.getenv("ZMQ_SUB_PORT", "5555"))
ZMQ_PUB_PORT    = int(os.getenv("ZMQ_PUB_PORT", "5556"))
HEARTBEAT_S     = int(os.getenv("HEARTBEAT_INTERVAL_S", "10"))
STRATEGY_NAME   = os.getenv("STRATEGY", "orb_xetra")
STRATEGY_CONFIG = os.getenv("STRATEGY_CONFIG", "/app/config/strategies.yaml")


# ── Config loading ─────────────────────────────────────────────────────────────

def load_strategy_config(yaml_path: str, strategy_name: str) -> dict:
    try:
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        strategies = cfg.get("strategies", {})
        if strategy_name not in strategies:
            raise ValueError(
                f"Strategy '{strategy_name}' not found in {yaml_path}. "
                f"Available: {list(strategies.keys())}"
            )
        return strategies[strategy_name]
    except FileNotFoundError:
        logger.warning("Config not found: %s — using built-in defaults", yaml_path)
        return _default_config(strategy_name)


def _default_config(strategy_name: str) -> dict:
    if strategy_name == "orb_xetra":
        return {
            "symbols": ["SAP", "SIE", "ALV", "DTE", "BAS", "VOW3",
                        "DBK", "MBG", "BMW", "ADS", "EXW1", "EXSA"],
            "opening_range_min": 15,
            "volume_multiplier": 1.5,
            "risk_reward": 2.0,
            "min_confidence": 0.65,
            "position_size_pct": 5.0,
        }
    raise ValueError(f"No built-in default config for strategy: {strategy_name!r}")


def build_strategy(name: str, config: dict):
    if name not in REGISTRY:
        raise ValueError(f"Unknown strategy: {name!r}. Available: {list(REGISTRY.keys())}")
    return REGISTRY[name](config)


# ── Type adapters (transport ↔ domain) ─────────────────────────────────────────

def proto_to_tick(pb_tick: pb.MarketData) -> TickSnapshot:
    """pb.MarketData → TickSnapshot (pure Python domain type)."""
    return TickSnapshot(
        symbol=pb_tick.symbol,
        price=pb_tick.price,
        bid=pb_tick.bid,
        ask=pb_tick.ask,
        volume=pb_tick.volume,
        ts_ns=pb_tick.ts_ns,
    )


def signal_to_proto(sig: SignalIntent) -> pb.TradeIntent:
    """SignalIntent → pb.TradeIntent (ZMQ transport type)."""
    return pb.TradeIntent(
        strategy_id=sig.strategy_id,
        symbol=sig.symbol,
        action=pb.OrderAction.BUY if sig.side == OrderSide.BUY else pb.OrderAction.SELL,
        quantity=sig.quantity,
        confidence=sig.confidence,
        reason=sig.reason,
        ts_ns=sig.ts_ns,
    )


# ── Background tasks ───────────────────────────────────────────────────────────

async def publish_heartbeat(pub: zmq.asyncio.Socket) -> None:
    while True:
        hb = pb.Heartbeat(
            service_name="brain-python",
            status="ok",
            version="3.0.0",
            ts_ns=time.time_ns(),
        )
        pub.send_multipart([b"system.heartbeat", hb.SerializeToString()])
        await asyncio.sleep(HEARTBEAT_S)


# ── Main event loop ────────────────────────────────────────────────────────────

async def main() -> None:
    cfg      = load_strategy_config(STRATEGY_CONFIG, STRATEGY_NAME)
    strategy = build_strategy(STRATEGY_NAME, cfg)

    ctx = zmq.asyncio.Context()
    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{ZMQ_SUB_HOST}:{ZMQ_SUB_PORT}")
    sub.setsockopt(zmq.SUBSCRIBE, b"market.data")
    logger.info("SUB connected → tcp://%s:%s", ZMQ_SUB_HOST, ZMQ_SUB_PORT)

    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://*:{ZMQ_PUB_PORT}")
    logger.info("PUB bound → tcp://*:%s", ZMQ_PUB_PORT)
    logger.info("Strategy: %s | Symbols: %s", STRATEGY_NAME, strategy.symbols)

    # Heartbeat task — keep reference for clean shutdown + exception surfacing
    hb_task = asyncio.create_task(publish_heartbeat(pub), name="heartbeat")
    hb_task.add_done_callback(_task_error_logger)

    ticks_in   = 0
    intents_out = 0

    try:
        while True:
            topic, data = await sub.recv_multipart()

            try:
                pb_tick = pb.MarketData()
                pb_tick.ParseFromString(data)
                tick = proto_to_tick(pb_tick)
                signals = strategy.on_tick(tick)
            except Exception as exc:
                logger.error("Tick processing error (skipping): %s", exc, exc_info=True)
                continue   # one bad tick never kills the service

            for sig in signals:
                try:
                    intent = signal_to_proto(sig)
                    pub.send_multipart([b"signal.intent", intent.SerializeToString()])
                    intents_out += 1
                    logger.info(
                        "TradeIntent published: %s %.1f %s [conf=%.2f] | %s",
                        "BUY" if sig.side == OrderSide.BUY else "SELL",
                        sig.quantity, sig.symbol, sig.confidence, sig.reason,
                    )
                except Exception as exc:
                    logger.error("Publish error for signal %s: %s", sig.symbol, exc, exc_info=True)

            ticks_in += 1
            if ticks_in % 100 == 0:
                logger.info("Processed %d ticks → %d intents", ticks_in, intents_out)

    except KeyboardInterrupt:
        logger.info("Shutting down brain-python...")
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass   # expected on clean shutdown
        sub.close()
        pub.close()
        ctx.term()


def _task_error_logger(task: asyncio.Task) -> None:
    """Log unexpected task failures (not cancellations)."""
    if not task.cancelled() and task.exception():
        logger.error("Background task '%s' died: %s", task.get_name(), task.exception())


if __name__ == "__main__":
    asyncio.run(main())
