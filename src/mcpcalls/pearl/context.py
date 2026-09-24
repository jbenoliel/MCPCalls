"""Paquete de contexto que se envia a Pearl en callData.

Solo se comparten los datos marcados como permitidos (spec F02 / apartado 9):
el interlocutor y el proveedor reciben exclusivamente lo que el encargo
autoriza compartir. callData es un dict[str, str] de variables que el flow
del Pearl puede referenciar.
"""

from typing import Any

from pydantic import BaseModel, Field

# Clave reservada que transporta nuestro marcador de idempotencia.
ATTEMPT_MARKER_KEY = "mcpearl_attempt_id"


class ContextFact(BaseModel):
    """Un hecho con procedencia. Solo viaja si allowed_to_share lo incluye."""

    value: str
    source: str = ""
    date: str = ""


class ContextPackage(BaseModel):
    """Contexto de una llamada, versionado.

    facts: hechos confirmados con fuente y fecha.
    hypotheses: suposiciones (nunca se presentan como hechos).
    constraints: limites de la llamada (que NO decir/hacer).
    pending_questions: preguntas que el agente debe resolver.
    allowed_to_share: lista de claves compartibles; los hechos cuyo nombre
        no este en esta lista (o con allow_all False) no salen de MCPCalls.
    """

    objective: str = ""
    facts: dict[str, ContextFact] = Field(default_factory=dict)
    hypotheses: dict[str, str] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)
    allowed_to_share: list[str] = Field(default_factory=list)
    extra_variables: dict[str, str] = Field(default_factory=dict)

    def to_call_data(self, attempt_marker: str = "") -> dict[str, str]:
        """Serializa a callData para make_call.

        Las hipotesis se etiquetan explicitamente para que el flow no las
        presente como hechos al interlocutor.
        """
        data: dict[str, str] = {
            "objective": self.objective,
        }
        shared = set(self.allowed_to_share)
        for name, fact in self.facts.items():
            if name in shared:
                data[f"fact_{name}"] = fact.value
        for name, hypothesis in self.hypotheses.items():
            if name in shared:
                data[f"hypothesis_{name}"] = hypothesis
        if self.constraints:
            data["constraints"] = " | ".join(self.constraints)
        if self.pending_questions:
            data["pending_questions"] = " | ".join(self.pending_questions)
        for key, value in self.extra_variables.items():
            if key not in data:
                data[key] = value
        if attempt_marker:
            data[ATTEMPT_MARKER_KEY] = attempt_marker
        return data

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "ContextPackage":
        facts = {
            name: (
                ContextFact(value=v)
                if not isinstance(v, dict)
                else ContextFact(**v)
            )
            for name, v in raw.get("facts", {}).items()
        }
        return cls(
            objective=raw.get("objective", ""),
            facts=facts,
            hypotheses=raw.get("hypotheses", {}),
            constraints=raw.get("constraints", []),
            pending_questions=raw.get("pending_questions", []),
            allowed_to_share=raw.get("allowed_to_share", []),
            extra_variables=raw.get("extra_variables", {}),
        )
