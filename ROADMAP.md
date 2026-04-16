# AlphaWolf 3.0v — Roadmap de Implementación

> **Principio:** Cada fase produce un sistema **testeable y funcional**.
> Nunca pasamos a la siguiente fase sin validar la anterior.
> IB Gateway es el último paso — no el primero.

---

## Estado actual

| Componente | Estado |
|---|---|
| Estructura del repositorio | ✅ Completa |
| proto/messages.proto | ✅ Completo (7 mensajes, 5 enums) |
| market-data-python | ✅ Fase 1 completa — ZMQ pipeline validado (5/5 mensajes) |
| executor-python | ✅ Esqueleto completo (PaperExecutor + IBGatewayExecutor) |
| brain-python | ✅ Stub Phase 1 (sin estrategia) → Fase 2 |
| risk-engine-rust | ✅ Stub Python (aprueba todo) → Fase 3 = Rust real |
| analytics-java | ✅ Stub Python (log de eventos) → Fase 5 = Spring Boot |
| docker-compose.yml | ✅ Completo |
| Makefile | ✅ Completo |
| IB Gateway | ⏳ Fase 7 |

---

## Arquitectura del sistema

```
                          EVENT BUS (ZeroMQ)
                    ┌─────────────────────────────┐
                    │                             │
 IB Gateway ──────► market-data-python            │
 (Phase 7+)        │  PUB "market.data" :5555     │
  o PaperBroker    │                             │
                   │         brain-python         │
                   │  SUB "market.data"           │
                   │  PUB "signal.intent" :5556   │
                   │                             │
                   │      risk-engine-rust        │
                   │  SUB "signal.intent"         │
                   │  PUB "risk.approved"  :5557  │
                   │  PUB "risk.rejected"  :5559  │
                   │                             │
 IB Gateway ◄───── executor-python               │
 (Phase 7+)        │  SUB "risk.approved"         │
  o PaperExecutor  │  PUB "execution.fill" :5558  │
                   │  PUB "account.update" :5558  │
                   │                             │
                   │      analytics-java          │
                   │  SUB all topics              │
                   │  REST API :8080              │
                   │                             │
                   └─────────────────────────────┘
```

---

## Fase 0 — Fundación ✅ COMPLETA

**Objetivo:** Repositorio listo, proto definido, estructura de servicios creada.

### Entregables
- [x] Repositorio `Moasinbd/alphawolf3` creado en GitHub
- [x] `proto/messages.proto` con todos los mensajes del sistema
- [x] Estructura de directorios de los 5 servicios
- [x] `market-data-python` — PaperBroker + IBGatewayBroker (esqueleto)
- [x] `executor-python` — PaperExecutor + IBGatewayExecutor (esqueleto)
- [x] `docker-compose.yml` completo con IB Gateway en profile `ib`
- [x] `Makefile` con targets `paper`, `ib-paper`, `live`
- [x] `config/risk_limits.yaml` y `config/strategies.yaml`

### Definition of Done
```bash
git clone https://github.com/Moasinbd/alphawolf3
ls services/   # 5 directorios
cat proto/messages.proto  # 7 mensajes
```

---

## Fase 1 — Pipeline de Market Data ✅ COMPLETA

**Objetivo:** `market-data-python` publica datos reales al bus ZMQ.
Sin IB. Sin estrategia. Solo el bus de datos funcionando.

### Tareas
- [x] Completar `services/market-data-python/main.py`
- [x] Generar stubs proto para Python: `bash scripts/proto-gen.sh`
- [x] Test local: `python services/market-data-python/main.py`
- [x] Verificar mensajes ZMQ — 5/5 mensajes recibidos con proto deserialization
- [ ] Build Docker: `docker compose build market-data` (requiere Docker Desktop)
- [ ] Test en Docker: `make phase1`

### Archivos a tocar
```
services/market-data-python/main.py      ← ya tiene esqueleto, revisar imports proto
services/market-data-python/broker/paper.py  ← ya completo
scripts/proto-gen.sh                     ← ejecutar una vez
```

### Definition of Done
```bash
make paper
# En otro terminal:
python - <<'EOF'
import zmq, time
ctx = zmq.Context()
sub = ctx.socket(zmq.SUB)
sub.connect("tcp://localhost:5555")
sub.setsockopt(zmq.SUBSCRIBE, b"market.data")
for _ in range(5):
    topic, data = sub.recv_multipart()
    print(f"Received {len(data)} bytes on {topic}")
EOF
# Debe imprimir 5 mensajes con datos de mercado
```

---

## Fase 2 — Motor de Estrategia (brain-python) ⏳ SIGUIENTE

**Objetivo:** `brain-python` consume `MarketData` y publica `TradeIntent`.
Estrategia simple: momentum de precio.

