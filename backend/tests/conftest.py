import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import main as main_module
from app.db import get_session
from app.main import create_app

AUTH = ("AC" + "a" * 32, "test-token")
MESSAGES_URL = f"/2010-04-01/Accounts/{AUTH[0]}/Messages.json"


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main_module, "init_db", lambda: None)

    app = create_app()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client


def send_message(client: TestClient, **overrides) -> dict:
    data = {"To": "+15551234567", "From": "+15557654321", "Body": "hello"}
    data.update(overrides)
    response = client.post(MESSAGES_URL, data=data, auth=AUTH)
    assert response.status_code == 201, response.text
    return response.json()
