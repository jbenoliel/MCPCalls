import pytest

from mcpcalls.config import Settings
from mcpcalls.pearl.store import Store


@pytest.fixture
def settings(tmp_path):
    """Settings de test: credenciales falsas, pacing 0, ventana siempre abierta."""
    return Settings(
        pearl_account_id="acc-test",
        pearl_secret_key="secret-test",
        pearl_outbound_id="outbound-test",
        pearl_id="pearl-test",
        mcpcalls_db_url=f"sqlite:///{tmp_path}/test.db",
        mcpcalls_calling_window="00:00-23:59 Europe/Madrid",
        pearl_request_pacing_s=0.0,
        pearl_max_concurrent=4,
        pearl_max_retries=2,
        mcpcalls_webhook_token="wh-secret",
    )


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path}/store.db")
