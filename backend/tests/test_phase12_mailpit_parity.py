"""Phase 12: release to real Twilio, search operators, capture webhook,
encoding check."""

import json
import time

import httpx
import pytest

from app import release, webhooks
from tests.conftest import send_message

USER = "+15551234567"
APP = "+15557654321"


# --- release / forwarding ---


@pytest.fixture
def real_twilio(monkeypatch):
    """Stand-in for api.twilio.com capturing release sends."""
    state = {"requests": [], "status": 201}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return httpx.Response(state["status"], json={"sid": "SM" + "f" * 32, "status": "queued"})

    monkeypatch.setattr(release, "_transport", httpx.MockTransport(handler))
    return state


def configure_release(client, allowlist):
    client.put(
        "/api/settings",
        json={
            "real_account_sid": "AC" + "9" * 32,
            "real_auth_token": "real-token",
            "real_from_number": "+15559990000",
            "release_allowlist": allowlist,
        },
    )


def test_release_requires_configuration(client):
    sent = send_message(client)
    response = client.post(f"/api/messages/{sent['sid']}/release", json={})
    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]


def test_release_enforces_allowlist(client, real_twilio):
    configure_release(client, allowlist=["+15550001111"])
    sent = send_message(client)  # To=USER, not allowlisted

    response = client.post(f"/api/messages/{sent['sid']}/release", json={})
    assert response.status_code == 403
    assert "allowlist" in response.json()["detail"]
    assert real_twilio["requests"] == []  # nothing left the building


def test_release_sends_via_real_twilio(client, real_twilio):
    configure_release(client, allowlist=[USER])
    sent = send_message(client, Body="release me")

    response = client.post(f"/api/messages/{sent['sid']}/release", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["released"] is True
    assert data["real_sid"] == "SM" + "f" * 32

    request = real_twilio["requests"][0]
    assert str(request.url).startswith("https://api.twilio.com/2010-04-01/Accounts/AC9")
    from urllib.parse import parse_qsl

    params = dict(parse_qsl(request.content.decode()))
    assert params == {"To": USER, "From": "+15559990000", "Body": "release me"}
    assert "Basic" in request.headers["authorization"]

    log = client.get("/api/webhook-log", params={"kind": "release"}).json()
    assert log["total"] == 1
    assert log["deliveries"][0]["response_status"] == 201


def test_release_to_override_recipient(client, real_twilio):
    configure_release(client, allowlist=["+15550002222"])
    sent = send_message(client)

    response = client.post(f"/api/messages/{sent['sid']}/release", json={"to": "+15550002222"})
    assert response.json()["to"] == "+15550002222"


def test_release_failure_reported(client, real_twilio):
    real_twilio["status"] = 401
    configure_release(client, allowlist=[USER])
    sent = send_message(client)

    data = client.post(f"/api/messages/{sent['sid']}/release", json={}).json()
    assert data["released"] is False
    assert data["response_status"] == 401


def wait_for_log(client, kind, total, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        log = client.get("/api/webhook-log", params={"kind": kind}).json()
        if log["total"] >= total:
            return log
        time.sleep(0.02)
    raise AssertionError(f"webhook log never reached {total} {kind} deliveries")


def test_auto_forward(client, real_twilio):
    configure_release(client, allowlist=["+15553334444"])
    client.put("/api/settings", json={"auto_forward_to": "+15553334444"})

    send_message(client, Body="forward me")
    wait_for_log(client, "release", 1)

    from urllib.parse import parse_qsl

    params = dict(parse_qsl(real_twilio["requests"][0].content.decode()))
    assert params["To"] == "+15553334444"
    assert params["Body"] == "forward me"


# --- capture webhook ---


@pytest.fixture
def capture_receiver(monkeypatch):
    state = {"requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return httpx.Response(200)

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(handler))
    return state


def test_capture_webhook_fires_for_all_directions(client, capture_receiver):
    client.put("/api/settings", json={"capture_webhook_url": "http://ci.test/capture"})

    sent = send_message(client, Body="outbound capture")
    wait_for_log(client, "capture", 1)
    client.post(f"/api/numbers/{USER}/reply", json={"body": "inbound capture"})
    wait_for_log(client, "capture", 2)

    payloads = [json.loads(r.content) for r in capture_receiver["requests"]]
    assert payloads[0]["message"]["sid"] == sent["sid"]
    assert payloads[0]["message"]["body"] == "outbound capture"
    assert payloads[1]["message"]["direction"] == "inbound"
    assert capture_receiver["requests"][0].headers["content-type"] == "application/json"


def test_capture_webhook_off_by_default(client, capture_receiver):
    send_message(client)
    time.sleep(0.1)
    assert capture_receiver["requests"] == []


# --- search operators ---


def test_search_operators(client):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    send_message(
        client, To="+15550001111", Body="picture message", MediaUrl="https://example.com/a.png"
    )
    send_message(client, To="+15550002222", Body="plain text")
    from tests.conftest import wait_for_status

    # let both reach delivered so status: is deterministic
    for thread in client.get("/api/numbers").json():
        wait_for_status(client, thread["last_message"]["sid"], "delivered")

    def numbers(q):
        return [t["number"] for t in client.get("/api/numbers", params={"q": q}).json()]

    assert numbers("has:media") == ["+15550001111"]
    assert numbers("to:0002222") == ["+15550002222"]
    assert set(numbers(f"from:{APP[1:5]}")) == {"+15550001111", "+15550002222"}
    assert set(numbers("status:delivered")) == {"+15550001111", "+15550002222"}
    assert numbers("status:failed") == []
    assert numbers("has:media plain") == []  # operators AND free text combine
    assert numbers("before:2000-01-01") == []
    assert set(numbers("after:2000-01-01")) == {"+15550001111", "+15550002222"}


def test_search_is_unread(client):
    send_message(client, To="+15550001111")
    send_message(client, To="+15550002222")
    client.post("/api/numbers/+15550001111/read")

    results = [t["number"] for t in client.get("/api/numbers", params={"q": "is:unread"}).json()]
    assert results == ["+15550002222"]


# --- encoding check ---


def test_encoding_check_gsm7(client):
    sent = send_message(client, Body="plain ascii")
    check = client.get(f"/api/messages/{sent['sid']}").json()["encoding_check"]
    assert check["encoding"] == "gsm7"
    assert check["num_segments"] == 1
    assert check["non_gsm_chars"] == []


def test_encoding_check_flags_unicode_and_smart_encoding(client):
    sent = send_message(client, Body="Smart “quotes” cost segments " + "x" * 140)
    check = client.get(f"/api/messages/{sent['sid']}").json()["encoding_check"]
    assert check["encoding"] == "ucs2"
    assert {c["char"] for c in check["non_gsm_chars"]} == {"“", "”"}
    assert check["smart_encoding_would_use"] == "gsm7"
    assert check["smart_encoding_segments"] < check["num_segments"]
