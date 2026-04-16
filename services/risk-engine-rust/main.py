"""
risk-engine — AlphaWolf 3.0v  (Phase 3+)

Adapter layer between ZMQ/Protobuf transport and the pure Python RiskEngine.

Responsibilities:
  1. Subscribe to market.data  → update_price() on every tick
  2. Subscribe to signal.intent → evaluate() each TradeRequest
  3. Approved:  publish pb.Order       on topic "risk.approved" (port ZMQ_PUB_APPROVED)
  4. Rejected:  publish pb.RiskVerdict on topic "risk.rejected"  (port ZMQ_PUB_REJECTED)
  5. Publish heartbeats

Two SUB sockets + asyncio Poller — no busy-wait, O(1) dispatch per event.

ENV vars:
  ZMQ_MARKET_HOST / ZMQ_MARKET_PORT  market-data service (default: market-data:5555)
  ZMQ_BRAIN_HOST  / ZMQ_BRAIN_PORT   brain-python service (default: brain:5556)
  ZMQ_PUB_APPROVED                    outbound approved port (default: 5557)
  ZMQ_PUB_REJECTED                    outbound rejected port (default: 5559)
  RISK_CONFIG                          path to risk_limits.yaml
  HEARTBEAT_INTERVAL_S                 (default: 10)
"""
import asyncio
import logging
import os
import sys
import time
import uuid

# Windows: use SelectorEventLoop for ZMQ asyncio compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import yaml
import zmq
import zmq.asyncio

sys.path.insert(0, ".")
from proto import messages_pb2 as pb
from risk import RiskEngine
from risk.types import RiskDecision, RiskLimits, TradeRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("risk-engine")

# ── Config ─────────────────────────────────────────────────────────────────────
ZMQ_MARKET_HOST  = os.getenv("ZMQ_MARKET_HOST",  "market-data")
ZMQ_MARKET_PORT  = int(os.getenv("ZMQ_MARKET_PORT",  "5555"))
ZMQ_BRAIN_HOST   = os.getenv("ZMQ_BRAIN_HOST",   "brain")
ZMQ_BRAIN_PORT   = int(os.getenv("ZMQ_BRAIN_PORT",   "5556"))
ZMQ_PUB_APPROVED = int(os.getenv("ZMQ_PUB_APPROVED", "5557"))
ZMQ_PUB_REJECTED = int(os.getenv("ZMQ_PUB_REJECTED", "5559"))
HEARTBEAT_S      = int(os.getenv("HEARTBEAT_INTERVAL_S", "10"))
RISK_CONFIG_PATH = os.getenv("RISK_CONFIG", "/app/config/risk_limits.yaml")


# ── YAML → RiskLimits ─────────────────────────────────────────────────────────

def load_risk_limits(path: str) -> RiskLimits:
    try:
        with open(path) as f:
            cfg = yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning("risk_limits.yaml not found at %s — using conservative defaults", path)
        return _default_limits()

    portfolio = cfg.get("portfolio", {})
    position  = cfg.get("position",  {})
    order     = cfg.get("order",     {})

    return RiskLimits(
        max_daily_loss_eur     = float(portfolio.get("max_daily_loss_eur",     15.0)),
        max_drawdown_pct       = float(portfolio.get("max_drawdown_pct",       15.0)),
        max_gross_exposure_pct = float(portfolio.get("max_gross_exposure_pct", 60.0)),
        max_size_pct           = float(position.get("max_size_pct",            15.0)),
        max_qty_per_order      = int(position.get("max_qty_per_order",         500)),
        min_confidence         = float(position.get("min_confidence",          0.65)),
        min_order_value_eur    = float(order.get("min_order_value_eur",        10.0)),
        max_order_value_eur    = float(order.get("max_order_value_eur",        50.0)),
        whitelist              = [str(s) for s in cfg.get("whitelist", [])],
        blacklist              = [str(s) for s in cfg.get("blacklist", [])],
    )


def _default_limits() -> RiskLimits:
    """Conservative defaults matching Tier 1 (EUR 100 account)."""
    return RiskLimits(
        max_daily_loss_eur=15.0, max_drawdown_pct=15.0,
        max_gross_exposure_pct=60.0, max_size_pct=15.0,
        max_qty_per_order=500, min_confidence=0.65,
        min_order_value_eur=10.0, max_order_value_eur=50.0,
        whitelist=[], blacklist=[],
    )


# ── Type adapters (transport ↔ domain) ─────────────────────────────────────────

def proto_to_request(intent: pb.TradeIntent) -> TradeRequest:
    """pb.TradeIntent → TradeRequest (pure Python domain type)."""
    return TradeRequest(
        strategy_id=intent.strategy_id,
        symbol=intent.symbol,
        side="BUY" if intent.action == pb.OrderAction.BUY else "SELL",
        quantity=intent.quantity,
        confidence=intent.confidence,
        reason=intent.reason,
        ts_ns=intent.ts_ns,
    )


def request_to_order(req: TradeRequest, decision: RiskDecision) -> pb.Order:
    """Approved TradeRequest → pb.Order for executor-python."""
    return pb.Order(
        order_id=str(uuid.uuid4()),
        symbol=req.symbol,
        action=pb.OrderAction.BUY if req.side == "BUY" else pb.OrderAction.SELL,
        quantity=decision.approved_qty,
        order_type=pb.OrderType.MKT,
        limit_price=0.0,
        stop_price=0.0,
        strategy_id=req.strategy_id,
        ts_ns=req.ts_ns,
    )


