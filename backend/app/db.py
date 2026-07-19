from collections.abc import Iterator

from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import config

_engine = None


def _apply_pragmas(dbapi_connection, _record) -> None:
    # WAL lets readers and a writer coexist; busy_timeout makes concurrent
    # writers wait for the lock instead of raising "database is locked".
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def get_engine():
    global _engine
    if _engine is None:
        config.db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{config.db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        event.listen(_engine, "connect", _apply_pragmas)
    return _engine


def _default_literal(column) -> str | None:
    """Render a column's Python-side default as a SQL literal, or None."""
    default = column.default
    if default is None or default.is_callable or default.is_server_default:
        return None
    value = default.arg
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def ensure_schema(engine) -> None:
    """Additive migration: ADD COLUMN for any model column missing from an
    existing table. The schema only ever grows (new Settings options each
    release), so this covers upgrades against a persisted database volume
    without a full migration framework. It never drops or alters columns.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            type_sql = column.type.compile(engine.dialect)
            clause = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {type_sql}'
            literal = _default_literal(column)
            if literal is not None:
                clause += f" DEFAULT {literal}"
                if not column.nullable:
                    clause += " NOT NULL"
            with engine.begin() as conn:
                conn.execute(text(clause))


def init_db() -> None:
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    ensure_schema(engine)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_settings(session: Session):
    """Fetch the singleton Settings row, creating it on first access."""
    from .models import Settings

    settings = session.get(Settings, 1)
    if settings is None:
        settings = Settings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings
