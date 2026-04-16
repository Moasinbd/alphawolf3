.PHONY: help proto paper ib-paper live stop logs status build clean

# ═══════════════════════════════════════════════════════════════════════
# AlphaWolf 3.0v — Makefile
# ═══════════════════════════════════════════════════════════════════════

help:
	@echo ""
	@echo "  AlphaWolf 3.0v — Available Commands"
	@echo ""
	@echo "  Development:"
	@echo "    make proto       Regenerate Protobuf stubs for all services"
	@echo "    make paper       Run full stack with simulated data (no IB)"
	@echo "    make ib-paper    Run full stack with IB Gateway (paper account)"
	@echo "    make live        ⚠️  Run with live IB account (REAL MONEY)"
	@echo ""
	@echo "  Operations:"
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

paper:
	@echo "Starting AlphaWolf 3.0v [PAPER MODE — simulated data]"
	BROKER_MODE=paper docker compose up -d market-data brain risk-engine executor analytics questdb
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