def make_verdict(intent: pb.TradeIntent, decision: RiskDecision) -> pb.RiskVerdict:
    """Rejected TradeIntent → pb.RiskVerdict for analytics."""
    return pb.RiskVerdict(
        intent=intent,
        approved=False,
        rejection_reason=decision.rejection_reason,
        approved_qty=0.0,
        latency_us=max(1, decision.latency_ns // 1000),
    )


# ── Background tasks ───────────────────────────────────────────────────────────

async def publish_heartbeat(pub: zmq.asyncio.Socket) -> None:
    while True:
        hb = pb.Heartbeat(
            service_name="risk-engine",
            status="ok",
            version="3.0.0",
            ts_ns=time.time_ns(),
        )
        pub.send_multipart([b"system.heartbeat", hb.SerializeToString()])
        await asyncio.sleep(HEARTBEAT_S)


# ── Main event loop ────────────────────────────────────────────────────────────

async def main() -> None:
    limits = load_risk_limits(RISK_CONFIG_PATH)
    engine = RiskEngine(limits)

    ctx = zmq.asyncio.Context()

    # SUB: market data ticks → price cache
    sub_market = ctx.socket(zmq.SUB)
    sub_market.connect(f"tcp://{ZMQ_MARKET_HOST}:{ZMQ_MARKET_PORT}")
    sub_market.setsockopt(zmq.SUBSCRIBE, b"market.data")
    logger.info("SUB market.data → tcp://%s:%s", ZMQ_MARKET_HOST, ZMQ_MARKET_PORT)

    # SUB: trade signals from brain
    sub_brain = ctx.socket(zmq.SUB)
    sub_brain.connect(f"tcp://{ZMQ_BRAIN_HOST}:{ZMQ_BRAIN_PORT}")
    sub_brain.setsockopt(zmq.SUBSCRIBE, b"signal.intent")
    logger.info("SUB signal.intent → tcp://%s:%s", ZMQ_BRAIN_HOST, ZMQ_BRAIN_PORT)

    # PUB: approved (Order) + rejected (RiskVerdict) + heartbeats
    # One socket bound to two ports — both receive all topics, subscribers filter.
    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://*:{ZMQ_PUB_APPROVED}")
    pub.bind(f"tcp://*:{ZMQ_PUB_REJECTED}")
    logger.info("PUB risk.approved → tcp://*:%s", ZMQ_PUB_APPROVED)
    logger.info("PUB risk.rejected → tcp://*:%s", ZMQ_PUB_REJECTED)

    # Heartbeat task — keep reference for clean shutdown + exception surfacing
    hb_task = asyncio.create_task(publish_heartbeat(pub), name="heartbeat")
    hb_task.add_done_callback(_task_error_logger)

    # Async poller — efficient multi-socket dispatch, no busy-wait
    poller = zmq.asyncio.Poller()
    poller.register(sub_market, zmq.POLLIN)
    poller.register(sub_brain,  zmq.POLLIN)

    prices_seen = 0
    approved    = 0
    rejected    = 0

    try:
        while True:
            events = dict(await poller.poll())

            # ── Market tick → price cache ──────────────────────────────────────
            if sub_market in events:
                try:
                    _, data = await sub_market.recv_multipart()
                    pb_tick = pb.MarketData()
                    pb_tick.ParseFromString(data)
                    engine.update_price(pb_tick.symbol, pb_tick.price)
                    prices_seen += 1
                except Exception as exc:
                    logger.error("Market tick error (skipping): %s", exc, exc_info=True)

            # ── Trade signal → risk evaluation ─────────────────────────────────
            if sub_brain in events:
                try:
                    _, data = await sub_brain.recv_multipart()
                    intent = pb.TradeIntent()
                    intent.ParseFromString(data)
                    req      = proto_to_request(intent)
                    decision = engine.evaluate(req)

                    if decision.approved:
                        order = request_to_order(req, decision)
                        pub.send_multipart([b"risk.approved", order.SerializeToString()])
                        approved += 1
                        logger.info(
                            "Order published: %s %.0f %s [order_id=%s]",
                            req.side, req.quantity, req.symbol,
                            order.order_id,
                        )
                    else:
                        verdict = make_verdict(intent, decision)
                        pub.send_multipart([b"risk.rejected", verdict.SerializeToString()])
                        rejected += 1
                        logger.info(
                            "Verdict published: REJECTED %s %s | %s",
                            req.side, req.symbol, decision.rejection_reason,
                        )

                except Exception as exc:
                    logger.error("Signal processing error (skipping): %s", exc, exc_info=True)

            # Periodic stats
            total = approved + rejected
            if total > 0 and total % 10 == 0:
                logger.info(
                    "Stats | prices=%d approved=%d rejected=%d",
                    prices_seen, approved, rejected,
                )

    except KeyboardInterrupt:
        logger.info("Shutting down risk-engine...")
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass
        sub_market.close()
        sub_brain.close()
        pub.close()
        ctx.term()


def _task_error_logger(task: asyncio.Task) -> None:
    """Log unexpected task failures (not cancellations)."""
    if not task.cancelled() and task.exception():
        logger.error("Background task '%s' died: %s", task.get_name(), task.exception())


if __name__ == "__main__":
    asyncio.run(main())
