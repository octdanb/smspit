"""SDK conformance: the real twilio-python client against a live smspit.

Run with a mock instance on SMSPIT_URL (default http://localhost:8025):

    uv run --project conformance/python pytest conformance/python -v

This is what turns "Twilio-shaped" into a tested guarantee: if these pass,
an app using the official SDK works against smspit unchanged.
"""

import os
import time
import uuid

import httpx
import pytest
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

BASE = os.environ.get("SMSPIT_URL", "http://localhost:8025")
ACCOUNT_SID = "AC" + "0" * 32
APP = "+15005550006"


def unique_number() -> str:
    return "+1555" + str(uuid.uuid4().int)[:7]


@pytest.fixture(scope="module")
def client() -> Client:
    twilio_client = Client(ACCOUNT_SID, "conformance-token")
    for domain in (twilio_client.api, twilio_client.messaging, twilio_client.verify,
                   twilio_client.lookups):
        domain.base_url = BASE
    return twilio_client


@pytest.fixture(scope="module", autouse=True)
def fast_simulation():
    httpx.put(f"{BASE}/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})


def wait_for_status(client: Client, sid: str, status: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        message = client.messages(sid).fetch()
        if message.status == status:
            return message
        time.sleep(0.05)
    raise AssertionError(f"{sid} never reached {status}; last: {message.status}")


def test_send_and_fetch(client):
    to = unique_number()
    message = client.messages.create(to=to, from_=APP, body="conformance hello")
    assert message.sid.startswith("SM")
    assert message.status in ("queued", "accepted")
    assert message.num_segments == "1"
    assert message.from_ == APP

    fetched = client.messages(message.sid).fetch()
    assert fetched.body == "conformance hello"
    assert fetched.to == to
    assert fetched.date_created is not None  # SDK parsed the RFC 2822 date


def test_list_pagination(client):
    to = unique_number()
    sids = {client.messages.create(to=to, from_=APP, body=f"msg {i}").sid for i in range(5)}

    # page_size=2 forces the SDK to follow next_page_uri / PageToken chains.
    listed = client.messages.list(to=to, page_size=2)
    assert {message.sid for message in listed} == sids


def test_redact_and_delete(client):
    to = unique_number()
    message = client.messages.create(to=to, from_=APP, body="secret 123456")
    wait_for_status(client, message.sid, "delivered")

    redacted = client.messages(message.sid).update(body="")
    assert redacted.body == ""

    assert client.messages(message.sid).delete() is True
    with pytest.raises(TwilioRestException) as excinfo:
        client.messages(message.sid).fetch()
    assert excinfo.value.status == 404


def test_error_envelope(client):
    with pytest.raises(TwilioRestException) as excinfo:
        client.messages.create(to="", from_=APP, body="x")
    assert excinfo.value.code == 21604
    assert excinfo.value.status == 400


def test_mms_media(client):
    to = unique_number()
    message = client.messages.create(
        to=to, from_=APP, body="pic", media_url=["https://example.com/cat.jpg"]
    )
    assert message.sid.startswith("MM")
    assert message.num_media == "1"

    media = client.messages(message.sid).media.list()
    assert len(media) == 1
    assert media[0].sid.startswith("ME")
    assert media[0].content_type == "image/jpeg"


def test_verify_flow(client):
    service = client.verify.v2.services.create(friendly_name="Conformance")
    assert service.sid.startswith("VA")

    to = unique_number()
    verification = client.verify.v2.services(service.sid).verifications.create(
        to=to, channel="sms"
    )
    assert verification.status == "pending"

    code = httpx.get(f"{BASE}/api/numbers/{to}/latest-code").json()["code"]
    wrong = client.verify.v2.services(service.sid).verification_checks.create(
        to=to, code="000000"
    )
    assert wrong.status == "pending"
    approved = client.verify.v2.services(service.sid).verification_checks.create(
        to=to, code=code
    )
    assert approved.status == "approved"
    assert approved.valid is True


def test_messaging_service_pool(client):
    service = client.messaging.v1.services.create(friendly_name="Conformance pool")
    assert service.sid.startswith("MG")
    client.messaging.v1.services(service.sid).phone_numbers.create(
        phone_number_sid="+15550009900"
    )

    to = unique_number()
    message = client.messages.create(to=to, messaging_service_sid=service.sid, body="via pool")
    assert message.status == "accepted"
    delivered = wait_for_status(client, message.sid, "delivered")
    assert delivered.from_ == "+15550009900"
    assert delivered.messaging_service_sid == service.sid


def test_lookup(client):
    result = client.lookups.v2.phone_numbers("+14155552671").fetch()
    assert result.valid is True
    assert result.phone_number == "+14155552671"
    assert result.country_code == "US"
    assert result.national_format == "(415) 555-2671"
