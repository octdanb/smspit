"""Phase 11: seed API and webhook chaos options."""

import httpx
import pytest

from app import webhooks
from tests.conftest import send_message

USER = "+15551234567"


def test_seed_demo_preset(client):
    response = client.post("/api/seed", json={})
    assert response.status_code == 201
    assert response.json()["created"] == 5

    numbers = client.get("/api/numbers").json()
    assert len(numbers) == 3
    tags = {t["tag"] for t in client.get("/api/tags").json()}
    assert {"otp", "campaign:spring", "shipping"} <= tags
    # Seeded outbound messages arrive terminal.
    thread = client.get("/api/numbers/+15551230001/messages").json()
    assert thread["messages"][0]["status"] == "delivered"
    assert thread["messages"][1]["status"] == "received"
    # OTP fixtures work with latest-code.
    assert client.get("/api/numbers/+15551230001/latest-code").json()["code"] == "482913"


def test_seed_custom_messages(client):
    response = client.post(
        "/api/seed",
        json={
            "messages": [
                {
                    "from_number": "+15550100009",
                    "to_number": "+15559990001",
                    "body": "custom fixture",
                    "tags": ["fixture"],
                }
            ]
        },
    )
    assert response.json()["created"] == 1
    numbers = client.get("/api/numbers").json()
    assert numbers[0]["number"] == "+15559990001"
    assert numbers[0]["tags"] == ["fixture"]


@pytest.fixture
def counting_receiver(monkeypatch):
    state = {"count": 0, "fail_first": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["count"] += 1
        if state["count"] <= state["fail_first"]:
            return httpx.Response(500)
        return httpx.Response(204)

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(handler))
    return state


def test_webhook_retries_after_failure(client, counting_receiver):
    counting_receiver["fail_first"] = 2
    client.put(
        "/api/settings",
        json={"inbound_webhook_url": "http://app.test/in", "webhook_retry_count": 3},
    )
    send_message(client)
    client.post(f"/api/numbers/{USER}/reply", json={"body": "hi"})

    # 2 failures + 1 success; each attempt logged.
    assert counting_receiver["count"] == 3
    log = client.get("/api/webhook-log").json()
    assert log["total"] == 3
    assert log["deliveries"][0]["response_status"] == 204
    assert log["deliveries"][1]["response_status"] == 500


def test_webhook_retries_exhausted(client, counting_receiver):
    counting_receiver["fail_first"] = 99
    client.put(
        "/api/settings",
        json={"inbound_webhook_url": "http://app.test/in", "webhook_retry_count": 2},
    )
    send_message(client)
    client.post(f"/api/numbers/{USER}/reply", json={"body": "hi"})

    assert counting_receiver["count"] == 3  # initial + 2 retries
    assert all(
        d["response_status"] == 500 for d in client.get("/api/webhook-log").json()["deliveries"]
    )


def test_webhook_failure_injection(client, counting_receiver):
    client.put(
        "/api/settings",
        json={"inbound_webhook_url": "http://app.test/in", "webhook_failure_rate": 1.0},
    )
    send_message(client)
    client.post(f"/api/numbers/{USER}/reply", json={"body": "hi"})

    assert counting_receiver["count"] == 0  # never reached the app
    log = client.get("/api/webhook-log").json()
    assert "ChaosError" in log["deliveries"][0]["error"]


def test_webhook_latency(client, counting_receiver):
    import time

    client.put(
        "/api/settings",
        json={"inbound_webhook_url": "http://app.test/in", "webhook_latency_ms": 300},
    )
    send_message(client)
    started = time.monotonic()
    client.post(f"/api/numbers/{USER}/reply", json={"body": "hi"})
    assert time.monotonic() - started >= 0.3
