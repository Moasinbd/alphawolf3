"""
brain-python — AlphaWolf 3.0v

Strategy engine. Consumes MarketData from ZMQ, runs strategy logic,
publishes TradeIntents.

ZMQ:
  SUB tcp://<market-data>:<ZMQ_SUB_PORT>  topic: "market.data"
  PUB tcp://*:<ZMQ_PUB_PORT>              topic: "signal.intent"
  PUB tcp://*:<ZMQ_PUB_PORT>              topic: "system.heartbeat"

Strategy selection:
  STRATEGY=orb_xetra (default)

Paper testing:
  PAPER_FORCE_SIGNALS=true → bypass market-hours check, rolling window
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("brain")

# ── Config ──────────────────────────────────────────────────
ZMQ_SUB_HOST     = os.getenv("ZMQ_SUB_HOST", "market-data")
ZMQ_SUB_PORT     = int(os.getenv("ZMQ_SUB_PORT", "5555"))
ZMQ_PUB_PORT     = int(os.getenv("ZMQ_PUB_PORT", "5556"))
HEARTBEAT_S      = int(os.getenv("HEARTBEAT_INTERVAL_S", "10"))
STRATEGY_NAME    = os.getenv("STRATEGY", "orb_xetra")
STRATEGY_CONFIG  = os.getenv("STRATEGY_CONFIG", "/app/config/strategies.yaml")


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
        logger.warning(
            f"Config file not found: {yaml_path} — using defaults for {strategy_name}"
        )
        return _default_config(strategy_name)


def _default_config(strategy_name: str) -> dict:
    if strategy_name == "orb_xetra":
        return {
            "symbols": ["SAP", "SIE", "ALV", "DTE", "BAS", "VOW3", "DBK", "MBG", "BMW", "ADS"],
            "opening_range_min": 15,
            "volume_multiplier": 1.5,
            "risk_reward": 2.0,
            "min_confidence": 0.65,
            "position_size_pct": 5.0,
        }
    raise ValueError(f"No default config for strategy: {strategy_name}")


def build_strategy(name: str, config: dict):
    if name not in REGISTRY:
        available = list(REGISTRY.keys())
        raise ValueError(f"Unknown strategy: {name!r}. Available: {available}")
    strategy_cls = REGISTRY[name]
    return strategy_cls(config)


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


async def main() -> None:
    cfg = load_strategy_config(STRATEGY_CONFIG, STRATEGY_NAME)
    strategy = build_strategy(STRATEGY_NAME, cfg)

    ctx = zmq.asyncio.Context()

    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{ZMQ_SUB_HOST}:{ZMQ_SUB_PORT}")
    sub.setsockopt(zmq.SUBSCRIBE, b"market.data")
    logger.info(f"SUB connected → tcp://{ZMQ_SUB_HOST}:{ZMQ_SUB_PORT}")

    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://*:{ZMQ_PUB_PORT}")
    logger.info(f"PUB bound → tcp://*:{ZMQ_PUB_PORT}")
    logger.info(f"Strategy: {STRATEGY_NAME} | Symbols: {strategy.symbols}")

    asyncio.create_task(publish_heartbeat(pub))

    ticks_in = 0
    intents_out = 0

    try:
        while True:
            topic, data = await sub.recv_multipart()

            tick = pb.MarketData()
            tick.ParseFromString(data)
            ticks_in += 1

            intents = strategy.on_tick(tick)

            for intent in intents:
                pub.send_multipart([b"signal.intent", intent.SerializeToString()])
                intents_out += 1
                logger.info(
                    f"TradeIntent published: "
                    f"{'BUY' if intent.action == pb.OrderAction.BUY else 'SELL'} "
                    f"{intent.quantity:.1f} {intent.symbol} "
                    f"[confidence={intent.confidence:.2f}] "
                    f"| {intent.reason}"
                )

            if ticks_in % 100 == 0:
                logger.info(
                    f"Processed {ticks_in} ticks → {intents_out} intents published"
                )

    except KeyboardInterrupt:
        logger.info("Shutting down brain-python...")
    finally:
        sub.close()
        pub.close()
        ctx.term()


if __name__ == "__main__":
    asyncio.run(main())
