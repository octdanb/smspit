import httpx
import pytest

from app import webhooks
from app.signature import compute_signature
from tests.conftest import send_message

WEBHOOK_URL = "http://app.test/sms/inbound"
USER = "+15551234567"
APP = "+15557654321"


@pytest.fixture
def inbound_receiver(monkeypatch):
    """Capture inbound webhooks; respond with a configurable body."""
    state = {"requests": [], "response": httpx.Response(204)}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["response"]

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(handler))
    return state


def form_of(request: httpx.Request) -> dict[str, str]:
    from urllib.parse import parse_qsl

    return dict(parse_qsl(request.content.decode()))


def reply(client, number=USER, **payload):
    payload.setdefault("body", "hi back")
    response = client.post(f"/api/numbers/{number}/reply", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_reply_records_inbound_message(client):
    send_message(client)  # establishes the thread and the app number
    data = reply(client, body="thanks!")

    assert data["direction"] == "inbound"
    assert data["status"] == "received"
    assert data["from_number"] == USER
    assert data["to_number"] == APP

    thread = client.get(f"/api/numbers/{USER}/messages").json()
    assert [m["direction"] for m in thread["messages"]] == ["outbound-api", "inbound"]


def test_reply_requires_known_app_number(client):
    response = client.post("/api/numbers/+15550001111/reply", json={"body": "hi"})
    assert response.status_code == 400

    data = reply(client, number="+15550001111", body="hi", to=APP)
    assert data["to_number"] == APP


def test_inbound_webhook_params_and_signature(client, inbound_receiver):
    client.put(
        "/api/settings",
        json={
            "inbound_webhook_url": WEBHOOK_URL,
            "auth_token": "webhook-secret",
            "account_sid": "AC" + "b" * 32,
            "webhook_geo_params": {"FromCountry": "NZ", "FromCity": "Wellington"},
        },
    )
    send_message(client)
    reply(client, body="hello app")

    assert len(inbound_receiver["requests"]) == 1
    request = inbound_receiver["requests"][0]
    params = form_of(request)
    assert params["From"] == USER
    assert params["To"] == APP
    assert params["Body"] == "hello app"
    assert params["SmsStatus"] == "received"
    assert params["NumMedia"] == "0"
    assert params["MessageSid"] == params["SmsSid"] == params["SmsMessageSid"]
    assert params["MessageSid"].startswith("SM")
    assert params["AccountSid"] == "AC" + "b" * 32
    assert params["FromCountry"] == "NZ"
    assert params["FromCity"] == "Wellington"

    expected = compute_signature("webhook-secret", WEBHOOK_URL, params)
    assert request.headers["X-Twilio-Signature"] == expected

    log = client.get("/api/webhook-log").json()
    assert log["deliveries"][0]["kind"] == "inbound"


def test_reply_with_media_in_webhook(client, inbound_receiver):
    client.put("/api/settings", json={"inbound_webhook_url": WEBHOOK_URL})
    send_message(client)
    data = reply(client, body="pic", media_urls=["https://example.com/cat.jpg"])

    assert data["num_media"] == 1
    assert data["media"][0]["content_type"] == "image/jpeg"

    params = form_of(inbound_receiver["requests"][0])
    assert params["NumMedia"] == "1"
    assert params["MediaContentType0"] == "image/jpeg"
    assert params["MediaUrl0"].startswith("http://localhost:8025/api/media/ME")


def test_twiml_auto_reply(client, inbound_receiver):
    client.put("/api/settings", json={"inbound_webhook_url": WEBHOOK_URL})
    inbound_receiver["response"] = httpx.Response(
        200,
        text=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response><Message>Auto-thanks!</Message></Response>"
        ),
        headers={"Content-Type": "text/xml"},
    )
    send_message(client)
    reply(client, body="ping")

    thread = client.get(f"/api/numbers/{USER}/messages").json()
    directions = [(m["direction"], m["body"]) for m in thread["messages"]]
    assert ("outbound-reply", "Auto-thanks!") in directions
    auto = next(m for m in thread["messages"] if m["direction"] == "outbound-reply")
    assert auto["from_number"] == APP
    assert auto["to_number"] == USER


def test_twiml_nested_body_and_media(client, inbound_receiver):
    client.put("/api/settings", json={"inbound_webhook_url": WEBHOOK_URL})
    inbound_receiver["response"] = httpx.Response(
        200,
        text=(
            "<Response><Message>"
            "<Body>With attachment</Body><Media>https://example.com/map.png</Media>"
            "</Message></Response>"
        ),
        headers={"Content-Type": "application/xml"},
    )
    send_message(client)
    reply(client, body="where?")

    thread = client.get(f"/api/numbers/{USER}/messages").json()
    auto = next(m for m in thread["messages"] if m["direction"] == "outbound-reply")
    assert auto["body"] == "With attachment"
    assert auto["num_media"] == 1


def test_empty_twiml_response_is_noop(client, inbound_receiver):
    client.put("/api/settings", json={"inbound_webhook_url": WEBHOOK_URL})
    inbound_receiver["response"] = httpx.Response(
        200, text="<Response/>", headers={"Content-Type": "text/xml"}
    )
    send_message(client)
    reply(client, body="ping")

    thread = client.get(f"/api/numbers/{USER}/messages").json()
    assert all(m["direction"] != "outbound-reply" for m in thread["messages"])


def test_malformed_twiml_does_not_crash(client, inbound_receiver):
    client.put("/api/settings", json={"inbound_webhook_url": WEBHOOK_URL})
    inbound_receiver["response"] = httpx.Response(
        200, text="<Response><Message>unclosed", headers={"Content-Type": "text/xml"}
    )
    send_message(client)
    reply(client, body="ping")  # asserts 200 internally
