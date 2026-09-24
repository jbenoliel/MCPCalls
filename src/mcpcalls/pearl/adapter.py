"""Adaptador semantico de NLPearl.

Orquesta PearlClient + Store aplicando las reglas del spec:
- Dedup por idempotency_key: la misma accion nunca genera dos llamadas.
- Respuesta ambigua de make_call => reconciliation_required y reconciliacion
  via Get Call Request / Search Calls antes de permitir reintentar.
- Estados 3/8 no finales: nunca marcar completed con duration=0.
- Ventana horaria configurable: fuera de ventana no se marca.
- Parada: la API no ofrece hangup por llamada; el unico mecanismo real es
  pausar el Pearl entero (documentado como limitacion de la Fase 0).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from mcpcalls.config import Settings, get_settings
from mcpcalls.pearl.client import PearlAPIError, PearlClient
from mcpcalls.pearl.context import ContextPackage
from mcpcalls.pearl.idempotency import make_idempotency_key, request_marker
from mcpcalls.pearl.models import (
    AttemptStatus,
    NormalizedResult,
    OutboundStatus,
)
from mcpcalls.pearl.normalize import normalize_call
from mcpcalls.pearl.store import Store

logger = logging.getLogger(__name__)

# Estados de una peticion API (Get Call Request)
_REQUEST_STATUS_NAMES = {
    1: "InCallQueue",
    2: "OnCall",
    10: "Completed",
    20: "BlackListed",
    100: "Error",
}


def parse_calling_window(spec: str) -> tuple[str, str, ZoneInfo]:
    """'09:00-21:00 Europe/Madrid' -> ('09:00', '21:00', ZoneInfo)."""
    window, _, tz_name = spec.partition(" ")
    start, _, end = window.partition("-")
    return start.strip(), end.strip(), ZoneInfo(tz_name.strip())


class PearlAdapter:
    """Operaciones de alto nivel sobre NLPearl con persistencia y dedup."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: PearlClient | None = None,
        store: Store | None = None,
    ):
        self.settings = settings or get_settings()
        self._owns_client = client is None
        self.client = client or PearlClient(self.settings)
        self.store = store or Store(self.settings.mcpcalls_db_url)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    # ---------- ventana horaria ----------

    def within_calling_window(self, at: datetime | None = None) -> bool:
        start, end, tz = parse_calling_window(self.settings.mcpcalls_calling_window)
        now = (at or datetime.now(timezone.utc)).astimezone(tz)
        hhmm = now.strftime("%H:%M")
        if start <= end:
            return start <= hhmm < end
        return hhmm >= start or hhmm < end

    # ---------- informacion de campana ----------

    async def ping(self) -> dict[str, Any]:
        outbounds = await self.client.list_outbounds()
        return {"ok": True, "outbounds": len(outbounds)}

    async def get_outbound_status(
        self, outbound_id: str | None = None
    ) -> dict[str, Any]:
        outbound_id = outbound_id or self.settings.pearl_outbound_id
        details = await self.client.get_outbound(outbound_id)
        status = details.get("status")
        try:
            status_name = OutboundStatus(status).name
        except ValueError:
            status_name = f"Unknown({status})"
        return {
            "outbound_id": outbound_id,
            "status": status,
            "status_name": status_name,
            "is_active": status == int(OutboundStatus.RUNNING),
            "total_agents": details.get("totalAgents"),
            "pearl_name": details.get("pearlName"),
            "raw": details,
        }

    async def set_pearl_active(
        self, is_active: bool, pearl_id: str | None = None
    ) -> Any:
        """Unico mecanismo de 'parada' disponible: pausa/reanuda el Pearl entero.

        No existe endpoint de hangup por llamada individual en la API.
        """
        pearl_id = pearl_id or self.settings.pearl_id
        return await self.client.set_pearl_active(pearl_id, is_active)

    # ---------- ciclo de llamada ----------

    async def place_call(
        self,
        to: str,
        context: ContextPackage,
        action_id: str = "manual",
        outbound_id: str | None = None,
    ) -> dict[str, Any]:
        """Crea el intento y marca la llamada.

        Devuelve {attempt_id, status, provider_request_id?, error?}.
        """
        outbound_id = outbound_id or self.settings.pearl_outbound_id
        idem_key = make_idempotency_key(action_id, to)
        attempt = self.store.create_attempt(
            idem_key, to, outbound_id, context.model_dump(mode="json")
        )

        if attempt.status not in (
            AttemptStatus.PENDING,
            AttemptStatus.RECONCILIATION_REQUIRED,
            AttemptStatus.FAILED,
        ):
            self.store.log_event(
                "place_call_deduplicated",
                attempt_id=attempt.id,
                payload={"idempotency_key": idem_key, "status": attempt.status},
            )
            return {
                "attempt_id": attempt.id,
                "status": attempt.status,
                "provider_request_id": attempt.provider_request_id,
                "provider_call_id": attempt.provider_call_id,
                "deduplicated": True,
            }

        if attempt.status == AttemptStatus.RECONCILIATION_REQUIRED:
            return {
                "attempt_id": attempt.id,
                "status": AttemptStatus.RECONCILIATION_REQUIRED,
                "error": {
                    "code": "execution_uncertain",
                    "message": "El intento anterior tuvo respuesta ambigua; "
                               "hay que reconciliar antes de reintentar.",
                    "retryable": False,
                },
            }

        if not self.within_calling_window():
            self.store.update_attempt(
                attempt.id, status=AttemptStatus.BLOCKED,
                error="outside_calling_window",
            )
            self.store.log_event(
                "place_call_blocked_window", attempt_id=attempt.id,
            )
            return {
                "attempt_id": attempt.id,
                "status": AttemptStatus.BLOCKED,
                "error": {
                    "code": "outside_calling_window",
                    "message": "Fuera de la ventana horaria de llamada.",
                    "retryable": True,
                },
            }

        call_data = context.to_call_data(request_marker(idem_key))
        try:
            response = await self.client.make_call(outbound_id, to, call_data)
        except PearlAPIError as e:
            if e.retryable:
                # No sabemos si la peticion llego: hay que reconciliar.
                self.store.update_attempt(
                    attempt.id,
                    status=AttemptStatus.RECONCILIATION_REQUIRED,
                    error=f"{e.code}: {e}",
                )
                self.store.log_event(
                    "place_call_uncertain", attempt_id=attempt.id,
                    payload=e.to_dict(),
                )
                return {
                    "attempt_id": attempt.id,
                    "status": AttemptStatus.RECONCILIATION_REQUIRED,
                    "error": e.to_dict(),
                }
            self.store.update_attempt(
                attempt.id, status=AttemptStatus.FAILED, error=str(e)
            )
            self.store.log_event(
                "place_call_failed", attempt_id=attempt.id,
                payload=e.to_dict(),
            )
            return {
                "attempt_id": attempt.id,
                "status": AttemptStatus.FAILED,
                "error": e.to_dict(),
            }

        request_id = response.get("id")
        if not request_id:
            # 200 sin id de peticion: ambiguo, reconciliar por telefono.
            self.store.update_attempt(
                attempt.id,
                status=AttemptStatus.RECONCILIATION_REQUIRED,
                error="no_request_id_in_response",
                last_result_json=response,
            )
            self.store.log_event(
                "place_call_no_request_id",
                attempt_id=attempt.id,
                payload=response,
            )
            return {
                "attempt_id": attempt.id,
                "status": AttemptStatus.RECONCILIATION_REQUIRED,
                "error": {
                    "code": "execution_uncertain",
                    "message": "Pearl devolvio 200 sin id de peticion.",
                    "retryable": False,
                },
            }

        queue_position = response.get("queuePosition") or 0
        self.store.update_attempt(
            attempt.id,
            status=AttemptStatus.SUBMITTED,
            provider_request_id=request_id,
            last_result_json=response,
        )
        self.store.log_event(
            "place_call_submitted",
            attempt_id=attempt.id,
            payload={
                "request_id": request_id,
                "queue_position": queue_position,
            },
        )
        if queue_position > 50:
            logger.warning(
                "Cola de Pearl saturada: %s llamadas pendientes", queue_position
            )
        return {
            "attempt_id": attempt.id,
            "status": AttemptStatus.SUBMITTED,
            "provider_request_id": request_id,
            "queue_position": queue_position,
        }

    async def reconcile(self, attempt_id: int) -> dict[str, Any]:
        """Resuelve un intento incierto consultando a Pearl.

        1) Si hay provider_request_id, Get Call Request da el callId real.
        2) Si no, Search Calls por telefono en una ventana horaria.
        """
        attempt = self.store.get_attempt(attempt_id)
        if attempt is None:
            raise PearlAPIError(f"Intento {attempt_id} no encontrado",
                                code="not_found")

        call_id = None
        if attempt.provider_request_id:
            req = await self.client.get_call_request(attempt.provider_request_id)
            req_status = req.get("status")
            call_id = req.get("callId")
            self.store.record_provider_event(
                event_key=f"callreq:{attempt.provider_request_id}:{req_status}",
                source="reconcile",
                call_id=call_id,
                status=_REQUEST_STATUS_NAMES.get(req_status, str(req_status)),
                payload=req,
            )
            if req_status == 100:  # Error
                self.store.update_attempt(
                    attempt_id, status=AttemptStatus.FAILED,
                    error="call_request_error: " + ",".join(req.get("errors") or []),
                )
                return {
                    "attempt_id": attempt_id,
                    "status": AttemptStatus.FAILED,
                    "request_status": _REQUEST_STATUS_NAMES.get(req_status),
                }
            if req_status == 20:  # BlackListed
                self.store.update_attempt(
                    attempt_id, status=AttemptStatus.BLOCKED,
                    error="destination_blocked",
                )
                return {
                    "attempt_id": attempt_id,
                    "status": AttemptStatus.BLOCKED,
                    "request_status": "BlackListed",
                }

        if call_id is None:
            call_id = await self._find_call_by_phone(attempt.to_e164)

        if call_id:
            self.store.update_attempt(
                attempt_id,
                provider_call_id=call_id,
                status=AttemptStatus.RUNNING,
            )
            self.store.log_event(
                "reconcile_found_call", attempt_id=attempt_id,
                payload={"call_id": call_id},
            )
            return {
                "attempt_id": attempt_id,
                "status": AttemptStatus.RUNNING,
                "provider_call_id": call_id,
            }

        # No hay rastro de la llamada: seguro reintentar.
        self.store.update_attempt(attempt_id, status=AttemptStatus.FAILED,
                                  error="reconciliation_no_call_found")
        return {
            "attempt_id": attempt_id,
            "status": AttemptStatus.FAILED,
            "provider_call_id": None,
            "note": "No se encontro llamada en Pearl; el intento puede relanzarse.",
        }

    async def _find_call_by_phone(self, to_e164: str) -> str | None:
        """Busca la llamada mas reciente al numero en las ultimas horas."""
        pearl_id = self.settings.pearl_id
        if not pearl_id:
            return None
        now = datetime.now(timezone.utc)
        from_date = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            result = await self.client.search_calls(
                pearl_id, from_date, to_date, limit=50
            )
        except PearlAPIError:
            return None
        calls = result.get("results", result) if isinstance(result, dict) else result
        if not isinstance(calls, list):
            return None
        digits = "".join(c for c in to_e164 if c.isdigit())
        for call in reversed(calls):
            if not isinstance(call, dict):
                continue
            candidate = call.get("to") or call.get("phoneNumber") or ""
            cand_digits = "".join(c for c in str(candidate) if c.isdigit())
            if cand_digits and digits.endswith(cand_digits[-9:]):
                return call.get("id") or call.get("callId")
        return None

    async def get_call(self, call_id: str) -> NormalizedResult:
        payload = await self.client.get_call(call_id)
        return normalize_call(call_id, payload)

    async def sync_attempt(self, attempt_id: int) -> dict[str, Any]:
        """Actualiza el intento con el estado real de la llamada en Pearl."""
        attempt = self.store.get_attempt(attempt_id)
        if attempt is None:
            raise PearlAPIError(f"Intento {attempt_id} no encontrado",
                                code="not_found")

        call_id = attempt.provider_call_id
        if call_id is None and attempt.provider_request_id:
            rec = await self.reconcile(attempt_id)
            call_id = rec.get("provider_call_id")
            if not call_id:
                return rec

        if call_id is None:
            return {
                "attempt_id": attempt_id,
                "status": attempt.status,
                "error": {
                    "code": "missing_call_id",
                    "message": "El intento aun no tiene call_id en Pearl.",
                    "retryable": True,
                },
            }

        result = await self.get_call(call_id)
        outcome = result.call_outcome
        event_key = f"poll:{call_id}:{outcome.status}"
        self.store.record_provider_event(
            event_key=event_key,
            source="poll",
            call_id=call_id,
            status=outcome.status_name,
            payload={
                "status": outcome.status,
                "duration": outcome.duration_s,
                "summary": result.summary,
            },
        )

        if outcome.is_final:
            new_status = (
                AttemptStatus.COMPLETED
                if outcome.status == 4
                else AttemptStatus.FAILED
            )
            self.store.update_attempt(
                attempt_id,
                status=new_status,
                last_result_json=result.model_dump(mode="json"),
            )
            self.store.log_event(
                "attempt_final",
                attempt_id=attempt_id,
                payload={
                    "call_id": call_id,
                    "call_status": outcome.status_name,
                    "duration_s": outcome.duration_s,
                },
            )
        else:
            self.store.update_attempt(attempt_id, status=AttemptStatus.RUNNING)

        return {
            "attempt_id": attempt_id,
            "status": new_status if outcome.is_final else AttemptStatus.RUNNING,
            "call_outcome": outcome.model_dump(mode="json"),
            "summary": result.summary,
            "collected": result.collected,
            "recording_url": result.recording_url,
        }

    async def list_recent_calls(self, days: int = 1) -> list[dict[str, Any]]:
        pearl_id = self.settings.pearl_id
        now = datetime.now(timezone.utc)
        from_date = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = await self.client.search_calls(pearl_id, from_date, to_date)
        calls = result.get("results", result) if isinstance(result, dict) else result
        return calls if isinstance(calls, list) else []
