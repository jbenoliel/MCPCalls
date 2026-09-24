import httpx
import pytest

from mcpcalls.pearl.client import PearlAPIError, PearlClient


def _client(settings, handler):
    return PearlClient(settings, transport=httpx.MockTransport(handler))


async def test_auth_header(settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[{"id": "ob1"}])

    async with _client(settings, handler) as client:
        result = await client.list_outbounds()
    assert result == [{"id": "ob1"}]
    assert seen["auth"] == "Bearer acc-test:secret-test"


async def test_make_call_payload_and_result(settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(
            200, json={"id": "req-1", "to": "+34600000000", "queuePosition": 0}
        )

    async with _client(settings, handler) as client:
        result = await client.make_call(
            "outbound-test", "+34600000000", {"objective": "hola"}
        )
    assert "/v1/Outbound/outbound-test/Call" in seen["url"]
    assert '"to": "+34600000000"' in seen["body"].replace("'", '"') or \
        '"to":"+34600000000"' in seen["body"].replace(" ", "")
    assert result["id"] == "req-1"


async def test_retry_on_429(settings):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": "rate limit"})
        return httpx.Response(200, json={"status": 1})

    async with _client(settings, handler) as client:
        result = await client.get_outbound("ob1")
    assert result == {"status": 1}
    assert len(calls) == 3


async def test_429_exhausted_raises(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limit"})

    async with _client(settings, handler) as client:
        with pytest.raises(PearlAPIError) as exc_info:
            await client.get_outbound("ob1")
    assert exc_info.value.status_code == 429


async def test_timeout_maps_to_retryable(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    async with _client(settings, handler) as client:
        with pytest.raises(PearlAPIError) as exc_info:
            await client.get_outbound("ob1")
    assert exc_info.value.code == "provider_unavailable"
    assert exc_info.value.retryable is True


async def test_500_retryable_400_not(settings):
    def handler_500(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    async with _client(settings, handler_500) as client:
        with pytest.raises(PearlAPIError) as exc_info:
            await client.get_outbound("ob1")
    assert exc_info.value.retryable is True

    def handler_400(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"title": "bad request"})

    async with _client(settings, handler_400) as client:
        with pytest.raises(PearlAPIError) as exc_info:
            await client.get_outbound("ob1")
    assert exc_info.value.retryable is False
    assert exc_info.value.status_code == 400


async def test_get_call_request_path(settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200, json={"id": "req-1", "status": 2, "callId": "call-9"}
        )

    async with _client(settings, handler) as client:
        result = await client.get_call_request("req-1")
    assert "/v1/Outbound/CallRequest/req-1" in seen["url"]
    assert result["callId"] == "call-9"


async def test_missing_credentials(tmp_path):
    from mcpcalls.config import Settings

    s = Settings(
        pearl_account_id="",
        pearl_secret_key="",
        mcpcalls_db_url=f"sqlite:///{tmp_path}/x.db",
    )
    with pytest.raises(PearlAPIError) as exc_info:
        PearlClient(s)
    assert exc_info.value.code == "missing_credentials"
