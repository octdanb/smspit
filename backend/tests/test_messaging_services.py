import re

import httpx
import pytest

from app import webhooks
from tests.conftest import AUTH, MESSAGES_URL, send_message, wait_for_status

USER = "+15551234567"


def create_service(client, **overrides) -> dict:
    data = {"FriendlyName": "Notifications"}
    data.update(overrides)
    response = client.post("/v1/Services", data=data, auth=AUTH)
    assert response.status_code == 201, response.text
    return response.json()


def add_number(client, service_sid, number) -> dict:
    response = client.post(
        f"/v1/Services/{service_sid}/PhoneNumbers", data={"PhoneNumber": number}, auth=AUTH
    )
    assert response.status_code == 201, response.text
    return response.json()


def send_via_service(client, service_sid, to=USER, **overrides) -> dict:
    data = {"To": to, "MessagingServiceSid": service_sid, "Body": "hi"}
    data.update(overrides)
    response = client.post(MESSAGES_URL, data=data, auth=AUTH)
    assert response.status_code == 201, response.text
    return response.json()


def test_service_crud_shape(client):
    service = create_service(
        client, InboundRequestUrl="http://app.test/in", AreaCodeGeomatch="true"
    )
    assert re.fullmatch(r"MG[0-9a-f]{32}", service["sid"])
    assert service["sticky_sender"] is True
    assert service["smart_encoding"] is True
    assert service["area_code_geomatch"] is True
    assert service["validity_period"] == 36000
    assert service["date_created"].endswith("Z")
    assert service["links"]["phone_numbers"].endswith("/PhoneNumbers")

    listing = client.get("/v1/Services", auth=AUTH).json()
    assert listing["meta"]["key"] == "services"

    updated = client.post(
        f"/v1/Services/{service['sid']}", data={"StickySender": "false"}, auth=AUTH
    ).json()
    assert updated["sticky_sender"] is False

    assert client.delete(f"/v1/Services/{service['sid']}", auth=AUTH).status_code == 204
    assert client.get(f"/v1/Services/{service['sid']}", auth=AUTH).status_code == 404


def test_sender_pool_subresources(client):
    service = create_service(client)
    number = add_number(client, service["sid"], "+15550001111")
    assert re.fullmatch(r"PN[0-9a-f]{32}", number["sid"])
    assert number["phone_number"] == "+15550001111"
    assert number["capabilities"] == ["SMS", "MMS"]

    alpha = client.post(
        f"/v1/Services/{service['sid']}/AlphaSenders", data={"AlphaSender": "OCTAVE"}, auth=AUTH
    ).json()
    assert re.fullmatch(r"AI[0-9a-f]{32}", alpha["sid"])
    assert alpha["capabilities"] == ["SMS"]

    short = client.post(
        f"/v1/Services/{service['sid']}/ShortCodes", data={"ShortCode": "44755"}, auth=AUTH
    ).json()
    assert re.fullmatch(r"SC[0-9a-f]{32}", short["sid"])

    numbers = client.get(f"/v1/Services/{service['sid']}/PhoneNumbers", auth=AUTH).json()
    assert numbers["meta"]["key"] == "phone_numbers"
    assert len(numbers["phone_numbers"]) == 1

    bad_alpha = client.post(
        f"/v1/Services/{service['sid']}/AlphaSenders", data={"AlphaSender": "12345"}, auth=AUTH
    )
    assert bad_alpha.status_code == 400

    assert (
        client.delete(
            f"/v1/Services/{service['sid']}/PhoneNumbers/{number['sid']}", auth=AUTH
        ).status_code
        == 204
    )
    assert (
        client.get(f"/v1/Services/{service['sid']}/PhoneNumbers", auth=AUTH).json()["phone_numbers"]
        == []
    )


def test_send_via_service_accepted_flow(client):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    service = create_service(client)
    add_number(client, service["sid"], "+15550001111")

    sent = send_via_service(client, service["sid"])
    assert sent["status"] == "accepted"
    assert sent["from"] == ""
    assert sent["messaging_service_sid"] == service["sid"]

    data = wait_for_status(client, sent["sid"], "delivered")
    assert data["from"] == "+15550001111"  # pool-selected sender


