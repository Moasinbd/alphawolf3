FROM python:3.11-slim

WORKDIR /app

COPY services/executor-python/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto/ ./proto/
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=./proto \
    ./proto/messages.proto

COPY services/executor-python/ .

ENV BROKER_MODE=paper \
    ZMQ_SUB_HOST=risk-engine \
    ZMQ_SUB_PORT=5557 \
    ZMQ_PUB_PORT=5558 \
    INITIAL_CAPITAL=100000 \
    ACCOUNT_POLL_S=30

CMD ["python", "main.py"]
