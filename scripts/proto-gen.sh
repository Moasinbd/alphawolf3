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
mkdir -p services/market-data-python/proto
python -m grpc_tools.protoc \
  -I="$PROTO_DIR" \
  --python_out="services/market-data-python/proto" \
  "$PROTO_SRC"
touch services/market-data-python/proto/__init__.py

# ── Python: brain-python ──────────────────────────────────────
echo "[Python] brain-python..."
mkdir -p services/brain-python/proto
python -m grpc_tools.protoc \
  -I="$PROTO_DIR" \
  --python_out="services/brain-python/proto" \
  "$PROTO_SRC"
touch services/brain-python/proto/__init__.py

# ── Python: executor-python ───────────────────────────────────
echo "[Python] executor-python..."
mkdir -p services/executor-python/proto
python -m grpc_tools.protoc \
  -I="$PROTO_DIR" \
  --python_out="services/executor-python/proto" \
  "$PROTO_SRC"
touch services/executor-python/proto/__init__.py

# ── Python: risk-engine-rust (stub only — replaced by Rust in Phase 3) ──
echo "[Python] risk-engine-rust (stub)..."
mkdir -p services/risk-engine-rust/proto
python -m grpc_tools.protoc \
  -I="$PROTO_DIR" \
  --python_out="services/risk-engine-rust/proto" \
  "$PROTO_SRC"
touch services/risk-engine-rust/proto/__init__.py

# ── Python: analytics-java (stub only — replaced by Java in Phase 5) ──
echo "[Python] analytics-java (stub)..."
mkdir -p services/analytics-java/proto
python -m grpc_tools.protoc \
  -I="$PROTO_DIR" \
  --python_out="services/analytics-java/proto" \
  "$PROTO_SRC"
touch services/analytics-java/proto/__init__.py

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
