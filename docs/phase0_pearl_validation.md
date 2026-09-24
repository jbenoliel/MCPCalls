# Fase 0 — Validacion del adaptador NLPearl

Checklist de los puntos que la Fase 0 debe validar segun el spec
(`MCPearl_Especificaciones_Desarrollo.docx`, seccion 10: "validar adaptador
Pearl, callbacks, idempotencia, contexto, extraccion y parada").

Estado: PENDIENTE de ejecucion con credenciales reales. La suite unitaria
(37 tests) ya cubre la logica interna; este documento recoge lo que hay que
verificar contra la API real y donde registrar los hallazgos.

## Como ejecutar

```bash
# rellenar .env con las credenciales (ver .env.example)
uv run python -m mcpcalls.pearl.cli validate          # checks sin llamada
uv run python -m mcpcalls.pearl.cli validate --live   # incluye llamada real
uv run python -m pytest -m pearl_live                 # tests contra API real
```

## Checklist

### 1. Iniciar llamada (make_call v1)

- [ ] `POST /v1/Outbound/{outboundId}/Call` acepta `{to, callData}` y devuelve
      `id` (Request ID) + `queuePosition`.
- [ ] Confirmado que `id` de la respuesta es Request ID (no call_id):
      el call_id se obtiene despues via `GET /v1/Outbound/CallRequest/{id}`
      cuando la llamada sale de cola.
- [ ] Comportamiento con outbound pausado: la llamada queda en cola y sale
      al reactivar (cola "fantasma" observada en tuotempo).

### 2. Consultar estado (polling)

- [ ] `GET /v1/Outbound/CallRequest/{requestId}`: status 1 InCallQueue,
      2 OnCall, 10 Completed, 20 BlackListed, 100 Error; campo `callId`.
- [ ] `GET /v2/Call/{callId}`: status 3/8 = en curso (NO finales),
      4 Completed, 5 Busy, 6 Failed, 7 NoAnswer.
- [ ] `POST /v2/Pearl/{pearlId}/Calls` para busqueda por ventana temporal.

### 3. Idempotencia

- [ ] Confirmado: la API NO acepta clave de idempotencia en make_call.
- [ ] Estrategia implementada: `idempotency_key` UNIQUE en `call_attempts`,
      marcador `mcpearl_attempt_id` en `callData`, reconciliacion por
      CallRequest/Search Calls antes de reintentar.
- [ ] Verificado en vivo: mismo intento dos veces = una sola llamada.

### 4. Contexto (callData)

- [ ] Las variables de `callData` llegan al flow del Pearl (visibles en la
      llamada de prueba / transcript).
- [ ] Limite practico de tamano/campos de `callData`: medir y anotar.
- [ ] Solo viajan campos en `allowed_to_share` (verificado en unitario).

### 5. Extraccion (variables PostCall)

- [ ] `GET /v2/Call/{id}` devuelve `summary`, `transcript` (lista de turnos
      `{role, content}`), `collectedInfo`, `recording`, `credits`.
- [ ] Anotar que variables PostCall rellena realmente el Pearl dedicado
      (depende de su configuracion de flow).

### 6. Parada

- [ ] Confirmado: NO existe endpoint de hangup por llamada individual.
      Mecanismos reales: `PUT /v2/Pearl/{id}/Active` (pausa el Pearl entero)
      y borrado de leads en cola (solo aplica a add_lead v2, no a make_call).
- [ ] Pregunta abierta para soporte NLPearl: posibilidad de cancelar una
      llamada en cola o en curso por API.
- [ ] Implicacion para Fase 1: la cancelacion de una accion ya enviada debe
      asumir "si ya empezo, reflejar resultado real" (spec seccion 9).

### 7. Callbacks (webhooks)

- [ ] Receptor implementado: `POST /webhooks/pearl/call` y `/lead` con
      verificacion de token y dedup por evento.
- [ ] Pendiente validar en vivo: registrar `callWebhookUrl` en el outbound
      con URL publica (tunel) y comprobar llegada + formato real del payload
      (documentar payload de ejemplo aqui).

## Hallazgos

(Registrar aqui los resultados de la ejecucion con credenciales reales.)

- API v1 vs v2: make_call usa outbound_id de v1; consultas de llamada usan
  pearl_id de v2. Ambos configurables por env.
- Rate limit 429 confirmado en produccion (tuotempo): el cliente aplica
  backoff 2s/4s/8s, pacing 1s y concurrencia 2.
