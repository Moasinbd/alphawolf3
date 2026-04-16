#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# proto-gen.sh — Regenerate Protobuf stubs for all services
#
# Run from project root: bash scripts/proto-gen.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

PROTO_SRC="./proto/messages.proto"
PROTO_DIR="./proto"

echo "Source: $PROTO_SRC"
echo ""

# ── Python: market-data-python ────────────────────────────────
echo "[Python] market-data-python..."
python -m grpc_tools.protoc \
  -I="$PROTO_DIR" \
  --python_out="services/market-data-python/proto" \
  "$PROTO_SRC"

# ── Python: brain-python ──────────────────────────────────────
echo "[Python] brain-python..."
mkdir -p services/brain-python/proto
python -m grpc_tools.protoc \
  -I="$PROTO_DIR" \
  --python_out="services/brain-python/proto" \
  "$PROTO_SRC"

# ── Python: executor-python ───────────────────────────────────
echo "[Python] executor-python..."
mkdir -p services/executor-python/proto
python -m grpc_tools.protoc \
  -I="$PROTO_DIR" \
  --python_out="services/executor-python/proto" \
  "$PROTO_SRC"

# ── Go: risk-engine-go (future) / ingestor-go ─────────────────
if command -v protoc-gen-go &>/dev/null; then
  echo "[Go] shared stubs..."
  mkdir -p shared/proto/go
  protoc \
    -I="$PROTO_DIR" \
    --go_out="shared/proto/go" \
    --go_opt=paths=source_relative \
    "$PROTO_SRC"
else
  echo "[Go] protoc-gen-go not found — skipping Go stubs"
fi

# ── Rust: prost (via build.rs) ────────────────────────────────
echo "[Rust] stubs generated at build time via prost (build.rs)"

echo ""
echo "Proto generation complete."
