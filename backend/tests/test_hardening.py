"""Phase 13 hardening: SSRF guard, secrets redaction, schema migration, SPA
traversal, opt-out on service sends, DateSent semantics, malformed params."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlmodel import Session

from app import config as config_module
from app import db, media
from tests.conftest import AUTH, MESSAGES_URL, send_message

# --- SSRF guard -------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:3000/x.png",  # loopback
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "http://10.0.0.5/internal.png",  # private
        "http://192.168.1.10/x",  # private
        "ftp://example.com/x",  # non-http scheme
        "file:///etc/passwd",  # file scheme
        "http://[::1]/x",  # IPv6 loopback
    ],
)
def test_ssrf_guard_blocks_dangerous_urls(url):
    assert media._is_fetchable(url) is False


def test_ssrf_guard_allows_public_literal_ip():
    assert media._is_fetchable("http://8.8.8.8/pic.png") is True


def test_ssrf_guard_can_be_opted_out_for_local_dev(monkeypatch):
    monkeypatch.setattr(config_module.config, "allow_private_media", True)
    assert media._is_fetchable("http://127.0.0.1:3000/x.png") is True


# --- Secrets redaction ------------------------------------------------------


def test_settings_never_returns_secrets(client):
    client.put("/api/settings", json={"auth_token": "supersecret"})
    body = client.get("/api/settings").json()
    assert body["auth_token"] == ""
    assert body["auth_token_set"] is True


def test_blank_secret_keeps_existing_value(client):
    client.put("/api/settings", json={"auth_token": "supersecret"})
    # A blank secret on save must not wipe the stored value (the UI never saw it).
    client.put("/api/settings", json={"auth_token": ""})
    with Session(db.get_engine()) as session:
        assert db.get_settings(session).auth_token == "supersecret"
    # A non-blank secret does update it.
    client.put("/api/settings", json={"auth_token": "rotated"})
    with Session(db.get_engine()) as session:
        assert db.get_settings(session).auth_token == "rotated"


# --- Additive schema migration ----------------------------------------------


def test_ensure_schema_adds_missing_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    # An "old" settings table from before several options were added.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE settings (id INTEGER PRIMARY KEY, auth_token VARCHAR)"))
        conn.execute(text("INSERT INTO settings (id, auth_token) VALUES (1, 'tok')"))

    db.ensure_schema(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("settings")}
    assert "capture_webhook_url" in columns
    assert "webhook_failure_rate" in columns
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT auth_token, capture_webhook_url FROM settings WHERE id = 1")
        ).one()
    assert row[0] == "tok"  # existing data preserved
    assert row[1] == ""  # new column backfilled with the model default


# --- SPA path traversal -----------------------------------------------------


def test_spa_does_not_serve_files_outside_static_root(tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<div id='root'></div>")
    (static / "assets" / "app.js").write_text("console.log('ok')")
    (tmp_path / "secret.txt").write_text("TOPSECRET")

    monkeypatch.setattr(config_module.config, "static_dir", static)
    monkeypatch.setattr(config_module.config, "db_path", tmp_path / "t.db")
    monkeypatch.setattr(db, "_engine", None)

    with TestClient(create_app_fresh()) as spa_client:
        assert spa_client.get("/assets/app.js").status_code == 200
        for attempt in ("/%2e%2e/secret.txt", "/..%2f..%2fsecret.txt", "/static/../secret.txt"):
            assert "TOPSECRET" not in spa_client.get(attempt).text


def create_app_fresh():
    from app.main import create_app

    return create_app()


# --- Opt-out enforcement on Messaging Service sends -------------------------


def test_optout_enforced_for_messaging_service_send(client):
    user = "+15559990000"
    client.put("/api/settings", json={"enforce_optouts": True})
    client.put("/api/optouts", json={"recipient": user, "sender": "*", "opted_out": True})

    service = client.post("/v1/Services", data={"FriendlyName": "Pool"}, auth=AUTH).json()

    response = client.post(
        MESSAGES_URL,
        data={"To": user, "MessagingServiceSid": service["sid"], "Body": "hi"},
        auth=AUTH,
    )
    assert response.status_code == 400
    assert response.json()["code"] == 21610


# --- DateSent filters on the sent date, not the created date ----------------


def test_datesent_filter_excludes_unsent(client):
    # simulate_delivery is off in tests, so this stays queued with date_sent = NULL.
    sent = send_message(client)
    today = datetime.now(UTC).date().isoformat()
    listing = client.get(f"{MESSAGES_URL}?DateSent={today}", auth=AUTH).json()
    assert all(m["sid"] != sent["sid"] for m in listing["messages"])


# --- Malformed numeric params return a Twilio 400, not a 500 ----------------


def test_malformed_pagesize_returns_twilio_400(client):
    response = client.get(f"{MESSAGES_URL}?PageSize=abc", auth=AUTH)
    assert response.status_code == 400
    assert "code" in response.json()


# --- Version endpoint -------------------------------------------------------


def test_version_endpoint(client):
    body = client.get("/api/version").json()
    assert "version" in body
