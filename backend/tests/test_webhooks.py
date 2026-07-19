import httpx
import pytest

from app import webhooks
from app.signature import compute_signature
from tests.conftest import send_message, wait_for_status

CALLBACK_URL = "http://app.test/sms/status"


@pytest.fixture
def captured(monkeypatch):
    """Capture outbound webhook requests instead of hitting the network."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(handler))
    return requests


def form_of(request: httpx.Request) -> dict[str, str]:
    from urllib.parse import parse_qsl

    return dict(parse_qsl(request.content.decode()))


def test_status_callbacks_fire_per_transition(client, captured):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    sent = send_message(client, StatusCallback=CALLBACK_URL)
    wait_for_status(client, sent["sid"], "delivered")

    statuses = [form_of(r)["MessageStatus"] for r in captured]
    assert statuses == ["sending", "sent", "delivered"]

    last = form_of(captured[-1])
    assert last["MessageSid"] == sent["sid"]
    assert last["SmsStatus"] == "delivered"
    assert last["To"] == "+15551234567"
    assert last["ApiVersion"] == "2010-04-01"
    assert "RawDlrDoneDate" in last
    assert str(captured[-1].url) == CALLBACK_URL


def test_callbacks_carry_valid_signature(client, captured):
    client.put(
        "/api/settings",
        json={"simulate_delivery": True, "status_delay_ms": 0, "auth_token": "tok123"},
    )
    sent = send_message(client, StatusCallback=CALLBACK_URL)
    wait_for_status(client, sent["sid"], "delivered")

    request = captured[-1]
    expected = compute_signature("tok123", CALLBACK_URL, form_of(request))
    assert request.headers["X-Twilio-Signature"] == expected


def test_failed_delivery_includes_error_code(client, captured):
    client.put(
        "/api/settings",
        json={
            "simulate_delivery": True,
            "status_delay_ms": 0,
            "forced_rules": [{"to_suffix": "9999", "status": "undelivered", "error_code": 30007}],
        },
    )
    sent = send_message(client, To="+15550009999", StatusCallback=CALLBACK_URL)
    wait_for_status(client, sent["sid"], "undelivered")

    last = form_of(captured[-1])
    assert last["MessageStatus"] == "undelivered"
    assert last["ErrorCode"] == "30007"


def test_webhook_log_and_retry(client, captured):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    sent = send_message(client, StatusCallback=CALLBACK_URL)
    wait_for_status(client, sent["sid"], "delivered")

    log = client.get("/api/webhook-log").json()
    assert log["total"] == 3
    newest = log["deliveries"][0]
    assert newest["kind"] == "status_callback"
    assert newest["response_status"] == 204
    assert newest["message_sid"] == sent["sid"]
    assert newest["request_params"]["MessageStatus"] == "delivered"

    retried = client.post(f"/api/webhook-log/{newest['id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["response_status"] == 204
    assert client.get("/api/webhook-log").json()["total"] == 4


def test_unreachable_webhook_is_logged_as_error(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(handler))
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    sent = send_message(client, StatusCallback=CALLBACK_URL)
    wait_for_status(client, sent["sid"], "delivered")

    log = client.get("/api/webhook-log").json()
    assert log["total"] == 3
    assert all(d["response_status"] is None for d in log["deliveries"])
    assert "ConnectError" in log["deliveries"][0]["error"]
