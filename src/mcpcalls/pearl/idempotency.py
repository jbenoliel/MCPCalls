"""Estrategia de idempotencia del adaptador.

NLPearl no ofrece clave de idempotencia nativa en make_call. La estrategia:

1. Cada intento lleva un idempotency_key unico (UNIQUE en call_attempts).
2. El marcador viaja en callData[ATTEMPT_MARKER_KEY] para poder localizar la
   llamada en Pearl a posteriori.
3. Si la respuesta de make_call es ambigua (timeout, 200 sin id, conexion
   cortada tras enviar), el intento pasa a reconciliation_required y hay que
   consultar Get Call Request / Search Calls ANTES de permitir reintentar.
   Nunca se relanza una llamada a ciegas.
"""

import hashlib
from datetime import datetime, timezone


def make_idempotency_key(
    action_id: str,
    to_e164: str,
    window_start_utc: datetime | None = None,
) -> str:
    """Clave estable por accion+destino. La ventana la incluye el caller si
    quiere que reintentos autorizados en otra ventana sean intentos nuevos."""
    base = f"{action_id}|{to_e164}"
    if window_start_utc is not None:
        base += f"|{window_start_utc.astimezone(timezone.utc).isoformat()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def request_marker(idempotency_key: str) -> str:
    """Marcador corto que viaja en callData."""
    return f"mcp-{idempotency_key[:16]}"
