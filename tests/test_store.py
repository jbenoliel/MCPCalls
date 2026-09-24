from mcpcalls.pearl.store import Store


def test_attempt_dedup_by_idempotency_key(store: Store):
    a = store.create_attempt("key-1", "+34600111222", "ob1")
    b = store.create_attempt("key-1", "+34600111222", "ob1")
    assert a.id == b.id

    c = store.create_attempt("key-2", "+34600111222", "ob1")
    assert c.id != a.id


def test_attempt_update(store: Store):
    a = store.create_attempt("key-1", "+34600111222", "ob1")
    store.update_attempt(a.id, status="submitted", provider_request_id="req-1")
    fetched = store.get_attempt(a.id)
    assert fetched.status == "submitted"
    assert fetched.provider_request_id == "req-1"


def test_provider_event_dedup(store: Store):
    first = store.record_provider_event(
        "ev-1", "webhook", "call-1", "4", {"status": 4}
    )
    second = store.record_provider_event(
        "ev-1", "webhook", "call-1", "4", {"status": 4}
    )
    assert first is True
    assert second is False


def test_event_log_append(store: Store):
    store.log_event("test_event", actor="test", payload={"a": 1})
    store.log_event("test_event", actor="test")
    # sin excepciones = ok; la lectura se cubre en tests de integracion
