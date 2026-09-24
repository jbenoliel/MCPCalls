"""Normaliza payloads crudos de NLPearl a NormalizedResult.

Campos observados en produccion (tuotempo):
- status: int (3/8 en curso, 4 Completed, 5 Busy, 6 Failed, 7 NoAnswer)
- duration: segundos (0 mientras no es final)
- transcript: lista de turnos [{role, content}] (NO 'transcription')
- summary: resumen post-call
- collectedInfo / collected_info: variables PostCall recogidas por el flow
- recording / recordingUrl: URL de audio
- outcome: resultado textual opcional
"""

import logging
from typing import Any

from mcpcalls.pearl.models import (
    CallStatus,
    NormalizedResult,
    TranscriptTurn,
    is_final_call_status,
)

logger = logging.getLogger(__name__)

_STATUS_NAMES = {
    CallStatus.IN_PROGRESS: "InProgress",
    CallStatus.COMPLETED: "Completed",
    CallStatus.BUSY: "Busy",
    CallStatus.FAILED: "Failed",
    CallStatus.NO_ANSWER: "NoAnswer",
    CallStatus.QUEUED: "Queued",
}


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if payload.get(key) is not None:
            return payload[key]
    return None


def _parse_transcript(raw: Any) -> list[TranscriptTurn]:
    turns: list[TranscriptTurn] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                turns.append(
                    TranscriptTurn(
                        role=item.get("role"),
                        content=str(item.get("content", "")),
                    )
                )
            elif isinstance(item, str):
                turns.append(TranscriptTurn(content=item))
    elif isinstance(raw, str) and raw:
        turns.append(TranscriptTurn(content=raw))
    return turns


def normalize_call(call_id: str, payload: dict[str, Any]) -> NormalizedResult:
    """Payload de GET /v2/Call/{id} (o de search calls) -> NormalizedResult."""
    status_raw = payload.get("status")
    status: int | None = None
    if status_raw is not None:
        try:
            status = int(status_raw)
        except (TypeError, ValueError):
            logger.warning("Status de llamada no numerico: %r", status_raw)

    if status is not None:
        try:
            status_name = _STATUS_NAMES[CallStatus(status)]
        except ValueError:
            status_name = f"Unknown({status})"
    else:
        status_name = "Unknown"

    transcript_raw = _first(payload, "transcript", "transcription")
    collected = _first(payload, "collectedInfo", "collected_info") or {}
    if not isinstance(collected, dict):
        collected = {"value": collected}

    result = NormalizedResult(
        provider_call_id=call_id,
        summary=str(_first(payload, "summary", "callSummary") or ""),
        transcript=_parse_transcript(transcript_raw),
        collected=collected,
        recording_url=str(
            _first(payload, "recording", "recordingUrl") or ""
        ),
        credits=_first(payload, "credits", "cost", "totalCredits"),
        raw=payload,
    )
    result.call_outcome.status = status
    result.call_outcome.status_name = status_name
    result.call_outcome.is_final = is_final_call_status(status)
    result.call_outcome.duration_s = int(payload.get("duration") or 0)
    result.call_outcome.outcome = str(payload.get("outcome") or "")
    return result
