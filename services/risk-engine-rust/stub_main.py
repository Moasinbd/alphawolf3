"""
risk-engine stub (Python) — Phase 1-2 placeholder.

Approves all TradeIntents until the Rust engine is implemented in Phase 3.

CRITICAL FIX: publishes pb.Order on "risk.approved" (not RiskVerdict).
executor-python expects Order messages. RiskVerdict goes on "risk.rejected".

Pipeline contract:
  IN:  signal.intent  → pb.TradeIntent   (from brain-python)
  OUT: risk.approved  → pb.Order         (executor-python reads this)
  OUT: risk.rejected  → pb.RiskVerdict   (analytics reads this, approved=false)
  OUT: system.heartbeat
"""
import asyncio
import logging
import os
import sys
import time
import uuid

import zmq
import zmq.asyncio

# Windows: use SelectorEventLoop for ZMQ asyncio compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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


def intent_to_order(intent: pb.TradeIntent) -> pb.Order:
    """Convert approved TradeIntent → Order for executor-python."""
    return pb.Order(
        order_id=str(uuid.uuid4()),
        symbol=intent.symbol,
        action=intent.action,
        quantity=intent.quantity,
        order_type=pb.OrderType.MKT,   # stub always uses market orders
        limit_price=0.0,
        stop_price=0.0,
        strategy_id=intent.strategy_id,
        ts_ns=intent.ts_ns,
    )


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
    logger.info(f"PUB approved (Order) → tcp://*:{ZMQ_PUB_APPROVED}")
    logger.info(f"PUB rejected (RiskVerdict) → tcp://*:{ZMQ_PUB_REJECTED}")

    logger.warning(
        "risk-engine running as STUB — approves all intents as MKT orders. "
        "Phase 3 = real Rust engine with risk_limits.yaml validation."
    )
    asyncio.create_task(publish_heartbeat(pub))

    approved = 0
    try:
        while True:
            topic, data = await sub.recv_multipart()
            intent = pb.TradeIntent()
            intent.ParseFromString(data)

            t_start = time.time_ns()
            order = intent_to_order(intent)
            latency_us = max(1, (time.time_ns() - t_start) // 1000)

            # Publish Order on risk.approved (executor expects pb.Order)
            pub.send_multipart([b"risk.approved", order.SerializeToString()])
            approved += 1

            action_name = pb.OrderAction.Name(intent.action)
            logger.info(
                f"STUB APPROVED → Order | {action_name} {intent.quantity:.1f} {intent.symbol} "
                f"[conf={intent.confidence:.2f} latency={latency_us}µs] #{approved}"
            )

    except KeyboardInterrupt:
        logger.info("Shutting down risk-engine stub...")
    finally:
        sub.close()
        pub.close()
        ctx.term()


if __name__ == "__main__":
    asyncio.run(main())
