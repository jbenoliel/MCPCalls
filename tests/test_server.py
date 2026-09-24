import json

import pytest
from mcp import Client

from mcpcalls import mcp
from mcpcalls.config import get_settings


def _payload(result):
    """El SDK devuelve structuredContent para salidas dict; texto si no."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_list_tools():
    async with Client(mcp) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
    assert {
        "pearl_ping",
        "pearl_place_call",
        "pearl_sync_attempt",
        "pearl_reconcile",
        "pearl_list_calls",
    } <= tools


@pytest.mark.asyncio
async def test_pearl_ping_without_credentials_returns_error(monkeypatch):
    """Sin credenciales la tool devuelve error estructurado, no excepcion."""
    monkeypatch.delenv("PEARL_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("PEARL_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    async with Client(mcp) as client:
        result = await client.call_tool("pearl_ping", {})
    payload = _payload(result)
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "missing_credentials"