### Tareas
- [ ] Crear `services/brain-python/strategies/base.py` — clase base `BaseStrategy`
- [ ] Crear `services/brain-python/strategies/vix_momentum.py` — primera estrategia
- [ ] Completar `services/brain-python/main.py` — loop ZMQ SUB → estrategia → ZMQ PUB
- [ ] Completar `services/brain-python/requirements.txt`
- [ ] Completar `services/brain-python/Dockerfile`
- [ ] Test: `make paper` → verificar que `signal.intent` se emite

### Archivos a crear
```
services/brain-python/
├── main.py                      ← loop principal
├── strategies/
│   ├── __init__.py
│   ├── base.py                  ← BaseStrategy Protocol
│   └── vix_momentum.py          ← estrategia concreta
├── requirements.txt
└── Dockerfile
```

### Definition of Done
```bash
make paper
# brain-python imprime en logs:
# "TradeIntent published: BUY 10.0 AAPL [confidence=0.72]"
```

---

## Fase 3 — Motor de Riesgo (risk-engine-rust)

**Objetivo:** `risk-engine-rust` valida `TradeIntent` contra `risk_limits.yaml`.
Rechaza órdenes que violan límites. Aprueba las que pasan.

### Tareas
- [ ] Implementar `services/risk-engine-rust/src/main.rs` — loop ZMQ SUB → validar → PUB
- [ ] Implementar `services/risk-engine-rust/src/validator.rs` — lógica de límites
- [ ] Implementar `services/risk-engine-rust/src/limits.rs` — carga de YAML
- [ ] Agregar dependencias en `Cargo.toml`: `prost`, `zmq`, `serde_yaml`
- [ ] Completar `Dockerfile` para Rust (multi-stage build)
- [ ] Test: `make paper` → verificar que `risk.approved` y `risk.rejected` se emiten

### Archivos a crear
```
services/risk-engine-rust/
├── src/
│   ├── main.rs        ← ZMQ loop + proto decode + pub
│   ├── validator.rs   ← validación contra risk_limits
│   └── limits.rs      ← struct RiskLimits + YAML loader
├── Cargo.toml         ← agregar zmq, serde_yaml, prost
├── build.rs           ← ya existe (genera stubs prost)
└── Dockerfile         ← multi-stage Rust build
```

### Definition of Done
```bash
make paper
# risk-engine logs:
# "APPROVED: BUY 10.0 AAPL [latency=45µs]"
# "REJECTED: BUY 500.0 QQQ — exceeds max_order_value_usd"
```

---

## Fase 4 — Ejecución Paper (executor-python)

**Objetivo:** `executor-python` recibe órdenes aprobadas y las "ejecuta"
con PaperExecutor. Publica fills y actualizaciones de cuenta.

### Tareas
- [ ] Verificar `services/executor-python/main.py` (ya tiene esqueleto)
- [ ] Verificar `services/executor-python/broker/paper.py` (ya completo)
- [ ] Test completo del pipeline: market-data → brain → risk → executor
- [ ] Verificar que `execution.fill` se publica correctamente
- [ ] Verificar que `account.update` refleja posiciones y P&L

### Definition of Done
```bash
make paper
# executor logs:
# "PaperExecutor FILL: BUY 10.0 AAPL @ 185.23 | commission: $0.50"
# "Account: NAV=$99,523.10 | Realized P&L=$-476.90"
```

---

## Fase 5 — Analytics (analytics-java / Spring Boot)

**Objetivo:** `analytics-java` consume todos los topics ZMQ y persiste en QuestDB.
REST API para consultar fills, P&L y posiciones.

### Tareas
- [ ] Crear `services/analytics-java/pom.xml` — Spring Boot + ZMQ + protobuf
- [ ] Crear `services/analytics-java/src/main/java/com/alphawolf/`
  - `consumer/MarketDataConsumer.java` — SUB market.data → QuestDB
  - `consumer/FillConsumer.java` — SUB execution.fill → QuestDB
  - `consumer/RiskConsumer.java` — SUB risk.rejected → QuestDB
  - `model/Fill.java`, `model/MarketTick.java`
  - `repository/QuestDbRepository.java`
  - `controller/AnalyticsController.java` — REST API
- [ ] Completar `Dockerfile` — multi-stage Java build
- [ ] Test: consultar `/api/fills`, `/api/pnl`, `/api/positions`

### Definition of Done
```bash
curl http://localhost:8080/api/fills | jq '.[0]'
# { "symbol": "AAPL", "qty": 10, "price": 185.23, "pnl": -2.50 }
```

---

## Fase 6 — Validación completa en Paper (sin IB)

**Objetivo:** El sistema completo corre en modo paper durante 48 horas sin errores.
Todas las métricas son correctas. El pipeline es estable.

### Checklist de validación
- [ ] 48h de uptime sin crashes
- [ ] Fills corresponden a señales (trazabilidad order_id)
- [ ] P&L calculado correctamente en analytics
- [ ] Risk engine rechaza correctamente órdenes fuera de límites
- [ ] Heartbeats de todos los servicios presentes en logs
- [ ] No memory leaks (revisar con `docker stats`)
- [ ] Logs estructurados en todos los servicios

