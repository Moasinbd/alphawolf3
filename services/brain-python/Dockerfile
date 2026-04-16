FROM python:3.11-slim

WORKDIR /app

COPY services/brain-python/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto/messages.proto ./proto/messages.proto
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=./proto \
    ./proto/messages.proto \
    && touch ./proto/__init__.py

COPY services/brain-python/ .

ENV ZMQ_SUB_HOST=market-data \
    ZMQ_SUB_PORT=5555 \
    ZMQ_PUB_PORT=5556 \
    HEARTBEAT_INTERVAL_S=10

CMD ["python", "main.py"]
