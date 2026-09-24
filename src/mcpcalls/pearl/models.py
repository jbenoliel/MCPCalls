"""Modelos del adaptador NLPearl.

Codigos de estado observados en produccion (tuotempo):
- Llamada: 3 y 8 son estados NO finales (en curso / en cola). Historicamente
  Pearl cambio el codigo de en-curso y se perdieron ~2.500 duraciones.
  Finales: 4 Completed, 5 Busy, 6 Failed, 7 NoAnswer.
- Outbound: 1 Running, 2 Paused, 3 Suspended, 10 TemporaryMaintenance.
"""

from datetime import datetime
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field


class CallStatus(IntEnum):
    """Estado tecnico de una llamada en NLPearl."""

    IN_PROGRESS = 3
    COMPLETED = 4
    BUSY = 5
    FAILED = 6
    NO_ANSWER = 7
    QUEUED = 8


FINAL_CALL_STATUSES: frozenset[int] = frozenset(
    {CallStatus.COMPLETED, CallStatus.BUSY, CallStatus.FAILED, CallStatus.NO_ANSWER}
)
NON_FINAL_CALL_STATUSES: frozenset[int] = frozenset(
    {CallStatus.IN_PROGRESS, CallStatus.QUEUED}
)


def is_final_call_status(status: int | None) -> bool:
    return status is not None and int(status) in FINAL_CALL_STATUSES


class OutboundStatus(IntEnum):
    """Estado de una campana/Pearl outbound."""

    RUNNING = 1
    PAUSED = 2
    SUSPENDED = 3
    TEMPORARY_MAINTENANCE = 10


class CallOutcome(BaseModel):
    """Resultado tecnico de la llamada, separado del avance del objetivo."""

    status: int | None = None
    status_name: str = ""
    is_final: bool = False
    duration_s: int = 0
    outcome: str = ""


class TranscriptTurn(BaseModel):
    """Un turno de la transcripcion. role: 2 = agente, 3 = interlocutor."""

    role: int | None = None
    content: str = ""


class NormalizedResult(BaseModel):
    """Resultado normalizado de una llamada Pearl.

    call_outcome es el resultado tecnico. El avance del objetivo
    (objective_progress del spec) lo calcula el servicio de gestiones
    en una fase posterior, no el adaptador.
    """

    provider_call_id: str
    call_outcome: CallOutcome = Field(default_factory=CallOutcome)
    summary: str = ""
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    collected: dict[str, Any] = Field(default_factory=dict)
    recording_url: str = ""
    credits: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class AttemptStatus:
    """Estados internos de un intento de llamada (call_attempts)."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class Attempt(BaseModel):
    """Intento de llamada persistido por el adaptador."""

    id: int | None = None
    idempotency_key: str
    to_e164: str
    outbound_id: str
    status: str = AttemptStatus.PENDING
    provider_call_id: str | None = None
    provider_request_id: str | None = None
    context_version: int = 1
    error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
