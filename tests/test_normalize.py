from mcpcalls.pearl.models import is_final_call_status
from mcpcalls.pearl.normalize import normalize_call


def test_final_statuses():
    for s in (4, 5, 6, 7):
        assert is_final_call_status(s)
    for s in (3, 8, None, 0):
        assert not is_final_call_status(s)


def test_normalize_completed_call():
    payload = {
        "status": 4,
        "duration": 87,
        "summary": "El taller confirma entrega la semana que viene",
        "transcript": [
            {"role": 2, "content": "Buenos dias, llamo por el coche"},
            {"role": 3, "content": "Si, estara la semana que viene"},
        ],
        "collectedInfo": {"plazo_estimado": "semana que viene"},
        "recording": "https://example.com/rec.mp3",
        "credits": 0.35,
    }
    result = normalize_call("call-1", payload)
    assert result.provider_call_id == "call-1"
    assert result.call_outcome.status == 4
    assert result.call_outcome.status_name == "Completed"
    assert result.call_outcome.is_final is True
    assert result.call_outcome.duration_s == 87
    assert result.summary.startswith("El taller")
    assert len(result.transcript) == 2
    assert result.transcript[1].role == 3
    assert result.collected["plazo_estimado"] == "semana que viene"
    assert result.recording_url.endswith("rec.mp3")
    assert result.credits == 0.35


def test_normalize_in_progress():
    result = normalize_call("call-2", {"status": 3, "duration": 0})
    assert result.call_outcome.is_final is False
    assert result.call_outcome.status_name == "InProgress"


def test_normalize_queued_status_8():
    result = normalize_call("call-3", {"status": 8, "duration": 0})
    assert result.call_outcome.is_final is False


def test_normalize_unknown_status():
    result = normalize_call("call-4", {"status": 99})
    assert result.call_outcome.status_name == "Unknown(99)"
    assert result.call_outcome.is_final is False


def test_transcript_as_string_fallback():
    result = normalize_call(
        "call-5", {"status": 4, "transcription": "texto plano"}
    )
    assert result.transcript[0].content == "texto plano"
