"""Servidor MCP de MCPCalls (MCPearl, Fase 0).

Expone herramientas del adaptador NLPearl. Las respuestas siguen el formato
del contrato del spec: request_id, status y error {code, message, retryable}.
"""

import uuid

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="MCPCalls",
    instructions=(
        "Servidor MCP de MCPearl (Fase 0): operaciones sobre el adaptador "
        "NLPearl para iniciar, consultar y reconciliar llamadas."
    ),
    version="0.1.0",
)


def _response(status: str, **fields):
    return {"request_id": uuid.uuid4().hex[:12], "status": status, **fields}


def _error(exc: Exception):
    from mcpcalls.pearl.client import PearlAPIError

    if isinstance(exc, PearlAPIError):
        return _response("error", error=exc.to_dict())
    return _response(
        "error",
        error={"code": "internal_error", "message": str(exc), "retryable": False},
    )


async def _adapter():
    from mcpcalls.pearl.adapter import PearlAdapter

    return PearlAdapter()


@mcp.tool(
    description=(
        "Comprueba conexion y credenciales con NLPearl y el estado de la "
        "campana outbound dedicada."
    )
)
async def pearl_ping() -> dict:
    try:
        adapter = await _adapter()
        try:
            ping = await adapter.ping()
            outbound = await adapter.get_outbound_status()
        finally:
            await adapter.aclose()
        return _response("ok", ping=ping, outbound=outbound)
    except Exception as e:
        return _error(e)


@mcp.tool(
    description=(
        "Inicia una llamada telefonica via NLPearl al numero E.164 indicado, "
        "con objetivo y contexto en JSON. Devuelve attempt_id para seguimiento."
    )
)
async def pearl_place_call(to: str, objective: str, context_json: str = "") -> dict:
    try:
        import json as _json

        from mcpcalls.pearl.context import ContextPackage

        if context_json:
            context = ContextPackage.from_json(_json.loads(context_json))
            if objective:
                context.objective = objective
        else:
            context = ContextPackage(objective=objective)
        adapter = await _adapter()
        try:
            result = await adapter.place_call(to, context)
        finally:
            await adapter.aclose()
        return _response(result.get("status", "error"), **result)
    except Exception as e:
        return _error(e)


@mcp.tool(
    description=(
        "Sincroniza un intento con el estado real en Pearl (polling). "
        "Devuelve call_outcome, summary y variables PostCall si es final."
    )
)
async def pearl_sync_attempt(attempt_id: int) -> dict:
    try:
        adapter = await _adapter()
        try:
            result = await adapter.sync_attempt(attempt_id)
        finally:
            await adapter.aclose()
        return _response(result.get("status", "error"), **result)
    except Exception as e:
        return _error(e)


@mcp.tool(
    description=(
        "Reconcilia un intento con respuesta ambigua consultando a Pearl "
        "antes de permitir un reintento."
    )
)
async def pearl_reconcile(attempt_id: int) -> dict:
    try:
        adapter = await _adapter()
        try:
            result = await adapter.reconcile(attempt_id)
        finally:
            await adapter.aclose()
        return _response(result.get("status", "ok"), **result)
    except Exception as e:
        return _error(e)


@mcp.tool(
    description="Lista las llamadas recientes del Pearl dedicado (ultimos N dias)."
)
async def pearl_list_calls(days: int = 1) -> dict:
    try:
        adapter = await _adapter()
        try:
            calls = await adapter.list_recent_calls(days=days)
        finally:
            await adapter.aclose()
        return _response("ok", count=len(calls), calls=calls[:50])
    except Exception as e:
        return _error(e)


@mcp.resource("mcpcalls://info", description="Informacion basica del servidor.")
def info() -> str:
    return "MCPCalls: servidor MCP de MCPearl, Fase 0 (adaptador NLPearl)."


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
