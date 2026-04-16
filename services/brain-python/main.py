"""
brain-python — AlphaWolf 3.0v (Phase 2 stub)

Consumes MarketData from ZMQ and publishes TradeIntent signals.
Phase 1 stub: logs ticks, does not publish signals yet.
Full strategy implementation in Phase 2.
"""
import asyncio
import logging
import os
import sys
import time

import zmq
import zmq.asyncio

sys.path.insert(0, ".")
from proto import messages_pb2 as pb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("brain")

ZMQ_SUB_HOST = os.getenv("ZMQ_SUB_HOST", "market-data")
ZMQ_SUB_PORT = int(os.getenv("ZMQ_SUB_PORT", "5555"))
ZMQ_PUB_PORT = int(os.getenv("ZMQ_PUB_PORT", "5556"))
HEARTBEAT_S  = int(os.getenv("HEARTBEAT_INTERVAL_S", "10"))


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
    ctx = zmq.asyncio.Context()

    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{ZMQ_SUB_HOST}:{ZMQ_SUB_PORT}")
    sub.setsockopt(zmq.SUBSCRIBE, b"market.data")
    logger.info(f"SUB connected → tcp://{ZMQ_SUB_HOST}:{ZMQ_SUB_PORT}")

    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://*:{ZMQ_PUB_PORT}")
    logger.info(f"PUB bound → tcp://*:{ZMQ_PUB_PORT}")

    logger.info("brain-python running (Phase 1 stub — strategy logic in Phase 2)")
    asyncio.create_task(publish_heartbeat(pub))

    received = 0
    try:
        while True:
            topic, data = await sub.recv_multipart()
            msg = pb.MarketData()
            msg.ParseFromString(data)
            received += 1
            if received % 20 == 0:
                logger.info(
                    f"Received {received} ticks | last: {msg.symbol} @ {msg.price:.4f} "
                    f"[strategy engine not active — Phase 2]"
                )
    except KeyboardInterrupt:
        logger.info("Shutting down brain-python...")
    finally:
        sub.close()
        pub.close()
        ctx.term()


if __name__ == "__main__":
    asyncio.run(main())
