# MCPCalls (MCPearl)

Servidor MCP de MCPearl: gestiones telefonicas delegadas con continuidad.
Fase 0: adaptador NLPearl validado (iniciar, consultar, reconciliar llamadas,
callbacks, idempotencia, contexto, extraccion y parada).

## Requisitos

- Python >= 3.10
- [uv](https://docs.astral.sh/uv/)
- Credenciales NLPearl en `.env` (copiar `.env.example`)

## Instalacion

```bash
uv sync
cp .env.example .env   # rellenar PEARL_ACCOUNT_ID, PEARL_SECRET_KEY, etc.
```

## Servidor MCP (stdio)

```bash
uv run python -m mcpcalls
```

Herramientas expuestas: `pearl_ping`, `pearl_place_call`, `pearl_sync_attempt`,
`pearl_reconcile`, `pearl_list_calls`.

## CLI de operacion

```bash
uv run python -m mcpcalls.pearl.cli ping                 # conexion y cuenta
uv run python -m mcpcalls.pearl.cli status               # estado del outbound
uv run python -m mcpcalls.pearl.cli call +34600000000 --objective "preguntar por el coche"
uv run python -m mcpcalls.pearl.cli poll <attempt_id>    # sincronizar estado
uv run python -m mcpcalls.pearl.cli reconcile <attempt_id>
uv run python -m mcpcalls.pearl.cli list-calls --days 3
uv run python -m mcpcalls.pearl.cli serve-webhook --port 8090
uv run python -m mcpcalls.pearl.cli validate [--live]    # bateria Fase 0
```

## Estructura

```
src/mcpcalls/
  config.py          # settings desde .env (pydantic-settings)
  server.py          # MCPServer con las tools pearl_*
  pearl/
    client.py        # httpx async, bearer auth, retry 429, pacing
    adapter.py       # place_call, reconcile, sync_attempt, ventana horaria
    store.py         # SQLite/SQLAlchemy: call_attempts, provider_events, event_log
    context.py       # ContextPackage -> callData (solo campos permitidos)
    idempotency.py   # idempotency_key + marcador callData
    normalize.py     # payload v2 -> NormalizedResult
    webhook.py       # receptor starlette con verificacion de token y dedup
    cli.py           # comandos de operacion y validacion
docs/phase0_pearl_validation.md   # checklist y hallazgos de la Fase 0
```

## Tests

```bash
uv run python -m pytest -q              # suite unitaria (sin credenciales)
uv run python -m pytest -m pearl_live   # contra la API real (requiere .env)
```

Nota: en este equipo el Control de aplicaciones bloquea `pytest.exe`
directamente; usar siempre `python -m pytest`.

## Registro en un cliente MCP

```json
{
  "mcpServers": {
    "mcpcalls": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\Users\\jbeno\\MCPCalls", "python", "-m", "mcpcalls"]
    }
  }
}
```

## Aprendizajes de produccion (tuotempo) aplicados

- `id` de make_call es Request ID, no call_id: se resuelve via
  `GET /v1/Outbound/CallRequest/{id}`.
- Estados de llamada 3/8 = en curso; nunca marcar final con duration=0.
- 429 frecuente: backoff exponencial, pacing 1s, concurrencia 2.
- Sin hangup por llamada: la unica parada real es pausar el Pearl entero.
