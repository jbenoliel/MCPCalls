"""Trazabilidad entre la especificacion y el codigo.

Un test por cada requisito funcional (F01-F12) y por cada escenario de
aceptacion (A01-A10) de `MCPearl_Especificaciones_Desarrollo.docx`. La salida
de pytest es la matriz de cumplimiento:

    pytest tests/test_spec_compliance.py -v

Cada requisito esta en uno de cuatro estados:

    OK        implementado y con evidencia; el test pasa.
    PARCIAL   hay parte construida; el test comprueba esa parte.
    PENDIENTE no construido todavia; el test sale xfail. Deuda conocida.
    BLOCKED   imposible con el proveedor actual; xfail permanente, con una
              entrada en docs/spec_deviations.md que explica por que.

Un xfail NO es un fallo: es un hueco declarado. Lo que si es un fallo es que
un requisito desaparezca de esta tabla, o que la evidencia que dice tener ya
no exista. De eso se encargan los dos ultimos tests del fichero.

Por que la evidencia es "el test X existe" y no una reimplementacion: esta
suite no vuelve a probar lo que ya prueban los tests unitarios. Su trabajo es
enlazar requisito con prueba, y avisar si el enlace se rompe.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from mcpcalls.pearl.context import ContextPackage, ContextFact

TESTS_DIR = Path(__file__).parent

OK = "OK"
PARCIAL = "PARCIAL"
PENDIENTE = "PENDIENTE"
BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class Req:
    id: str
    titulo: str
    fase: str
    estado: str
    nota: str = ""
    evidencia: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# La tabla. Refleja el estado REAL, no el deseado. Cambiarla sin cambiar el
# codigo es mentir en el informe.
# ---------------------------------------------------------------------------
REQUISITOS: tuple[Req, ...] = (
    Req("F01", "Encargo abierto", "1", PENDIENTE,
        "Necesita el modelo de gestion. Ademas no es verificable por test: "
        "se mide con las 18 pruebas de generalizacion de la seccion 10."),
    Req("F02", "Preparacion del contexto", "0", PARCIAL,
        "Hechos, hipotesis y allowed_to_share implementados. extra_variables "
        "se salta el filtro: ver test_f02_extra_variables_deberia_filtrarse.",
        ("test_adapter.py::test_place_call_submitted",)),
    Req("F03", "Llamada contextual", "0", PARCIAL,
        "callData transporta objetivo, limites y preguntas pendientes. "
        "La vigencia del contexto entre intentos llega con la gestion.",
        ("test_adapter.py::test_place_call_submitted",)),
    Req("F04", "Resultado util", "0", PARCIAL,
        "call_outcome separado del avance del objetivo. objective_progress "
        "y commitments los calcula el servicio de gestiones (Fase 1).",
        ("test_normalize.py::test_normalize_completed_call",
         "test_normalize.py::test_normalize_in_progress")),
    Req("F05", "Deteccion de pendientes", "1", PENDIENTE,
        "Extraccion de plazo, responsable, evidencia y motivo."),
    Req("F06", "Propuesta de seguimiento", "1", PENDIENTE),
    Req("F07", "Programacion duradera", "1", PENDIENTE,
        "No hay planificador persistente todavia."),
    Req("F08", "Actualizacion de la gestion", "1", PENDIENTE),
    Req("F09", "Control del usuario", "1", BLOCKED,
        "Cancelar solo puede impedir llamadas futuras. Una llamada en curso "
        "no se puede detener: ver docs/spec_deviations.md D01."),
    Req("F10", "Avisos y consulta", "1", PENDIENTE),
    Req("F11", "Delegacion continuada", "2", PENDIENTE,
        "Fase 2 por diseno."),
    Req("F12", "Decisiones durante llamada", "2", PENDIENTE,
        "La salida segura ante decision nueva se exige desde el inicio; "
        "la respuesta en directo es Fase 2."),

    Req("A01", "Taller dice la semana que viene", "1", PENDIENTE),
    Req("A02", "Aceptacion y chat cerrado", "1", PENDIENTE,
        "Requiere el planificador persistente de F07."),
    Req("A03", "Segunda llamada al taller", "1", PENDIENTE),
    Req("A04", "Nueva demora", "1", PENDIENTE),
    Req("A05", "Cancelacion o cambio de alcance", "1", BLOCKED,
        "La primera mitad (impedir nuevas llamadas) es exigible y esta "
        "pendiente. La segunda (detener la que ya empezo) es imposible: "
        "ver docs/spec_deviations.md D01."),
    Req("A06", "Evento o peticion duplicada", "0", PARCIAL,
        "Dedup por idempotency_key, dedup de eventos y reconciliacion ante "
        "inicio incierto ya cubiertos en el adaptador. Falta el cargo, que "
        "no existe todavia.",
        ("test_adapter.py::test_place_call_dedup",
         "test_adapter.py::test_place_call_timeout_reconciliation_required",
         "test_adapter.py::test_place_call_200_without_id_is_uncertain",
         "test_adapter.py::test_reconcile_via_call_request",
         "test_store.py::test_attempt_dedup_by_idempotency_key",
         "test_store.py::test_provider_event_dedup",
         "test_webhook.py::test_accepts_and_dedups")),
    Req("A07", "Saldo o vigencia agotados", "1", PENDIENTE,
        "No hay libro de cobros."),
    Req("A08", "Cambio horario y fecha relativa", "0", PARCIAL,
        "La ventana de llamada y el cruce de medianoche estan cubiertos. "
        "La resolucion de expresiones relativas es de la gestion (Fase 1).",
        ("test_adapter.py::test_parse_calling_window",
         "test_adapter.py::test_window_overnight",
         "test_adapter.py::test_place_call_outside_window")),
    Req("A09", "Decision no autorizada", "1", PENDIENTE,
        "Necesita el modelo de mandato."),
    Req("A10", "Objetivo ya cumplido", "1", PENDIENTE),
)

POR_ID = {r.id: r for r in REQUISITOS}


# ---------------------------------------------------------------------------
# Utilidades de evidencia
# ---------------------------------------------------------------------------
def _tests_definidos(fichero: str) -> set[str]:
    """Nombres de funciones test_* definidas en un fichero de tests."""
    ruta = TESTS_DIR / fichero
    if not ruta.exists():
        return set()
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    return {
        n.name
        for n in ast.walk(arbol)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith("test_")
    }


def _comprobar_evidencia(req: Req) -> None:
    """La evidencia declarada tiene que seguir existiendo."""
    assert req.evidencia, f"{req.id} dice estar en estado {req.estado} sin evidencia"
    for ref in req.evidencia:
        fichero, _, nombre = ref.partition("::")
        disponibles = _tests_definidos(fichero)
        assert disponibles, f"{req.id}: {fichero} no existe o no tiene tests"
        assert nombre in disponibles, (
            f"{req.id}: la evidencia {ref} ya no existe. O el test se renombro "
            f"o el requisito dejo de estar cubierto; en ambos casos hay que "
            f"actualizar la tabla."
        )


# ---------------------------------------------------------------------------
# Un test por requisito
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("req", REQUISITOS, ids=lambda r: f"{r.id}-{r.titulo}")
def test_requisito(req: Req) -> None:
    if req.estado == BLOCKED:
        pytest.xfail(f"BLOCKED — {req.nota}")
    if req.estado == PENDIENTE:
        pytest.xfail(f"PENDIENTE (fase {req.fase}) — {req.nota or req.titulo}")
    _comprobar_evidencia(req)


# ---------------------------------------------------------------------------
# Comprobaciones de comportamiento propias de esta suite
# ---------------------------------------------------------------------------
def test_f02_solo_viaja_lo_permitido() -> None:
    """F02: un hecho no autorizado no puede salir en callData."""
    ctx = ContextPackage(
        objective="Preguntar por la reparacion",
        facts={
            "matricula": ContextFact(value="1234ABC", source="usuario"),
            "dni": ContextFact(value="00000000X", source="usuario"),
        },
        hypotheses={"urgencia": "probablemente corre prisa"},
        allowed_to_share=["matricula", "urgencia"],
    )
    data = ctx.to_call_data()

    assert data["fact_matricula"] == "1234ABC"
    assert "fact_dni" not in data, "un hecho fuera de allowed_to_share no debe viajar"
    assert "00000000X" not in " ".join(data.values()), "el DNI se ha filtrado"
    # Las hipotesis viajan etiquetadas, para que el flow no las de por hechas.
    assert "hypothesis_urgencia" in data
    assert "fact_urgencia" not in data


@pytest.mark.xfail(
    strict=True,
    reason="F02: extra_variables entra en callData sin pasar por "
           "allowed_to_share. Al arreglarlo, quitar este marcador.",
)
def test_f02_extra_variables_deberia_filtrarse() -> None:
    """F02 / seccion 9: 'compartir solo datos permitidos'.

    extra_variables es hoy un canal sin puerta: cualquier clave que se meta
    ahi llega al proveedor aunque allowed_to_share este vacio.
    """
    ctx = ContextPackage(
        objective="x",
        allowed_to_share=[],
        extra_variables={"email_cliente": "jacques@distrisave.com"},
    )
    data = ctx.to_call_data()
    assert "email_cliente" not in data


# ---------------------------------------------------------------------------
# La tabla no puede desincronizarse de la spec
# ---------------------------------------------------------------------------
def test_la_tabla_cubre_todos_los_ids_de_la_spec() -> None:
    esperados = {f"F{i:02d}" for i in range(1, 13)} | {f"A{i:02d}" for i in range(1, 11)}
    presentes = set(POR_ID)
    assert presentes == esperados, (
        f"faltan: {sorted(esperados - presentes)} / "
        f"sobran: {sorted(presentes - esperados)}"
    )


def test_los_bloqueados_estan_documentados() -> None:
    """Un BLOCKED sin entrada en spec_deviations.md es una excusa, no un hecho."""
    desviaciones = (TESTS_DIR.parent / "docs" / "spec_deviations.md")
    assert desviaciones.exists(), "falta docs/spec_deviations.md"
    texto = desviaciones.read_text(encoding="utf-8")
    for req in REQUISITOS:
        if req.estado == BLOCKED:
            assert "spec_deviations.md" in req.nota or "D0" in req.nota, (
                f"{req.id} esta BLOCKED pero su nota no referencia una desviacion"
            )
            assert req.id in texto, (
                f"{req.id} esta BLOCKED pero no aparece en docs/spec_deviations.md"
            )
