"""Configuracion de MCPCalls cargada desde variables de entorno / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes del servicio. Las credenciales nunca deben loguearse."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Credenciales NLPearl (auth: Bearer {account_id}:{secret_key})
    pearl_account_id: str = ""
    pearl_secret_key: str = ""
    pearl_api_base: str = "https://api.nlpearl.ai"
    # Identificador de la campana outbound en la API v1 (para make_call)
    pearl_outbound_id: str = ""
    # Identificador del Pearl en la API v2 (para consultas de llamadas)
    pearl_id: str = ""
    # Telefono de pruebas para el harness de validacion (nunca en codigo)
    pearl_test_number: str = ""

    # Receptor de webhooks
    mcpcalls_webhook_token: str = ""
    webhook_public_url: str = ""

    # Persistencia (SQLite ahora; Postgres despues sin tocar codigo)
    mcpcalls_db_url: str = "sqlite:///./data/mcpcalls.db"

    # Ventana horaria de llamada: formato "HH:MM-HH:MM ZonaIANA"
    mcpcalls_calling_window: str = "09:00-21:00 Europe/Madrid"

    # Ritmo frente a la API (aprendido en tuotempo: 429 frecuente)
    pearl_max_concurrent: int = 2
    pearl_request_pacing_s: float = 1.0
    pearl_max_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
