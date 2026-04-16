# AlphaWolf 3.0v

Event-driven multi-language algorithmic trading system with IB Gateway integration.

**Stack:** Go · Python · Rust · Java · ZeroMQ · Protobuf · Docker

---

## Architecture

```
market-data-python  →  brain-python  →  risk-engine-rust  →  executor-python
     (ZMQ PUB)           (ZMQ PUB)          (ZMQ PUB)            (ZMQ PUB)
      :5555               :5556           :5557 / :5559             :5558
         ↑                                                              ↑
    IB Gateway                                                    IB Gateway
  (market data)                                                   (orders)
  Phase 7+ only                                                  Phase 7+ only
```

Services communicate **only** through the ZeroMQ event bus using Protobuf messages.
No direct service-to-service calls. Full fault isolation.

## Quick Start

```bash
git clone https://github.com/Moasinbd/alphawolf3
cd alphawolf3
cp .env.example .env
make paper     # full stack with simulated data, no IB needed
make logs      # tail all logs
```

## Development Roadmap

See [ROADMAP.md](ROADMAP.md) for the complete phase-by-phase implementation plan.

Current status: **Phase 1 complete — ready for Phase 2 (brain-python strategy engine)**

## IB Gateway Integration

IB Gateway is introduced in **Phase 7**, after the full pipeline is validated in paper mode (Phase 6).

```bash
# Phase 7+ only — requires IBKR credentials in config/ib.env
make ib-paper   # IB paper account
make live       # ⚠️  real money — only after Phase 8
```

## Event Bus Topics

| Topic | From | To | Message |
|---|---|---|---|
| `market.data` | market-data-python | brain-python | `MarketData` |
| `signal.intent` | brain-python | risk-engine-rust | `TradeIntent` |
| `risk.approved` | risk-engine-rust | executor-python | `RiskVerdict` |
| `execution.fill` | executor-python | analytics-java | `Fill` |
| `account.update` | executor-python | analytics-java | `AccountUpdate` |

## License

Private — All rights reserved.
