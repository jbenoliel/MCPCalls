"""CLI de operacion del adaptador Pearl.

Uso: uv run python -m mcpcalls.pearl.cli <comando> [args]
Comandos: ping, outbounds, status, call, poll, reconcile, list-calls,
serve-webhook, validate.
"""

import argparse
import asyncio
import json
import logging
import sys
import time

from mcpcalls.pearl.adapter import PearlAdapter
from mcpcalls.pearl.client import PearlAPIError
from mcpcalls.pearl.context import ContextPackage

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)


def _print(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _load_context(path: str | None, objective: str) -> ContextPackage:
    if path:
        with open(path, encoding="utf-8") as f:
            return ContextPackage.from_json(json.load(f))
    return ContextPackage(
        objective=objective or "Llamada de prueba del adaptador MCPCalls",
        extra_variables={"firstName": "Prueba"},
    )


async def _run(args: argparse.Namespace) -> int:
    if args.cmd == "serve-webhook":
        import uvicorn
        from mcpcalls.pearl.webhook import create_app

        app = create_app()
        config = uvicorn.Config(app, host="0.0.0.0", port=args.port)
        await uvicorn.Server(config).serve()
        return 0

    adapter = None
    try:
        adapter = PearlAdapter()
        if args.cmd == "ping":
            _print(await adapter.ping())
        elif args.cmd == "outbounds":
            _print(await adapter.client.list_outbounds())
        elif args.cmd == "status":
            _print(await adapter.get_outbound_status())
        elif args.cmd == "call":
            context = _load_context(args.context, args.objective)
            _print(await adapter.place_call(args.to, context))
        elif args.cmd == "poll":
            _print(await adapter.sync_attempt(args.attempt_id))
        elif args.cmd == "reconcile":
            _print(await adapter.reconcile(args.attempt_id))
        elif args.cmd == "list-calls":
            _print(await adapter.list_recent_calls(days=args.days))
        elif args.cmd == "validate":
            return await _validate(adapter, args)
        else:
            print(f"Comando desconocido: {args.cmd}", file=sys.stderr)
            return 2
    except PearlAPIError as e:
        _print({"error": e.to_dict()})
        return 1
    finally:
        if adapter is not None:
            await adapter.aclose()
    return 0


async def _validate(adapter: PearlAdapter, args: argparse.Namespace) -> int:
    """Bateria de validacion de la Fase 0. --live ejecuta llamada real."""
    results: dict[str, str] = {}

    # 1. Conexion y cuenta
    try:
        ping = await adapter.ping()
        results["conexion"] = f"OK ({ping['outbounds']} outbounds)"
    except PearlAPIError as e:
        results["conexion"] = f"FALLO: {e}"
        _print(results)
        return 1

    # 2. Estado del outbound dedicado
    try:
        outbound = await adapter.get_outbound_status()
        results["outbound"] = (
            f"{outbound['status_name']} agents={outbound['total_agents']}"
        )
        if not outbound["is_active"]:
            results["aviso"] = "Outbound no esta Running: make_call puede encolar"
    except PearlAPIError as e:
        results["outbound"] = f"FALLO: {e}"

    # 3. Ventana horaria
    results["ventana_horaria"] = (
        "dentro" if adapter.within_calling_window() else "FUERA (call bloqueara)"
    )

    # 4. Llamada real (solo con --live)
    if args.live:
        if not adapter.settings.pearl_test_number:
            results["llamada_real"] = "SIN PEARL_TEST_NUMBER configurado"
        else:
            context = ContextPackage(
                objective=(
                    "Confirmar que el sistema de llamadas funciona. "
                    "Preguntar la hora que es y despedirse."
                ),
                pending_questions=["que hora es"],
                allowed_to_share=["firstName"],
                extra_variables={"firstName": "Validacion"},
            )
            placed = await adapter.place_call(
                adapter.settings.pearl_test_number,
                context,
                action_id=f"validate-{int(time.monotonic())}",
            )
            results["llamada_real"] = json.dumps(placed, default=str)
            attempt_id = placed.get("attempt_id")
            if attempt_id and placed.get("status") == "submitted":
                # 5. Polling hasta estado final (max ~3 min)
                final = None
                for _ in range(36):
                    await asyncio.sleep(5)
                    sync = await adapter.sync_attempt(attempt_id)
                    if sync.get("call_outcome", {}).get("is_final"):
                        final = sync
                        break
                if final:
                    co = final["call_outcome"]
                    results["polling"] = (
                        f"OK status={co['status_name']} "
                        f"duration={co['duration_s']}s"
                    )
                    results["extraccion_summary"] = (
                        final.get("summary") or "(vacio)"
                    )[:200]
                    results["extraccion_collected"] = json.dumps(
                        final.get("collected") or {}, ensure_ascii=False
                    )[:300]
                else:
                    results["polling"] = "TIMEOUT sin estado final"
    else:
        results["llamada_real"] = "omitida (usar --live para llamada real)"

    _print(results)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="pearl")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping")
    sub.add_parser("outbounds")
    sub.add_parser("status")

    p_call = sub.add_parser("call")
    p_call.add_argument("to")
    p_call.add_argument("--objective", default="")
    p_call.add_argument("--context", default=None,
                        help="ruta a JSON con ContextPackage")

    p_poll = sub.add_parser("poll")
    p_poll.add_argument("attempt_id", type=int)
    p_rec = sub.add_parser("reconcile")
    p_rec.add_argument("attempt_id", type=int)

    p_list = sub.add_parser("list-calls")
    p_list.add_argument("--days", type=int, default=1)

    p_wh = sub.add_parser("serve-webhook")
    p_wh.add_argument("--port", type=int, default=8090)

    p_val = sub.add_parser("validate")
    p_val.add_argument("--live", action="store_true",
                       help="ejecuta una llamada real a PEARL_TEST_NUMBER")

    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
