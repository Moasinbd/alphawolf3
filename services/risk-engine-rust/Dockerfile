# ─────────────────────────────────────────────────────────────
# risk-engine Dockerfile
#
# Phase 3+: Real Python risk engine with risk_limits.yaml validation
#           Subscribes to market.data (prices) + signal.intent (signals)
#           Publishes pb.Order on risk.approved / pb.RiskVerdict on risk.rejected
#
# Phase 7+: Replace with Rust multi-stage build (see Dockerfile.rust)
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY services/risk-engine-rust/requirements-stub.txt .
RUN pip install --no-cache-dir -r requirements-stub.txt

COPY proto/messages.proto ./proto/messages.proto
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=./proto \
    ./proto/messages.proto \
    && touch ./proto/__init__.py

COPY services/risk-engine-rust/ .

ENV ZMQ_MARKET_HOST=market-data \
    ZMQ_MARKET_PORT=5555 \
    ZMQ_BRAIN_HOST=brain \
    ZMQ_BRAIN_PORT=5556 \
    ZMQ_PUB_APPROVED=5557 \
    ZMQ_PUB_REJECTED=5559 \
    RISK_CONFIG=/app/config/risk_limits.yaml \
    HEARTBEAT_INTERVAL_S=10

CMD ["python", "main.py"]
