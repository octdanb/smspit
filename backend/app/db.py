from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import config

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        config.db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{config.db_path}",
            connect_args={"check_same_thread": False},
        )
    return _engine


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
