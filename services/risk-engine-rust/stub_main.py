"""
risk-engine stub (Python) — Phase 1-2 placeholder.

Approves all TradeIntents until the Rust engine is implemented in Phase 3.
This file is only used during early phases for pipeline validation.
"""
import asyncio
import logging
import os
import sys
import time
import uuid

import zmq
import zmq.asyncio

sys.path.insert(0, ".")
from proto import messages_pb2 as pb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("risk-engine-stub")

ZMQ_SUB_HOST     = os.getenv("ZMQ_SUB_HOST", "brain")
ZMQ_SUB_PORT     = int(os.getenv("ZMQ_SUB_PORT", "5556"))
ZMQ_PUB_APPROVED = int(os.getenv("ZMQ_PUB_APPROVED", "5557"))
ZMQ_PUB_REJECTED = int(os.getenv("ZMQ_PUB_REJECTED", "5559"))
HEARTBEAT_S      = int(os.getenv("HEARTBEAT_INTERVAL_S", "10"))


async def publish_heartbeat(pub: zmq.asyncio.Socket) -> None:
    while True:
        hb = pb.Heartbeat(
            service_name="risk-engine-stub",
            status="ok",
            version="3.0.0-stub",
            ts_ns=time.time_ns(),
        )
        pub.send_multipart([b"system.heartbeat", hb.SerializeToString()])
        await asyncio.sleep(HEARTBEAT_S)


async def main() -> None:
    ctx = zmq.asyncio.Context()

    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{ZMQ_SUB_HOST}:{ZMQ_SUB_PORT}")
    sub.setsockopt(zmq.SUBSCRIBE, b"signal.intent")
    logger.info(f"SUB connected → tcp://{ZMQ_SUB_HOST}:{ZMQ_SUB_PORT}")

    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://*:{ZMQ_PUB_APPROVED}")
    pub.bind(f"tcp://*:{ZMQ_PUB_REJECTED}")
    logger.info(f"PUB approved → tcp://*:{ZMQ_PUB_APPROVED}")
    logger.info(f"PUB rejected → tcp://*:{ZMQ_PUB_REJECTED}")

    logger.warning("risk-engine running as STUB — approves all intents. Phase 3 = real Rust engine.")
    asyncio.create_task(publish_heartbeat(pub))

    approved = 0
    try:
        while True:
            topic, data = await sub.recv_multipart()
            intent = pb.TradeIntent()
            intent.ParseFromString(data)

            t_start = time.time_ns()
            verdict = pb.RiskVerdict(
                intent=intent,
                approved=True,
                rejection_reason="",
                approved_qty=intent.quantity,
                latency_us=max(1, (time.time_ns() - t_start) // 1000),
            )
            pub.send_multipart([b"risk.approved", verdict.SerializeToString()])
            approved += 1
            logger.info(
                f"STUB APPROVED: {intent.action} {intent.quantity} {intent.symbol} "
                f"[conf={intent.confidence:.2f}] #{approved}"
            )
    except KeyboardInterrupt:
        logger.info("Shutting down risk-engine stub...")
    finally:
        sub.close()
        pub.close()
        ctx.term()


if __name__ == "__main__":
    asyncio.run(main())
