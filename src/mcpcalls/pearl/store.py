"""Persistencia del adaptador Pearl.

SQLite ahora; la URL viene de MCPCALLS_DB_URL y puede apuntar a Postgres
en el despliegue sin tocar este codigo.

Tablas:
- call_attempts: un intento de llamada nuestro, con dedup por idempotency_key.
- provider_events: eventos recibidos (webhook o poll) con dedup.
- event_log: registro append-only, semilla del patron outbox de la Fase 1.
"""

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import (
    JSON,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CallAttemptRow(Base):
    __tablename__ = "call_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(unique=True, index=True)
    to_e164: Mapped[str] = mapped_column(index=True)
    outbound_id: Mapped[str]
    status: Mapped[str] = mapped_column(default="pending", index=True)
    provider_request_id: Mapped[str | None] = mapped_column(default=None)
    provider_call_id: Mapped[str | None] = mapped_column(default=None, index=True)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=None
    )
    context_version: Mapped[int] = mapped_column(default=1)
    last_result_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=None
    )
    error: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ProviderEventRow(Base):
    __tablename__ = "provider_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_provider_event_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_key: Mapped[str]
    source: Mapped[str]  # "webhook" | "poll" | "reconcile"
    call_id: Mapped[str | None] = mapped_column(default=None, index=True)
    status: Mapped[str] = mapped_column(default="")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    received_at: Mapped[datetime] = mapped_column(default=utcnow)


class EventLogRow(Base):
    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(index=True)
    actor: Mapped[str] = mapped_column(default="system")
    attempt_id: Mapped[int | None] = mapped_column(default=None, index=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Store:
    """Acceso a datos del adaptador. Una instancia por proceso."""

    def __init__(self, db_url: str):
        self.engine: Engine = create_engine(
            db_url,
            connect_args=(
                {"check_same_thread": False}
                if db_url.startswith("sqlite")
                else {}
            ),
        )
        Base.metadata.create_all(self.engine)
        self._session_factory = sessionmaker(
            self.engine, expire_on_commit=False
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ---------- call_attempts ----------

    def create_attempt(
        self,
        idempotency_key: str,
        to_e164: str,
        outbound_id: str,
        context: dict[str, Any] | None = None,
    ) -> CallAttemptRow:
        """Crea el intento o devuelve el existente si la clave ya existe."""
        with self.session() as s:
            existing = s.scalar(
                select(CallAttemptRow).where(
                    CallAttemptRow.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return existing
            row = CallAttemptRow(
                idempotency_key=idempotency_key,
                to_e164=to_e164,
                outbound_id=outbound_id,
                context_json=context,
            )
            s.add(row)
            s.flush()
            return row

    def get_attempt(self, attempt_id: int) -> CallAttemptRow | None:
        with self.session() as s:
            return s.get(CallAttemptRow, attempt_id)

    def get_attempt_by_key(self, key: str) -> CallAttemptRow | None:
        with self.session() as s:
            return s.scalar(
                select(CallAttemptRow).where(
                    CallAttemptRow.idempotency_key == key
                )
            )

    def update_attempt(self, attempt_id: int, **fields: Any) -> None:
        with self.session() as s:
            row = s.get(CallAttemptRow, attempt_id)
            if row is None:
                return
            for key, value in fields.items():
                setattr(row, key, value)

    # ---------- provider_events ----------

    def record_provider_event(
        self,
        event_key: str,
        source: str,
        call_id: str | None,
        status: str,
        payload: dict[str, Any] | None,
    ) -> bool:
        """Inserta el evento si no existe. Devuelve True si era nuevo."""
        with self.session() as s:
            existing = s.scalar(
                select(ProviderEventRow).where(
                    ProviderEventRow.event_key == event_key
                )
            )
            if existing is not None:
                return False
            s.add(
                ProviderEventRow(
                    event_key=event_key,
                    source=source,
                    call_id=call_id,
                    status=status,
                    payload=payload,
                )
            )
            return True

    # ---------- event_log ----------

    def log_event(
        self,
        event_type: str,
        actor: str = "system",
        attempt_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.session() as s:
            s.add(
                EventLogRow(
                    event_type=event_type,
                    actor=actor,
                    attempt_id=attempt_id,
                    payload=payload,
                )
            )

    def dump_json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)
