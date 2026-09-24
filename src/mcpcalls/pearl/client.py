"""Cliente HTTP async para la API de NLPearl.

Auth: Authorization: Bearer {account_id}:{secret_key}
Politicas heredadas de tuotempo (produccion):
- 429 frecuente: backoff exponencial 2s/4s/8s, maximo 3 reintentos.
- Pacing ~1s entre peticiones y maximo 2 simultaneas.
- Timeouts: 10s lecturas, 30s escrituras.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from mcpcalls.config import Settings, get_settings

logger = logging.getLogger(__name__)


class PearlAPIError(Exception):
    """Error estructurado de la API de NLPearl.

    code usa los codigos del contrato MCP del spec cuando aplica
    (provider_unavailable, execution_uncertain, ...).
    """

    def __init__(
        self,
        message: str,
        code: str = "provider_error",
        status_code: int | None = None,
        retryable: bool = False,
        response: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.response = response or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "status_code": self.status_code,
        }


class PearlClient:
    """Cliente async de bajo nivel para api.nlpearl.ai."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.settings = settings or get_settings()
        if not self.settings.pearl_account_id or not self.settings.pearl_secret_key:
            raise PearlAPIError(
                "Credenciales NLPearl no configuradas "
                "(PEARL_ACCOUNT_ID / PEARL_SECRET_KEY)",
                code="missing_credentials",
            )
        self._base = self.settings.pearl_api_base.rstrip("/")
        self._headers = {
            "Authorization": (
                f"Bearer {self.settings.pearl_account_id}"
                f":{self.settings.pearl_secret_key}"
            ),
            "Content-Type": "application/json",
        }
        self._semaphore = asyncio.Semaphore(self.settings.pearl_max_concurrent)
        self._pacing = max(0.0, self.settings.pearl_request_pacing_s)
        self._max_retries = self.settings.pearl_max_retries
        self._last_request_at = 0.0
        self._http = httpx.AsyncClient(
            headers=self._headers,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "PearlClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _pace(self) -> None:
        """Espacio minimo entre peticiones para evitar 429."""
        if self._pacing <= 0:
            return
        wait = self._pacing - (time.monotonic() - self._last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)

    async def _request(
        self,
        method: str,
        path: str,
        timeout: float,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base}{path}"
        attempt = 0
        while True:
            async with self._semaphore:
                await self._pace()
                try:
                    response = await self._http.request(
                        method, url, json=json_body, timeout=timeout
                    )
                    self._last_request_at = time.monotonic()
                except httpx.TimeoutException as e:
                    raise PearlAPIError(
                        f"Timeout en {method} {path}: {e}",
                        code="provider_unavailable",
                        retryable=True,
                    ) from e
                except httpx.HTTPError as e:
                    raise PearlAPIError(
                        f"Error de conexion en {method} {path}: {e}",
                        code="provider_unavailable",
                        retryable=True,
                    ) from e

            if response.status_code == 429 and attempt < self._max_retries:
                wait_s = (2**attempt) * 2.0
                logger.warning(
                    "Rate limit 429 en %s %s, reintento %s en %.0fs",
                    method, path, attempt + 1, wait_s,
                )
                await asyncio.sleep(wait_s)
                attempt += 1
                continue

            break

        try:
            data = response.json()
        except ValueError:
            data = {"raw_response": response.text}

        if response.status_code >= 500:
            raise PearlAPIError(
                f"Error {response.status_code} de Pearl en {method} {path}",
                code="provider_unavailable",
                status_code=response.status_code,
                retryable=True,
                response=data if isinstance(data, dict) else {},
            )
        if response.status_code >= 400:
            raise PearlAPIError(
                f"Error {response.status_code} de Pearl en {method} {path}: "
                f"{response.text[:300]}",
                code="provider_error",
                status_code=response.status_code,
                retryable=False,
                response=data if isinstance(data, dict) else {},
            )
        return data

    # ---------- API v1: outbounds y make_call ----------

    async def list_outbounds(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/Outbound", timeout=10)

    async def get_outbound(self, outbound_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/Outbound/{outbound_id}", timeout=10)

    async def make_call(
        self, outbound_id: str, to: str, call_data: dict[str, str]
    ) -> dict[str, Any]:
        """Inicia una llamada inmediata (v1).

        Devuelve {id, from, to, queuePosition}: 'id' es el Request ID de la
        peticion (ver get_call_request), NO el call_id definitivo.
        """
        payload = {"to": to, "callData": call_data}
        return await self._request(
            "POST", f"/v1/Outbound/{outbound_id}/Call", timeout=30, json_body=payload
        )

    async def get_call_request(self, request_id: str) -> dict[str, Any]:
        """Estado de una peticion API (reconciliacion).

        status: 1 InCallQueue, 2 OnCall, 10 Completed, 20 BlackListed, 100 Error.
        Incluye callId cuando la llamada ya existe.
        """
        return await self._request(
            "GET", f"/v1/Outbound/CallRequest/{request_id}", timeout=10
        )

    async def search_calls_v1(
        self,
        outbound_id: str,
        from_date: str,
        to_date: str,
        skip: int = 0,
        limit: int = 100,
    ) -> Any:
        payload = {
            "fromDate": from_date,
            "toDate": to_date,
            "skip": skip,
            "limit": limit,
        }
        return await self._request(
            "POST",
            f"/v1/Outbound/{outbound_id}/Calls",
            timeout=60,
            json_body=payload,
        )

    # ---------- API v2: Pearls y llamadas ----------

    async def list_pearls(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/v2/Pearl", timeout=10)

    async def get_pearl(self, pearl_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v2/Pearl/{pearl_id}", timeout=10)

    async def set_pearl_active(self, pearl_id: str, is_active: bool) -> Any:
        return await self._request(
            "PUT",
            f"/v2/Pearl/{pearl_id}/Active",
            timeout=10,
            json_body={"isActive": is_active},
        )

    async def get_call(self, call_id: str) -> dict[str, Any]:
        """Detalle completo de una llamada (v2): status, duration, transcript,
        summary, collectedInfo, recording."""
        return await self._request("GET", f"/v2/Call/{call_id}", timeout=10)

    async def search_calls(
        self,
        pearl_id: str,
        from_date: str,
        to_date: str,
        skip: int = 0,
        limit: int = 100,
    ) -> Any:
        payload = {
            "fromDate": from_date,
            "toDate": to_date,
            "skip": skip,
            "limit": limit,
        }
        return await self._request(
            "POST", f"/v2/Pearl/{pearl_id}/Calls", timeout=60, json_body=payload
        )
