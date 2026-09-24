"""Tests contra la API real de NLPearl.

Desactivados por defecto: requieren .env con PEARL_ACCOUNT_ID,
PEARL_SECRET_KEY, PEARL_OUTBOUND_ID, PEARL_ID y PEARL_TEST_NUMBER.
Cada test puede generar una llamada real con coste.

Ejecutar: uv run python -m pytest -m pearl_live
"""

import asyncio
import os

import pytest

from mcpcalls.pearl.adapter import PearlAdapter
from mcpcalls.pearl.context import ContextPackage

pytestmark = pytest.mark.pearl_live

CREDENTIALS_OK = all(
    os.getenv(k)
    for k in ("PEARL_ACCOUNT_ID", "PEARL_SECRET_KEY", "PEARL_OUTBOUND_ID")
)


@pytest.fixture
async def adapter():
    a = PearlAdapter()
    yield a
    await a.aclose()


@pytest.mark.skipif(not CREDENTIALS_OK, reason="sin credenciales NLPearl")
async def test_live_ping(adapter):
    result = await adapter.ping()
    assert result["ok"] is True


@pytest.mark.skipif(not CREDENTIALS_OK, reason="sin credenciales NLPearl")
async def test_live_outbound_status(adapter):
    result = await adapter.get_outbound_status()
    assert result["status_name"]


@pytest.mark.skipif(
    not (CREDENTIALS_OK and os.getenv("PEARL_TEST_NUMBER")),
    reason="sin credenciales o numero de prueba",
)
async def test_live_call_and_poll(adapter):
    """Una llamada real corta al numero de prueba. Coste minimo."""
    context = ContextPackage(
        objective=(
            "Confirmar que el sistema funciona. Saludar, preguntar la hora "
            "y despedirse en menos de 30 segundos."
        ),
        extra_variables={"firstName": "Validacion"},
    )
    placed = await adapter.place_call(
        os.environ["PEARL_TEST_NUMBER"], context, action_id="test-live"
    )
    assert placed["status"] == "submitted", placed

    for _ in range(36):
        await asyncio.sleep(5)
        sync = await adapter.sync_attempt(placed["attempt_id"])
        if sync.get("call_outcome", {}).get("is_final"):
            break
    else:
        pytest.fail("la llamada no llego a estado final en 3 minutos")

    assert sync["call_outcome"]["status_name"]
