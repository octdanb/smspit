import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

from app import db
from app.main import create_app

AUTH = ("AC" + "a" * 32, "test-token")
MESSAGES_URL = f"/2010-04-01/Accounts/{AUTH[0]}/Messages.json"


@pytest.fixture
def client(monkeypatch, tmp_path):
    # A file-backed database (not :memory:/StaticPool): request handlers and
    # background lifecycle tasks need isolated connections, or one session's
    # rollback can clobber another's in-flight transaction.
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    # Patch the global engine so request handlers AND background lifecycle
    # tasks all hit the same in-memory database.
    monkeypatch.setattr(db, "_engine", engine)

    with TestClient(create_app()) as test_client:
        # Deterministic default: lifecycle simulation off, no artificial delays.
        # Lifecycle tests opt back in via PUT /api/settings.
        test_client.put(
            "/api/settings",
            json={"simulate_delivery": False, "status_delay_ms": 0},
        )
        yield test_client


def send_message(client: TestClient, **overrides) -> dict:
    data = {"To": "+15551234567", "From": "+15557654321", "Body": "hello"}
    data.update(overrides)
    response = client.post(MESSAGES_URL, data=data, auth=AUTH)
    assert response.status_code == 201, response.text
    return response.json()


def wait_for_status(client: TestClient, sid: str, status: str, timeout: float = 3.0) -> dict:
    """Poll a message until the lifecycle simulator reaches the given status."""
    url = f"/2010-04-01/Accounts/{AUTH[0]}/Messages/{sid}.json"
    deadline = time.time() + timeout
    data: dict = {}
    while time.time() < deadline:
        data = client.get(url, auth=AUTH).json()
        if data["status"] == status:
            return data
        time.sleep(0.01)
    raise AssertionError(f"{sid} never reached {status!r}; last status: {data.get('status')!r}")
