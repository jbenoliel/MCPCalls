import httpx
import pytest

from mcpcalls.pearl.adapter import PearlAdapter, parse_calling_window
from mcpcalls.pearl.client import PearlClient
from mcpcalls.pearl.context import ContextPackage
from mcpcalls.pearl.models import AttemptStatus


def _adapter(settings, store, handler) -> PearlAdapter:
    client = PearlClient(settings, transport=httpx.MockTransport(handler))
    adapter = PearlAdapter(settings, client=client, store=store)
    adapter._owns_client = True
    return adapter


def _ctx() -> ContextPackage:
    return ContextPackage(
        objective="Preguntar por el coche",
        extra_variables={"firstName": "Juan"},
    )


async def test_place_call_submitted(settings, store):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": "req-1", "queuePosition": 0}
        )

    adapter = _adapter(settings, store, handler)
    result = await adapter.place_call("+34600111222", _ctx(), action_id="a1")
    assert result["status"] == AttemptStatus.SUBMITTED
    assert result["provider_request_id"] == "req-1"
    await adapter.aclose()


async def test_place_call_dedup(settings, store):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"id": "req-1"})

    adapter = _adapter(settings, store, handler)
    first = await adapter.place_call("+34600111222", _ctx(), action_id="a1")
    second = await adapter.place_call("+34600111222", _ctx(), action_id="a1")
    assert second.get("deduplicated") is True
    assert first["attempt_id"] == second["attempt_id"]
    assert len(calls) == 1  # una sola llamada a la API
    await adapter.aclose()


async def test_place_call_outside_window(settings, store):
    # ventana degenerada: nunca se esta dentro, sea la hora que sea
    settings.mcpcalls_calling_window = "00:00-00:00 Europe/Madrid"
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"id": "req-1"})

    adapter = _adapter(settings, store, handler)
    result = await adapter.place_call("+34600111222", _ctx(), action_id="a1")
    assert result["status"] == AttemptStatus.BLOCKED
    assert len(calls) == 0
    await adapter.aclose()


async def test_place_call_timeout_reconciliation_required(settings, store):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("t", request=request)

    adapter = _adapter(settings, store, handler)
    result = await adapter.place_call("+34600111222", _ctx(), action_id="a1")
    assert result["status"] == AttemptStatus.RECONCILIATION_REQUIRED

    # un segundo intento no relanza la llamada: exige reconciliar primero
    second = await adapter.place_call("+34600111222", _ctx(), action_id="a1")
    assert second["status"] == AttemptStatus.RECONCILIATION_REQUIRED
    await adapter.aclose()


async def test_place_call_200_without_id_is_uncertain(settings, store):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"queuePosition": 3})

    adapter = _adapter(settings, store, handler)
    result = await adapter.place_call("+34600111222", _ctx(), action_id="a1")
    assert result["status"] == AttemptStatus.RECONCILIATION_REQUIRED
    await adapter.aclose()


async def test_reconcile_via_call_request(settings, store):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/CallRequest/" in url:
            return httpx.Response(
                200, json={"id": "req-1", "status": 2, "callId": "call-9"}
            )
        return httpx.Response(200, json={"id": "req-1", "queuePosition": 0})

    adapter = _adapter(settings, store, handler)
    placed = await adapter.place_call("+34600111222", _ctx(), action_id="a1")
    rec = await adapter.reconcile(placed["attempt_id"])
    assert rec["provider_call_id"] == "call-9"
    assert rec["status"] == AttemptStatus.RUNNING
    await adapter.aclose()


async def test_reconcile_request_error(settings, store):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/CallRequest/" in url:
            return httpx.Response(
                200, json={"id": "req-1", "status": 100, "errors": ["boom"]}
            )
        return httpx.Response(200, json={"id": "req-1"})

    adapter = _adapter(settings, store, handler)
    placed = await adapter.place_call("+34600111222", _ctx(), action_id="a1")
    rec = await adapter.reconcile(placed["attempt_id"])
    assert rec["status"] == AttemptStatus.FAILED
    await adapter.aclose()


async def test_sync_attempt_to_final(settings, store):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/CallRequest/" in url:
            return httpx.Response(
                200, json={"status": 2, "callId": "call-9"}
            )
        if "/v2/Call/" in url:
            return httpx.Response(
                200,
                json={
                    "status": 4,
                    "duration": 42,
                    "summary": "todo bien",
                    "collectedInfo": {"plazo": "lunes"},
                },
            )
        return httpx.Response(200, json={"id": "req-1"})

    adapter = _adapter(settings, store, handler)
    placed = await adapter.place_call("+34600111222", _ctx(), action_id="a1")
    synced = await adapter.sync_attempt(placed["attempt_id"])
    assert synced["status"] == AttemptStatus.COMPLETED
    assert synced["call_outcome"]["duration_s"] == 42
    assert synced["collected"]["plazo"] == "lunes"
    await adapter.aclose()


def test_parse_calling_window():
    start, end, tz = parse_calling_window("09:00-21:00 Europe/Madrid")
    assert start == "09:00"
    assert end == "21:00"
    assert str(tz) == "Europe/Madrid"


def test_window_overnight(settings, store):
    settings.mcpcalls_calling_window = "22:00-06:00 Europe/Madrid"
    adapter = PearlAdapter.__new__(PearlAdapter)
    adapter.settings = settings
    # madrugada dentro, tarde fuera
    from datetime import datetime
    from zoneinfo import ZoneInfo

    inside = datetime(2026, 9, 24, 2, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    outside = datetime(2026, 9, 24, 15, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    assert adapter.within_calling_window(inside) is True
    assert adapter.within_calling_window(outside) is False
