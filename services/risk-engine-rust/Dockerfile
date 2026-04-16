# ─────────────────────────────────────────────────────────────
# risk-engine Dockerfile
#
# Phase 1-2: Python stub (approves all intents, pipeline validation only)
# Phase 3+:  Replace with Rust multi-stage build (see Dockerfile.rust)
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

ENV ZMQ_SUB_HOST=brain \
    ZMQ_SUB_PORT=5556 \
    ZMQ_PUB_APPROVED=5557 \
    ZMQ_PUB_REJECTED=5559 \
    HEARTBEAT_INTERVAL_S=10

CMD ["python", "stub_main.py"]
