import httpx
import pytest

from app import webhooks
from tests.conftest import AUTH, MESSAGES_URL, send_message

USER = "+15551234567"
APP = "+15557654321"
WEBHOOK_URL = "http://app.test/sms/inbound"


@pytest.fixture
def inbound_receiver(monkeypatch):
    state = {"requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return httpx.Response(204)

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(handler))
    return state


def form_of(request: httpx.Request) -> dict[str, str]:
    from urllib.parse import parse_qsl

    return dict(parse_qsl(request.content.decode()))


def reply(client, body):
    response = client.post(f"/api/numbers/{USER}/reply", json={"body": body})
    assert response.status_code == 200
    return response.json()


def test_stop_records_optout_and_confirms(client):
    send_message(client)
    reply(client, "STOP")

    optouts = client.get("/api/optouts").json()
    assert optouts == [
        {
            "recipient": USER,
            "sender": APP,
            "opted_out": True,
            "date_updated": optouts[0]["date_updated"],
        }
    ]

    thread = client.get(f"/api/numbers/{USER}/messages").json()
    assert thread["opted_out"] is True
    confirmation = thread["messages"][-1]
    assert confirmation["direction"] == "outbound-reply"
    assert "unsubscribed" in confirmation["body"]

    numbers = client.get("/api/numbers").json()
    assert numbers[0]["opted_out"] is True


def test_start_clears_optout(client):
    send_message(client)
    reply(client, "stop")  # keywords are case-insensitive
    reply(client, "START")

    assert client.get("/api/optouts").json()[0]["opted_out"] is False
    thread = client.get(f"/api/numbers/{USER}/messages").json()
    assert thread["opted_out"] is False
    assert "re-subscribed" in thread["messages"][-1]["body"]


def test_help_sends_help_reply_without_optout(client):
    send_message(client)
    reply(client, "HELP")

    assert client.get("/api/optouts").json() == []
    thread = client.get(f"/api/numbers/{USER}/messages").json()
    assert "Reply STOP to unsubscribe" in thread["messages"][-1]["body"]


def test_optout_type_in_webhook(client, inbound_receiver):
    client.put("/api/settings", json={"inbound_webhook_url": WEBHOOK_URL})
    send_message(client)
    reply(client, "STOP")

    params = form_of(inbound_receiver["requests"][0])
    assert params["OptOutType"] == "STOP"

    reply(client, "just a normal message")
    assert "OptOutType" not in form_of(inbound_receiver["requests"][1])


def test_enforcement_rejects_opted_out_sends(client):
    send_message(client)
    reply(client, "STOP")

    # Permissive default: the send still succeeds.
    assert (
        client.post(
            MESSAGES_URL,
            data={"To": USER, "From": APP, "Body": "promo"},
            auth=AUTH,
        ).status_code
        == 201
    )

    client.put("/api/settings", json={"enforce_optouts": True})
    response = client.post(
        MESSAGES_URL,
        data={"To": USER, "From": APP, "Body": "promo"},
        auth=AUTH,
    )
    assert response.status_code == 400
    assert response.json()["code"] == 21610

    # A different From is not blocked by this pair.
    assert (
        client.post(
            MESSAGES_URL,
            data={"To": USER, "From": "+15550009999", "Body": "other sender"},
            auth=AUTH,
        ).status_code
        == 201
    )


def test_manual_optout_toggle_uses_wildcard(client):
    client.put("/api/settings", json={"enforce_optouts": True})
    response = client.put("/api/optouts", json={"recipient": USER, "opted_out": True})
    assert response.json()["sender"] == "*"

    blocked = client.post(
        MESSAGES_URL,
        data={"To": USER, "From": "+15550001234", "Body": "any sender"},
        auth=AUTH,
    )
    assert blocked.status_code == 400
    assert blocked.json()["code"] == 21610

    client.put("/api/optouts", json={"recipient": USER, "opted_out": False})
    assert (
        client.post(
            MESSAGES_URL,
            data={"To": USER, "From": "+15550001234", "Body": "any sender"},
            auth=AUTH,
        ).status_code
        == 201
    )


def test_wildcard_opt_in_clears_stop_created_pairs(client):
    send_message(client)
    reply(client, "STOP")  # creates the (USER, APP) pair
    client.put("/api/settings", json={"enforce_optouts": True})

    client.put("/api/optouts", json={"recipient": USER, "opted_out": False})

    assert all(not p["opted_out"] for p in client.get("/api/optouts").json())
    assert (
        client.post(
            MESSAGES_URL,
            data={"To": USER, "From": APP, "Body": "welcome back"},
            auth=AUTH,
        ).status_code
        == 201
    )


def test_custom_keywords_and_confirmations(client):
    client.put(
        "/api/settings",
        json={
            "optout_config": {
                "keywords": {"stop": ["BASTA"]},
                "confirmations": {"stop": "Kua mutu. Reply START to resubscribe."},
            }
        },
    )
    send_message(client)
    reply(client, "BASTA")

    assert client.get("/api/optouts").json()[0]["opted_out"] is True
    thread = client.get(f"/api/numbers/{USER}/messages").json()
    assert thread["messages"][-1]["body"].startswith("Kua mutu")