### Definition of Done
```bash
make paper
sleep $((48*3600))
make status  # todos healthy
curl http://localhost:8080/api/pnl | jq '.total_trades'  # > 0
```

---

## Fase 7 — Integración IB Gateway (Paper Account)

**Objetivo:** Reemplazar PaperBroker/PaperExecutor por IBGatewayBroker/IBGatewayExecutor.
Conectar a cuenta paper real de Interactive Brokers.

### Prerequisitos
- [ ] Cuenta IBKR Paper Trading activa
- [ ] `config/ib.env` con credenciales configuradas
- [ ] Fase 6 validada (48h estable)

### Tareas
- [ ] Configurar `config/ib.env` (copiar de `ib.env.example`)
- [ ] Testear conectividad: `docker compose --profile ib up ib-gateway`
- [ ] Verificar VNC en puerto 5900 (debug si falla login)
- [ ] Cambiar `BROKER_MODE=live` en `.env`
- [ ] Ejecutar: `make ib-paper`
- [ ] Verificar que `market-data-python` recibe precios reales de IB
- [ ] Verificar que `executor-python` envía órdenes al paper account
- [ ] Verificar fills en la plataforma de IB

### Archivos a configurar
```
config/ib.env          ← credenciales IB (NO commitear)
.env                   ← BROKER_MODE=live, IB_PORT=4002
```

### Definition of Done
```bash
make ib-paper
# market-data logs: "IB data: AAPL @ 185.43"   ← precio real
# executor logs: "IB FILL: BUY 1 AAPL @ 185.43" ← orden real en paper
# Verificar en IBKR portal → Activity → Trades
```

---

## Fase 8 — Estabilización en Paper Real (15 días mínimo)

**Objetivo:** El sistema opera con IB paper account durante 15 días consecutivos.
Performance validada. Risk management probado.

### Métricas a monitorear
- Sharpe Ratio > 0.5
- Max drawdown < 5% (límite configurado en 10%)
- Win rate > 50%
- Slippage < 0.1%
- Uptime > 99%

### Checklist antes de live
- [ ] 15 días de trading paper con IB real
- [ ] Zero crashes en ese período
- [ ] P&L positivo o drawdown dentro de límites
- [ ] Fills se ejecutan correctamente en IB
- [ ] Alertas de riesgo funcionan correctamente
- [ ] Revisión manual de cada estrategia

---

## Fase 9 — Live Trading ⚠️ DINERO REAL

**Objetivo:** Cambiar a cuenta live de Interactive Brokers.
**SOLO después de validar las fases 7 y 8 completamente.**

### Prerequisitos OBLIGATORIOS
- [ ] Fase 8 completada (15 días paper)
- [ ] Revisión manual del código de ejecución
- [ ] Capital máximo configurado en risk_limits.yaml
- [ ] Alertas de emergencia configuradas (Telegram, email)
- [ ] Procedimiento de emergencia documentado

### Activación
```bash
# 1. Actualizar credenciales en config/ib.env
IB_TRADING_MODE=live

# 2. Ajustar límites de riesgo para capital real
# Editar config/risk_limits.yaml

# 3. Levantar con confirmación explícita
make live
# Te pedirá confirmación con 5 segundos de delay
```

---

## Comandos de referencia rápida

```bash
# Desarrollo diario
make paper              # Levantar stack completo en paper
make logs               # Ver todos los logs en tiempo real
make status             # Estado de contenedores

# Generación de código
make proto              # Regenerar stubs proto en todos los servicios

# Cuando tengas credenciales IB
make ib-paper           # Stack con IB Gateway paper account

# PRODUCCIÓN (después de Fase 8)
make live               # ⚠️  Live trading — DINERO REAL
```

---

## Bus de eventos — referencia de topics

| Topic | Publicado por | Consumido por | Mensaje |
|---|---|---|---|
| `market.data` | market-data-python | brain-python, analytics | `MarketData` |
| `signal.intent` | brain-python | risk-engine-rust | `TradeIntent` |
| `risk.approved` | risk-engine-rust | executor-python | `RiskVerdict` |
| `risk.rejected` | risk-engine-rust | analytics-java | `RiskVerdict` |
| `execution.fill` | executor-python | analytics-java | `Fill` |
| `account.update` | executor-python | analytics-java | `AccountUpdate` |
| `system.heartbeat` | todos | monitoring | `Heartbeat` |

---

## Puertos

| Puerto | Servicio | Protocolo |
|---|---|---|
| 5555 | market-data-python | ZMQ PUB |
| 5556 | brain-python | ZMQ PUB |
| 5557 | risk-engine-rust (approved) | ZMQ PUB |
| 5558 | executor-python | ZMQ PUB |
| 5559 | risk-engine-rust (rejected) | ZMQ PUB |
| 8080 | analytics-java | REST API |
| 9000 | QuestDB | REST / UI |
| 4002 | IB Gateway | TWS API (paper) |
| 4001 | IB Gateway | TWS API (live) |
| 5900 | IB Gateway | VNC (debug) |
