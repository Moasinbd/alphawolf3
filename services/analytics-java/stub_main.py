"""
analytics stub (Python) — Phase 1-4 placeholder.

Subscribes to all ZMQ topics, logs events.
Full Spring Boot / QuestDB implementation in Phase 5.
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
logger = logging.getLogger("analytics-stub")

MARKET_HOST  = os.getenv("ZMQ_MARKET_DATA_HOST", "market-data")
MARKET_PORT  = int(os.getenv("ZMQ_MARKET_DATA_PORT", "5555"))
FILLS_HOST   = os.getenv("ZMQ_FILLS_HOST", "executor")
FILLS_PORT   = int(os.getenv("ZMQ_FILLS_PORT", "5558"))
RISK_HOST    = os.getenv("ZMQ_RISK_HOST", "risk-engine")
RISK_PORT    = int(os.getenv("ZMQ_RISK_PORT", "5559"))


async def subscribe(ctx: zmq.asyncio.Context, addr: str, topics: list[bytes]) -> None:
    sub = ctx.socket(zmq.SUB)
    sub.connect(addr)
    for t in topics:
        sub.setsockopt(zmq.SUBSCRIBE, t)
    logger.info(f"Analytics SUB → {addr}")
    counts: dict[bytes, int] = {}
    try:
        while True:
            topic, data = await sub.recv_multipart()
            counts[topic] = counts.get(topic, 0) + 1
            if sum(counts.values()) % 50 == 0:
                summary = " | ".join(f"{t.decode()}={n}" for t, n in counts.items())
                logger.info(f"Event counts: {summary}")
    finally:
        sub.close()


async def main() -> None:
    ctx = zmq.asyncio.Context()
    logger.warning("analytics running as STUB — no QuestDB persistence. Phase 5 = Spring Boot.")

    await asyncio.gather(
        subscribe(ctx, f"tcp://{MARKET_HOST}:{MARKET_PORT}", [b"market.data", b"system.heartbeat"]),
        subscribe(ctx, f"tcp://{FILLS_HOST}:{FILLS_PORT}",  [b"execution.fill", b"account.update"]),
        subscribe(ctx, f"tcp://{RISK_HOST}:{RISK_PORT}",    [b"risk.rejected"]),
    )


if __name__ == "__main__":
    asyncio.run(main())
