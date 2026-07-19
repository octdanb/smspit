"""Phase 9: Feedback, content templates, GET webhooks, WhatsApp depth,
API-key auth, list pagination, fallback URLs, IncomingPhoneNumbers."""

from urllib.parse import parse_qs, parse_qsl, urlparse

import httpx
import pytest

from app import webhooks
from app.signature import compute_signature
from tests.conftest import AUTH, MESSAGES_URL, send_message, wait_for_status

USER = "+15551234567"
APP = "+15557654321"


@pytest.fixture
def receiver(monkeypatch):
    state = {"requests": [], "responses": {}}  # url-substring -> Response

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        for fragment, response in state["responses"].items():
            if fragment in str(request.url):
                return response
        return httpx.Response(204)

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(handler))
    return state


# --- Feedback subresource ---


def test_feedback_roundtrip(client):
    sent = send_message(client, ProvideFeedback="true")
    url = f"/2010-04-01/Accounts/{AUTH[0]}/Messages/{sent['sid']}/Feedback.json"

    response = client.post(url, data={"Outcome": "confirmed"}, auth=AUTH)
    assert response.status_code == 201
    data = response.json()
    assert data["message_sid"] == sent["sid"]
    assert data["outcome"] == "confirmed"
    assert data["uri"].endswith("/Feedback.json")


def test_feedback_requires_provide_feedback(client):
    sent = send_message(client)
    url = f"/2010-04-01/Accounts/{AUTH[0]}/Messages/{sent['sid']}/Feedback.json"
    response = client.post(url, data={"Outcome": "confirmed"}, auth=AUTH)
    assert response.status_code == 400
    assert response.json()["code"] == 20001


def test_feedback_validates_outcome(client):
    sent = send_message(client, ProvideFeedback="true")
    url = f"/2010-04-01/Accounts/{AUTH[0]}/Messages/{sent['sid']}/Feedback.json"
    assert client.post(url, data={"Outcome": "maybe"}, auth=AUTH).status_code == 400


# --- ContentSid rendering ---


def test_content_sid_renders_variables(client):
    response = client.post(
        MESSAGES_URL,
        data={
            "To": USER,
            "From": APP,
            "ContentSid": "HX" + "a" * 32,
            "ContentVariables": '{"1": "482913", "name": "Dan"}',
        },
        auth=AUTH,
    )
    assert response.status_code == 201
    body = response.json()["body"]
    assert body.startswith("[HX")
    assert "482913" in body
    # latest-code picks the OTP out of the rendered template
    assert client.get(f"/api/numbers/{USER}/latest-code").json()["code"] == "482913"


def test_content_sid_without_variables(client):
    response = client.post(
        MESSAGES_URL,
        data={"To": USER, "From": APP, "ContentSid": "HX" + "b" * 32},
        auth=AUTH,
    )
    assert response.status_code == 201
    assert response.json()["body"] == "[HX" + "b" * 32 + "]"


# --- GET webhook delivery ---


def test_inbound_webhook_get_method_and_signature(client, receiver):
    client.put(
        "/api/settings",
        json={
            "inbound_webhook_url": "http://app.test/sms",
            "inbound_webhook_method": "GET",
            "auth_token": "get-secret",
        },
    )
    send_message(client)
    client.post(f"/api/numbers/{USER}/reply", json={"body": "hi"})

    request = receiver["requests"][-1]
    assert request.method == "GET"
    params = dict(parse_qsl(urlparse(str(request.url)).query))
    assert params["Body"] == "hi"
    assert params["From"] == USER
    # GET signature: full URL including query, nothing appended.
    expected = compute_signature("get-secret", str(request.url), {})
    assert request.headers["X-Twilio-Signature"] == expected

    log = client.get("/api/webhook-log").json()
    assert log["deliveries"][0]["method"] == "GET"


# --- WhatsApp depth ---


def test_whatsapp_session_window_strict(client):
    client.put("/api/settings", json={"strict_validation": True})
    wa_user = f"whatsapp:{USER}"
    wa_app = f"whatsapp:{APP}"

    blocked = client.post(
        MESSAGES_URL, data={"To": wa_user, "From": wa_app, "Body": "free-form"}, auth=AUTH
    )
    assert blocked.status_code == 400
    assert blocked.json()["code"] == 63016

    # Template sends always pass.
    assert (
        client.post(
            MESSAGES_URL,
            data={"To": wa_user, "From": wa_app, "ContentSid": "HX" + "c" * 32},
            auth=AUTH,
        ).status_code
        == 201
    )

    # An inbound message opens the 24h window for free-form sends.
    client.post(f"/api/numbers/{wa_user}/reply", json={"body": "hello", "to": wa_app})
    assert (
        client.post(
            MESSAGES_URL, data={"To": wa_user, "From": wa_app, "Body": "free-form"}, auth=AUTH
        ).status_code
        == 201
    )


def test_whatsapp_read_status(client):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    client.post(
        f"/api/numbers/whatsapp:{USER}/reply", json={"body": "open window", "to": f"whatsapp:{APP}"}
    )
    sent = send_message(client, To=f"whatsapp:{USER}", From=f"whatsapp:{APP}")
    data = wait_for_status(client, sent["sid"], "read")
    assert data["status"] == "read"


def test_sms_stops_at_delivered(client):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    sent = send_message(client)
    wait_for_status(client, sent["sid"], "delivered")


# --- API key auth ---


