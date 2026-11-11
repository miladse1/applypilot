from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
        return kwargs
    return {"pool_pre_ping": True}


def _prepare_sqlite_folder(url: str) -> None:
    """Create the folder of a SQLite database file, readable only by this user."""
    from sqlalchemy.engine import make_url

    database = make_url(url).database
    if not database or database == ":memory:":
        return
    folder = Path(database).expanduser().resolve().parent
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)


def make_engine(url: str | None = None):
    database_url = url or get_settings().database_url
    if database_url.startswith("sqlite"):
        _prepare_sqlite_folder(database_url)
    engine = create_engine(database_url, **_engine_kwargs(database_url))

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        if database_url.startswith("sqlite"):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if database_url not in {"sqlite://", "sqlite:///:memory:"}:
                # WAL lets background job discovery write while pages read.
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()

    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
