.PHONY: help proto paper ib-paper live stop logs status build clean

# ═══════════════════════════════════════════════════════════════════════
# AlphaWolf 3.0v — Makefile
# ═══════════════════════════════════════════════════════════════════════

help:
	@echo ""
	@echo "  AlphaWolf 3.0v — Available Commands"
	@echo ""
	@echo "  Phased Development:"
	@echo "    make phase1      Phase 1: market-data only (ZMQ pipeline validation)"
	@echo "    make phase2      Phase 2: market-data + brain"
	@echo "    make phase3      Phase 3: market-data + brain + risk-engine"
	@echo "    make paper       Full stack with simulated data (Phase 4+)"
	@echo ""
	@echo "  IB Gateway (Phase 7+):"
	@echo "    make ib-paper    Full stack with IB Gateway (paper account)"
	@echo "    make live        ⚠️  Run with live IB account (REAL MONEY)"
	@echo ""
	@echo "  Operations:"
	@echo "    make proto       Regenerate Protobuf stubs for all services"
	@echo "    make stop        Stop all containers"
	@echo "    make logs        Tail logs for all services"
	@echo "    make status      Show container health"
	@echo "    make build       Build all Docker images"
	@echo "    make clean       Remove containers + volumes"
	@echo ""

# ── Protobuf ───────────────────────────────────────────────────────────

proto:
	@echo "Regenerating Protobuf stubs..."
	@bash scripts/proto-gen.sh
	@echo "Done."

# ── Run Modes ──────────────────────────────────────────────────────────

phase1:
	@echo "Starting AlphaWolf 3.0v [PHASE 1 — market-data pipeline only]"
	BROKER_MODE=paper PAPER_FORCE_SIGNALS=true docker compose up -d market-data
	@echo "market-data running on :5555. Validate: make logs | grep market-data"

phase2:
	@echo "Starting AlphaWolf 3.0v [PHASE 2 — market-data + brain]"
	BROKER_MODE=paper PAPER_FORCE_SIGNALS=true docker compose up -d market-data brain
	@echo "Stack running. Tail logs: make logs"

phase3:
	@echo "Starting AlphaWolf 3.0v [PHASE 3 — market-data + brain + risk-engine]"
	BROKER_MODE=paper PAPER_FORCE_SIGNALS=true docker compose up -d market-data brain risk-engine
	@echo "Stack running. Tail logs: make logs"

paper:
	@echo "Starting AlphaWolf 3.0v [PAPER MODE — full stack, simulated data]"
	BROKER_MODE=paper PAPER_FORCE_SIGNALS=true docker compose up -d market-data brain risk-engine executor analytics questdb
	@echo "Stack running. Tail logs: make logs"

ib-paper: _check-ib-credentials
	@echo "Starting AlphaWolf 3.0v [IB PAPER — real IB paper account]"
	BROKER_MODE=live IB_PORT=4002 docker compose --profile ib up -d
	@echo "Stack running with IB Gateway (paper). Tail logs: make logs"

live: _check-ib-credentials _confirm-live
	@echo "Starting AlphaWolf 3.0v [LIVE — REAL MONEY]"
	BROKER_MODE=live IB_PORT=4001 IB_TRADING_MODE=live docker compose --profile ib up -d
	@echo "Stack running with IB Gateway (LIVE)."

# ── Operations ─────────────────────────────────────────────────────────

stop:
	docker compose down

logs:
	docker compose logs -f --tail=50

status:
	docker compose ps

build:
	docker compose build

clean:
	docker compose down -v
	@echo "Containers and volumes removed."

# ── Internal Helpers ───────────────────────────────────────────────────

_check-ib-credentials:
	@test -n "$(IB_USERNAME)" || (echo "ERROR: IB_USERNAME not set in .env"; exit 1)
	@test -n "$(IB_PASSWORD)" || (echo "ERROR: IB_PASSWORD not set in .env"; exit 1)

_confirm-live:
	@echo ""
	@echo "  ⚠️  WARNING: You are about to trade with REAL MONEY."
	@echo "  Press Ctrl+C to abort. Continuing in 5 seconds..."
	@sleep 5