def test_strict_auth_accepts_api_key(client):
    client.put(
        "/api/settings",
        json={
            "strict_auth": True,
            "account_sid": AUTH[0],
            "auth_token": "main-token",
            "api_key_sid": "SK" + "a" * 32,
            "api_key_secret": "key-secret",
        },
    )
    data = {"To": USER, "From": APP, "Body": "x"}
    assert (
        client.post(MESSAGES_URL, data=data, auth=("SK" + "a" * 32, "key-secret")).status_code
        == 201
    )
    assert client.post(MESSAGES_URL, data=data, auth=("SK" + "a" * 32, "wrong")).status_code == 401


# --- pagination ---


def test_v1_service_list_pagination(client):
    for index in range(3):
        client.post("/v1/Services", data={"FriendlyName": f"svc {index}"}, auth=AUTH)

    page = client.get("/v1/Services", params={"PageSize": 2}, auth=AUTH).json()
    assert len(page["services"]) == 2
    assert page["meta"]["next_page_url"] is not None

    page2 = client.get(page["meta"]["next_page_url"], auth=AUTH).json()
    assert len(page2["services"]) == 1
    assert page2["meta"]["next_page_url"] is None
    assert page2["meta"]["previous_page_url"] is not None


def test_media_list_pagination(client):
    urls = [f"https://example.com/{i}.png" for i in range(3)]
    sent = client.post(
        MESSAGES_URL,
        data={"To": USER, "From": APP, "Body": "pics", "MediaUrl": urls},
        auth=AUTH,
    ).json()

    page = client.get(sent["subresource_uris"]["media"], params={"PageSize": 2}, auth=AUTH).json()
    assert len(page["media_list"]) == 2
    assert page["next_page_uri"] is not None
    page2 = client.get(page["next_page_uri"], auth=AUTH).json()
    assert len(page2["media_list"]) == 1
    assert page2["next_page_uri"] is None


# --- fallback URLs ---


def test_service_fallback_url_on_handler_error(client, receiver):
    receiver["responses"]["primary"] = httpx.Response(500, text="boom")
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    service = client.post(
        "/v1/Services",
        data={
            "FriendlyName": "Alerts",
            "InboundRequestUrl": "http://app.test/primary",
            "FallbackUrl": "http://app.test/fallback",
        },
        auth=AUTH,
    ).json()
    client.post(f"/v1/Services/{service['sid']}/PhoneNumbers", data={"PhoneNumber": APP}, auth=AUTH)
    sent = client.post(
        MESSAGES_URL,
        data={"To": USER, "MessagingServiceSid": service["sid"], "Body": "hi"},
        auth=AUTH,
    ).json()
    wait_for_status(client, sent["sid"], "delivered")

    client.post(f"/api/numbers/{USER}/reply", json={"body": "reply"})
    urls = [str(r.url) for r in receiver["requests"]]
    assert "http://app.test/primary" in urls
    assert "http://app.test/fallback" in urls


# --- IncomingPhoneNumbers ---


def test_incoming_phone_number_crud(client):
    response = client.post(
        f"/2010-04-01/Accounts/{AUTH[0]}/IncomingPhoneNumbers.json",
        data={"PhoneNumber": APP, "SmsUrl": "http://app.test/number-sms", "SmsMethod": "GET"},
        auth=AUTH,
    )
    assert response.status_code == 201
    number = response.json()
    assert number["sid"].startswith("PN")
    assert number["sms_url"] == "http://app.test/number-sms"
    assert number["sms_method"] == "GET"
    assert number["capabilities"]["sms"] is True

    listing = client.get(
        f"/2010-04-01/Accounts/{AUTH[0]}/IncomingPhoneNumbers.json",
        params={"PhoneNumber": APP},
        auth=AUTH,
    ).json()
    assert len(listing["incoming_phone_numbers"]) == 1

    updated = client.post(
        f"/2010-04-01/Accounts/{AUTH[0]}/IncomingPhoneNumbers/{number['sid']}.json",
        data={"FriendlyName": "Main line"},
        auth=AUTH,
    ).json()
    assert updated["friendly_name"] == "Main line"

    # Duplicate provisioning rejected.
    assert (
        client.post(
            f"/2010-04-01/Accounts/{AUTH[0]}/IncomingPhoneNumbers.json",
            data={"PhoneNumber": APP},
            auth=AUTH,
        ).status_code
        == 400
    )

    assert (
        client.delete(
            f"/2010-04-01/Accounts/{AUTH[0]}/IncomingPhoneNumbers/{number['sid']}.json", auth=AUTH
        ).status_code
        == 204
    )


def test_number_sms_url_routing(client, receiver):
    client.put("/api/settings", json={"inbound_webhook_url": "http://app.test/global"})
    client.post(
        f"/2010-04-01/Accounts/{AUTH[0]}/IncomingPhoneNumbers.json",
        data={"PhoneNumber": APP, "SmsUrl": "http://app.test/number-sms"},
        auth=AUTH,
    )
    send_message(client)  # From=APP establishes the thread
    client.post(f"/api/numbers/{USER}/reply", json={"body": "to the number"})

    assert str(receiver["requests"][-1].url) == "http://app.test/number-sms"


def test_number_status_callback_fallback(client, receiver):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    client.post(
        f"/2010-04-01/Accounts/{AUTH[0]}/IncomingPhoneNumbers.json",
        data={"PhoneNumber": APP, "StatusCallback": "http://app.test/number-status"},
        auth=AUTH,
    )
    sent = send_message(client)  # no per-message StatusCallback
    wait_for_status(client, sent["sid"], "delivered")

    urls = {str(r.url) for r in receiver["requests"]}
    assert "http://app.test/number-status" in urls
    statuses = [
        dict(parse_qs(r.content.decode()))["MessageStatus"][0]
        for r in receiver["requests"]
        if r.method == "POST"
    ]
    assert "delivered" in statuses