def test_sticky_sender(client):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    service = create_service(client)
    add_number(client, service["sid"], "+15550001111")
    add_number(client, service["sid"], "+15550002222")

    first = wait_for_status(client, send_via_service(client, service["sid"])["sid"], "delivered")
    second = wait_for_status(client, send_via_service(client, service["sid"])["sid"], "delivered")
    assert second["from"] == first["from"]  # same recipient keeps the same sender


def test_area_code_geomatch(client):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    service = create_service(client, AreaCodeGeomatch="true", StickySender="false")
    add_number(client, service["sid"], "+15550001111")
    add_number(client, service["sid"], "+16465550000")  # 646 matches the recipient

    sent = send_via_service(client, service["sid"], to="+16467778888")
    data = wait_for_status(client, sent["sid"], "delivered")
    assert data["from"] == "+16465550000"


def test_empty_pool_fails_with_21606(client):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    service = create_service(client)

    sent = send_via_service(client, service["sid"])
    data = wait_for_status(client, sent["sid"], "failed")
    assert data["error_code"] == 21606


def test_unknown_service_sid_rejected(client):
    response = client.post(
        MESSAGES_URL,
        data={"To": USER, "MessagingServiceSid": "MG" + "0" * 32, "Body": "x"},
        auth=AUTH,
    )
    assert response.status_code == 404
    assert response.json()["code"] == 21701


def test_service_status_callback_applies(client, monkeypatch):
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(handler))
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    service = create_service(client, StatusCallback="http://app.test/service-status")
    add_number(client, service["sid"], "+15550001111")

    sent = send_via_service(client, service["sid"])
    wait_for_status(client, sent["sid"], "delivered")

    assert captured, "expected service-level status callbacks"
    from urllib.parse import parse_qsl

    params = dict(parse_qsl(captured[-1].content.decode()))
    assert str(captured[-1].url) == "http://app.test/service-status"
    assert params["MessagingServiceSid"] == service["sid"]


@pytest.fixture
def inbound_receiver(monkeypatch):
    state = {"requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return httpx.Response(204)

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(handler))
    return state


def test_reply_routes_to_service_inbound_url(client, inbound_receiver):
    client.put(
        "/api/settings",
        json={
            "simulate_delivery": True,
            "status_delay_ms": 0,
            "inbound_webhook_url": "http://app.test/global",
        },
    )
    service = create_service(client, InboundRequestUrl="http://app.test/service-inbound")
    add_number(client, service["sid"], "+15550001111")
    sent = send_via_service(client, service["sid"])
    wait_for_status(client, sent["sid"], "delivered")

    response = client.post(f"/api/numbers/{USER}/reply", json={"body": "hi back"})
    assert response.status_code == 200

    inbound_requests = [r for r in inbound_receiver["requests"] if "inbound" in str(r.url)]
    assert str(inbound_requests[-1].url) == "http://app.test/service-inbound"
    from urllib.parse import parse_qsl

    params = dict(parse_qsl(inbound_requests[-1].content.decode()))
    assert params["MessagingServiceSid"] == service["sid"]


def test_use_inbound_webhook_on_number_falls_back(client, inbound_receiver):
    client.put(
        "/api/settings",
        json={
            "simulate_delivery": True,
            "status_delay_ms": 0,
            "inbound_webhook_url": "http://app.test/global",
        },
    )
    service = create_service(
        client,
        InboundRequestUrl="http://app.test/service-inbound",
        UseInboundWebhookOnNumber="true",
    )
    add_number(client, service["sid"], "+15550001111")
    sent = send_via_service(client, service["sid"])
    wait_for_status(client, sent["sid"], "delivered")

    client.post(f"/api/numbers/{USER}/reply", json={"body": "hi back"})
    urls = [str(r.url) for r in inbound_receiver["requests"]]
    assert "http://app.test/global" in urls
    assert "http://app.test/service-inbound" not in urls


def test_plain_send_still_works_with_from_and_service(client):
    # From + MessagingServiceSid together: no accepted phase, From wins.
    service = create_service(client)
    sent = send_message(client, MessagingServiceSid=service["sid"])
    assert sent["status"] == "queued"
    assert sent["from"] == "+15557654321"
    assert sent["messaging_service_sid"] == service["sid"]
