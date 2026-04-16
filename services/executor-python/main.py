"""
executor-python — AlphaWolf 3.0v

Receives approved orders from risk-engine-rust via ZMQ.
Executes via broker (PaperExecutor or IBGatewayExecutor).
Publishes Fill and AccountUpdate back to the event bus.

ZMQ Topics:
  SUB: "risk.approved"   ← Order messages from risk engine
  PUB: "execution.fill"  ← Fill confirmations
  PUB: "account.update"  ← Account snapshots (every 30s)
"""
import asyncio
import logging
import os
import sys
import time

import zmq
import zmq.asyncio

sys.path.insert(0, ".")
from broker import PaperExecutor
from broker.protocol import AccountSnapshot

from proto import messages_pb2 as pb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("executor")

# ── Config ─────────────────────────────────────
BROKER_MODE     = os.getenv("BROKER_MODE", "paper").lower()
ZMQ_SUB_HOST    = os.getenv("ZMQ_SUB_HOST", "risk-engine")
ZMQ_SUB_PORT    = int(os.getenv("ZMQ_SUB_PORT", "5557"))
ZMQ_PUB_PORT    = int(os.getenv("ZMQ_PUB_PORT", "5558"))
ZMQ_HB_PORT     = int(os.getenv("ZMQ_HB_PORT", "5561"))
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "100000"))
IB_HOST         = os.getenv("IB_HOST", "ib-gateway")
IB_PORT         = int(os.getenv("IB_PORT", "4002"))
IB_CLIENT_ID    = int(os.getenv("IB_CLIENT_ID", "2"))
ACCOUNT_POLL_S  = int(os.getenv("ACCOUNT_POLL_S", "30"))


def build_broker():
    if BROKER_MODE == "paper":
        logger.info("Mode: PAPER (simulated execution)")
        return PaperExecutor(initial_capital=INITIAL_CAPITAL)
    if BROKER_MODE in ("live", "ib"):
        logger.info(f"Mode: IB GATEWAY → {IB_HOST}:{IB_PORT}")
        from broker.ib_gateway import IBGatewayExecutor
        return IBGatewayExecutor(host=IB_HOST, port=IB_PORT, client_id=IB_CLIENT_ID)
    raise ValueError(f"Unknown BROKER_MODE: {BROKER_MODE!r}")


async def publish_account(pub: zmq.asyncio.Socket, broker) -> None:
    while True:
        try:
            acc = await broker.get_account()
            msg = pb.AccountUpdate(
                account_id=acc.account_id,
                net_liquidation=acc.net_liquidation,
                available_funds=acc.available_funds,
                unrealized_pnl=acc.unrealized_pnl,
                realized_pnl=acc.realized_pnl,
                gross_position=acc.gross_position,
                ts_ns=time.time_ns(),
            )
            pub.send_multipart([b"account.update", msg.SerializeToString()])
        except Exception as e:
            logger.error(f"Account poll error: {e}")
        await asyncio.sleep(ACCOUNT_POLL_S)


async def publish_heartbeat(pub: zmq.asyncio.Socket) -> None:
    while True:
        hb = pb.Heartbeat(
            service_name="executor-python",
            status="ok",
            version="3.0.0",
            ts_ns=time.time_ns(),
        )
        pub.send_multipart([b"system.heartbeat", hb.SerializeToString()])
        await asyncio.sleep(10)


async def main() -> None:
    ctx = zmq.asyncio.Context()

    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{ZMQ_SUB_HOST}:{ZMQ_SUB_PORT}")
    sub.setsockopt(zmq.SUBSCRIBE, b"risk.approved")
    logger.info(f"ZMQ SUB connected → tcp://{ZMQ_SUB_HOST}:{ZMQ_SUB_PORT}")

    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://*:{ZMQ_PUB_PORT}")
    logger.info(f"ZMQ PUB bound → tcp://*:{ZMQ_PUB_PORT}")

    broker = build_broker()
    await broker.connect()

    asyncio.create_task(publish_account(pub, broker))
    asyncio.create_task(publish_heartbeat(pub))

    executed = 0
    try:
        while True:
            topic, data = await sub.recv_multipart()
            order = pb.Order()
            order.ParseFromString(data)

            logger.info(f"Order received: {pb.OrderAction.Name(order.action)} "
                        f"{order.quantity} {order.symbol} [{order.order_id}]")

            result = await broker.place_order(
                symbol=order.symbol,
                action=pb.OrderAction.Name(order.action),
                quantity=order.quantity,
                order_type=pb.OrderType.Name(order.order_type),
                limit_price=order.limit_price,
                stop_price=order.stop_price,
            )

            fill = pb.Fill(
                order_id=order.order_id,
                symbol=order.symbol,
                action=order.action,
                filled_qty=result.filled_qty,
                avg_price=result.avg_price,
                status=pb.OrderStatus.FILLED if result.status == "filled" else pb.OrderStatus.REJECTED,
                commission=result.commission,
                strategy_id=order.strategy_id,
                ts_ns=time.time_ns(),
            )
            pub.send_multipart([b"execution.fill", fill.SerializeToString()])
            executed += 1
            logger.info(f"Fill published: {result.status} @ {result.avg_price:.4f} "
                        f"qty={result.filled_qty} commission=${result.commission:.2f} "
                        f"(total executed: {executed})")

    except KeyboardInterrupt:
        logger.info("Shutting down executor-python...")
    finally:
        await broker.disconnect()
        sub.close()
        pub.close()
        ctx.term()


if __name__ == "__main__":
    asyncio.run(main())
