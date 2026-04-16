FROM python:3.11-slim

WORKDIR /app

# Dependencies first (layer cache)
COPY services/market-data-python/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Proto stubs — generated at build time
COPY proto/messages.proto ./proto/messages.proto
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=./proto \
    ./proto/messages.proto \
    && touch ./proto/__init__.py

# Service source
COPY services/market-data-python/ .

ENV BROKER_MODE=paper \
    ZMQ_PUB_PORT=5555 \
    SYMBOLS=AAPL,TSLA,SPY,QQQ \
    HEARTBEAT_INTERVAL_S=10

CMD ["python", "main.py"]
