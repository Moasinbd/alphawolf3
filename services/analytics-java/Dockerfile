# ─────────────────────────────────────────────────────────────
# analytics Dockerfile
#
# Phase 1-4: Python stub (logs events, no persistence)
# Phase 5+:  Replace with Spring Boot multi-stage build
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY services/analytics-java/requirements-stub.txt .
RUN pip install --no-cache-dir -r requirements-stub.txt

COPY proto/messages.proto ./proto/messages.proto
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=./proto \
    ./proto/messages.proto \
    && touch ./proto/__init__.py

COPY services/analytics-java/ .

ENV ZMQ_MARKET_DATA_HOST=market-data \
    ZMQ_MARKET_DATA_PORT=5555 \
    ZMQ_FILLS_HOST=executor \
    ZMQ_FILLS_PORT=5558 \
    ZMQ_RISK_HOST=risk-engine \
    ZMQ_RISK_PORT=5559

CMD ["python", "stub_main.py"]
