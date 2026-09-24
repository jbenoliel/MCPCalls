import pytest
from starlette.testclient import TestClient

from mcpcalls.pearl.models import AttemptStatus
from mcpcalls.pearl.webhook import create_app


@pytest.fixture
def app(settings, store):
    return create_app(settings, store)


def _post(client, payload, token="wh-secret"):
    return client.post(
        "/webhooks/pearl/call",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_rejects_without_token(app):
    client = TestClient(app)
    r = client.post("/webhooks/pearl/call", json={"id": "c1", "status": 3})
    assert r.status_code == 401


def test_rejects_wrong_token(app):
    client = TestClient(app)
    r = _post(client, {"id": "c1", "status": 3}, token="otro")
    assert r.status_code == 401


def test_accepts_and_dedups(app):
    client = TestClient(app)
    payload = {"id": "call-1", "status": 4, "duration": 30}
    r1 = _post(client, payload)
    r2 = _post(client, payload)
    assert r1.status_code == 200 and r1.json()["deduplicated"] is False
    assert r2.status_code == 200 and r2.json()["deduplicated"] is True


def test_token_via_query_param(app):
    client = TestClient(app)
    r = client.post(
        "/webhooks/pearl/call?token=wh-secret",
        json={"id": "c2", "status": 3},
    )
    assert r.status_code == 200


def test_out_of_order_does_not_downgrade(app, store):
    """Un evento no-final tras un final no toca el intento."""
    attempt = store.create_attempt("k1", "+34600111222", "ob1")
    store.update_attempt(
        attempt.id, provider_call_id="call-1", status=AttemptStatus.COMPLETED
    )
    client = TestClient(app)
    r = _post(client, {"id": "call-1", "status": 3})  # llega tarde
    assert r.status_code == 200
    assert store.get_attempt(attempt.id).status == AttemptStatus.COMPLETED


def test_final_event_updates_attempt(app, store):
    attempt = store.create_attempt("k1", "+34600111222", "ob1")
    store.update_attempt(
        attempt.id, provider_call_id="call-1", status=AttemptStatus.RUNNING
    )
    client = TestClient(app)
    r = _post(client, {"id": "call-1", "status": 4})
    assert r.status_code == 200
    assert store.get_attempt(attempt.id).status == AttemptStatus.COMPLETED


def test_lead_endpoint(app):
    client = TestClient(app)
    r = client.post(
        "/webhooks/pearl/lead",
        json={"leadId": "l1", "status": "called"},
        headers={"X-Webhook-Token": "wh-secret"},
    )
    assert r.status_code == 200
