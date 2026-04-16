"""
market-data-python — AlphaWolf 3.0v

Publishes MarketData to the ZMQ event bus.
Topic: "market.data"

Broker selection via environment variable:
  BROKER_MODE=paper  → PaperBroker (no IB required)
  BROKER_MODE=live   → IBGatewayBroker (requires IB Gateway)
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

# ── Protobuf stubs (generated — do not edit) ──
from proto import messages_pb2 as pb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("market-data")

# ── Config from environment ────────────────────
BROKER_MODE   = os.getenv("BROKER_MODE", "paper").lower()
ZMQ_PUB_PORT  = int(os.getenv("ZMQ_PUB_PORT", "5555"))
ZMQ_HB_PORT   = int(os.getenv("ZMQ_HB_PORT", "5560"))
SYMBOLS       = os.getenv("SYMBOLS", "AAPL,TSLA,SPY,QQQ").split(",")
IB_HOST       = os.getenv("IB_HOST", "ib-gateway")
IB_PORT       = int(os.getenv("IB_PORT", "4002"))
IB_CLIENT_ID  = int(os.getenv("IB_CLIENT_ID", "1"))
HEARTBEAT_S   = int(os.getenv("HEARTBEAT_INTERVAL_S", "10"))


def build_broker():
    if BROKER_MODE == "paper":
        logger.info("Mode: PAPER (simulated data)")
        return PaperBroker(tick_interval_s=1.0)

    if BROKER_MODE in ("live", "ib"):
        logger.info(f"Mode: IB GATEWAY → {IB_HOST}:{IB_PORT}")
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
    logger.info(f"ZMQ PUB bound → tcp://*:{ZMQ_PUB_PORT}")
    logger.info(f"Symbols: {SYMBOLS}")

    broker = build_broker()
    await broker.connect()

    asyncio.create_task(publish_heartbeat(pub))

    published = 0
    try:
        async for tick in broker.stream_ticks(SYMBOLS):
            msg = tick_to_proto(tick)
            pub.send_multipart([
                b"market.data",
                msg.SerializeToString(),
            ])
            published += 1
            if published % 100 == 0:
                logger.info(f"Published {published} ticks | last: {tick.symbol} @ {tick.price:.4f}")
    except KeyboardInterrupt:
        logger.info("Shutting down market-data-python...")
    finally:
        await broker.disconnect()
        pub.close()
        ctx.term()


if __name__ == "__main__":
    asyncio.run(main())
