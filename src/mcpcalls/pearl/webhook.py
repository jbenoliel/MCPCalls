"""Receptor de webhooks de NLPearl.

App Starlette con dos endpoints:
- POST /webhooks/pearl/call  (call webhook: inicio y fin de llamada)
- POST /webhooks/pearl/lead  (lead webhook: cambios de estado del lead)

Verificacion: Pearl permite configurar un token de credenciales que adjunta
a cada peticion. Lo aceptamos por header Authorization (Bearer), por
X-Webhook-Token o por query param 'token'. Sin token configurado en
settings se rechaza todo (fail closed).

Dedup y orden: cada evento se deduplica por event_key en provider_events.
Los eventos fuera de orden no degradan un intento: un estado no final
recibido despues de un estado final se registra pero no modifica el intento.

Uso: uv run python -m mcpcalls.pearl.cli serve-webhook --port 8090
"""

import hashlib
import json
import logging
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcpcalls.config import Settings, get_settings
from mcpcalls.pearl.models import AttemptStatus, is_final_call_status
from mcpcalls.pearl.store import Store

logger = logging.getLogger(__name__)

FINAL_ATTEMPT_STATUSES = frozenset(
    {AttemptStatus.COMPLETED, AttemptStatus.FAILED, AttemptStatus.CANCELLED}
)


def _check_token(request: Request, settings: Settings) -> bool:
    expected = settings.mcpcalls_webhook_token
    if not expected:
        return False
    auth = request.headers.get("authorization", "")
    header_token = request.headers.get("x-webhook-token", "")
    query_token = request.query_params.get("token", "")
    return expected in (
        auth.removeprefix("Bearer ").strip(),
        header_token,
        query_token,
    )


def _event_key(kind: str, payload: dict[str, Any]) -> str:
    """Clave de dedup: id del evento si existe, si no hash del payload."""
    for key in ("id", "eventId", "callId"):
        value = payload.get(key)
        if value:
            status = payload.get("status", "")
            return f"wh:{kind}:{value}:{status}"
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:24]
    return f"wh:{kind}:{digest}"


def _apply_event_to_attempt(store: Store, call_id: str | None, status: Any) -> None:
    """Actualiza el intento solo si el evento no llega fuera de orden."""
    if not call_id:
        return
    from sqlalchemy import select
    from mcpcalls.pearl.store import CallAttemptRow

    with store.session() as s:
        attempt = s.scalar(
            select(CallAttemptRow).where(
                CallAttemptRow.provider_call_id == call_id
            )
        )
        if attempt is None or attempt.status in FINAL_ATTEMPT_STATUSES:
            return
        try:
            status_int = int(status) if status is not None else None
        except (TypeError, ValueError):
            status_int = None
        if status_int is not None and is_final_call_status(status_int):
            attempt.status = (
                AttemptStatus.COMPLETED if status_int == 4
                else AttemptStatus.FAILED
            )
        else:
            attempt.status = AttemptStatus.RUNNING


async def _handle(kind: str, request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    store: Store = request.app.state.store

    if not _check_token(request, settings):
        logger.warning("Webhook %s rechazado: token invalido", kind)
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    if not isinstance(payload, dict):
        payload = {"items": payload}

    call_id = (
        payload.get("id")
        or payload.get("callId")
        or (payload.get("call") or {}).get("id")
    )
    status = payload.get("status")
    event_key = _event_key(kind, payload)

    is_new = store.record_provider_event(
        event_key=event_key,
        source="webhook",
        call_id=str(call_id) if call_id else None,
        status=str(status) if status is not None else "",
        payload=payload,
    )
    if not is_new:
        return JSONResponse({"ok": True, "deduplicated": True})

    if kind == "call":
        _apply_event_to_attempt(store, str(call_id) if call_id else None, status)

    store.log_event(
        f"webhook_{kind}",
        actor="pearl",
        payload={"call_id": call_id, "status": status},
    )
    return JSONResponse({"ok": True, "deduplicated": False})


async def handle_call(request: Request) -> JSONResponse:
    return await _handle("call", request)


async def handle_lead(request: Request) -> JSONResponse:
    return await _handle("lead", request)


async def handle_health(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def create_app(
    settings: Settings | None = None, store: Store | None = None
) -> Starlette:
    settings = settings or get_settings()
    app = Starlette(
        routes=[
            Route("/webhooks/pearl/call", handle_call, methods=["POST"]),
            Route("/webhooks/pearl/lead", handle_lead, methods=["POST"]),
            Route("/health", handle_health, methods=["GET"]),
        ]
    )
    app.state.settings = settings
    app.state.store = store or Store(settings.mcpcalls_db_url)
    return app
