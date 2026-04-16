"""
market-data-python — AlphaWolf 3.0v

Publishes MarketData to the ZMQ event bus.
Topic: "market.data"

Broker selection:
  BROKER_MODE=paper  → PaperBroker (no IB required, Phase 1–6)
  BROKER_MODE=live   → IBGatewayBroker (requires IB Gateway, Phase 7+)
"""
import asyncio
import logging
import os
import sys
import time

# Windows: use SelectorEventLoop for ZMQ asyncio compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import zmq
import zmq.asyncio

sys.path.insert(0, ".")
from broker import PaperBroker
from broker.protocol import TickData

from proto import messages_pb2 as pb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("market-data")

# ── Config ─────────────────────────────────────────────────────────────────────
BROKER_MODE  = os.getenv("BROKER_MODE", "paper").lower()
ZMQ_PUB_PORT = int(os.getenv("ZMQ_PUB_PORT", "5555"))
SYMBOLS      = os.getenv("SYMBOLS", "AAPL,TSLA,SPY,QQQ").split(",")
IB_HOST      = os.getenv("IB_HOST", "ib-gateway")
IB_PORT      = int(os.getenv("IB_PORT", "4002"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))
HEARTBEAT_S  = int(os.getenv("HEARTBEAT_INTERVAL_S", "10"))


def build_broker():
    if BROKER_MODE == "paper":
        logger.info("Mode: PAPER (simulated data)")
        return PaperBroker(tick_interval_s=1.0)
    if BROKER_MODE in ("live", "ib"):
        logger.info("Mode: IB GATEWAY → %s:%s", IB_HOST, IB_PORT)
        from broker.ib_gateway import IBGatewayBroker
        return IBGatewayBroker(host=IB_HOST, port=IB_PORT, client_id=IB_CLIENT_ID)
    raise ValueError(f"Unknown BROKER_MODE: {BROKER_MODE!r}. Use 'paper' or 'live'.")


def tick_to_proto(tick: TickData) -> pb.MarketData:
    source = pb.BrokerMode.PAPER if BROKER_MODE == "paper" else pb.BrokerMode.LIVE
    return pb.MarketData(
        symbol=tick.symbol,
        price=tick.price,
        bid=tick.bid,
        ask=tick.ask,
        volume=tick.volume,
        ts_ns=tick.ts_ns,
        source=source,
    )


async def publish_heartbeat(pub: zmq.asyncio.Socket) -> None:
    while True:
        hb = pb.Heartbeat(
            service_name="market-data-python",
            status="ok",
            version="3.0.0",
            ts_ns=time.time_ns(),
        )
        pub.send_multipart([b"system.heartbeat", hb.SerializeToString()])
        await asyncio.sleep(HEARTBEAT_S)


async def main() -> None:
    ctx = zmq.asyncio.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://*:{ZMQ_PUB_PORT}")
    logger.info("ZMQ PUB bound → tcp://*:%s", ZMQ_PUB_PORT)
    logger.info("Symbols: %s", SYMBOLS)

    broker = build_broker()
    await broker.connect()

    # Heartbeat task — keep reference for clean shutdown + exception surfacing
    hb_task = asyncio.create_task(publish_heartbeat(pub), name="heartbeat")
    hb_task.add_done_callback(_task_error_logger)

    published = 0
    try:
        async for tick in broker.stream_ticks(SYMBOLS):
            try:
                msg = tick_to_proto(tick)
                pub.send_multipart([b"market.data", msg.SerializeToString()])
                published += 1
                if published % 100 == 0:
                    logger.info(
                        "Published %d ticks | last: %s @ %.4f",
                        published, tick.symbol, tick.price,
                    )
            except Exception as exc:
                logger.error(
                    "Tick publish error for %s (skipping): %s",
                    tick.symbol, exc, exc_info=True,
                )
    except KeyboardInterrupt:
        logger.info("Shutting down market-data-python...")
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass
        await broker.disconnect()
        pub.close()
        ctx.term()


def _task_error_logger(task: asyncio.Task) -> None:
    """Log unexpected task failures (not cancellations)."""
    if not task.cancelled() and task.exception():
        logger.error("Background task '%s' died: %s", task.get_name(), task.exception())


if __name__ == "__main__":
    asyncio.run(main())
