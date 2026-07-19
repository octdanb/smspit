import re

from tests.conftest import AUTH

USER = "+15551234567"


def create_service(client, **overrides) -> dict:
    data = {"FriendlyName": "My App"}
    data.update(overrides)
    response = client.post("/v2/Services", data=data, auth=AUTH)
    assert response.status_code == 201, response.text
    return response.json()


def start(client, service_sid, **overrides) -> dict:
    data = {"To": USER, "Channel": "sms"}
    data.update(overrides)
    response = client.post(f"/v2/Services/{service_sid}/Verifications", data=data, auth=AUTH)
    assert response.status_code == 201, response.text
    return response.json()


def check(client, service_sid, code, **extra):
    data = {"To": USER, "Code": code}
    data.update(extra)
    return client.post(f"/v2/Services/{service_sid}/VerificationCheck", data=data, auth=AUTH)


def test_service_crud(client):
    service = create_service(client, CodeLength="4")
    assert re.fullmatch(r"VA[0-9a-f]{32}", service["sid"])
    assert service["friendly_name"] == "My App"
    assert service["code_length"] == 4
    assert service["date_created"].endswith("Z")  # v2 uses ISO 8601, not RFC 2822

    listing = client.get("/v2/Services", auth=AUTH).json()
    assert listing["meta"]["key"] == "services"
    assert len(listing["services"]) == 1

    updated = client.post(
        f"/v2/Services/{service['sid']}", data={"CodeLength": "8"}, auth=AUTH
    ).json()
    assert updated["code_length"] == 8

    assert client.delete(f"/v2/Services/{service['sid']}", auth=AUTH).status_code == 204
    assert client.get(f"/v2/Services/{service['sid']}", auth=AUTH).status_code == 404


def test_service_validation(client):
    assert client.post("/v2/Services", data={}, auth=AUTH).json()["code"] == 60200
    assert (
        client.post("/v2/Services", data={"FriendlyName": "x" * 33}, auth=AUTH).json()["code"]
        == 60200
    )
    assert (
        client.post(
            "/v2/Services", data={"FriendlyName": "ok", "CodeLength": "3"}, auth=AUTH
        ).json()["code"]
        == 60200
    )


def test_start_verification_records_sms(client):
    service = create_service(client)
    verification = start(client, service["sid"])

    assert re.fullmatch(r"VE[0-9a-f]{32}", verification["sid"])
    assert verification["status"] == "pending"
    assert verification["valid"] is False
    assert len(verification["send_code_attempts"]) == 1

    # The code arrives as a real SMS and is exposed via latest-code.
    latest = client.get(f"/api/numbers/{USER}/latest-code").json()
    assert re.fullmatch(r"\d{6}", latest["code"])
    thread = client.get(f"/api/numbers/{USER}/messages").json()
    assert f"Your My App verification code is: {latest['code']}" in [
        m["body"] for m in thread["messages"]
    ]
    assert thread["messages"][-1]["from_number"] == "My App"  # valid alpha sender

    verifications = client.get(f"/api/numbers/{USER}/verifications").json()
    assert verifications[0]["code"] == latest["code"]
    assert verifications[0]["service_name"] == "My App"


def test_check_wrong_then_correct(client):
    service = create_service(client)
    start(client, service["sid"])
    code = client.get(f"/api/numbers/{USER}/latest-code").json()["code"]

    wrong = check(client, service["sid"], "000000")
    assert wrong.status_code == 200
    assert wrong.json()["status"] == "pending"
    assert wrong.json()["valid"] is False

    approved = check(client, service["sid"], code)
    assert approved.json()["status"] == "approved"
    assert approved.json()["valid"] is True

    # Approved verifications are consumed: further checks 404 like Twilio.
    assert check(client, service["sid"], code).status_code == 404
    assert check(client, service["sid"], code).json()["code"] == 20404


def test_max_check_attempts(client):
    service = create_service(client)
    start(client, service["sid"])

    for _ in range(5):
        assert check(client, service["sid"], "000000").status_code == 200
    blocked = check(client, service["sid"], "000000")
    assert blocked.status_code == 429
    assert blocked.json()["code"] == 60202

    verifications = client.get(f"/api/numbers/{USER}/verifications").json()
    assert verifications[0]["status"] == "max_attempts_reached"


def test_resend_appends_attempt_and_max_sends(client):
    service = create_service(client)
    first = start(client, service["sid"])
    second = start(client, service["sid"])
    assert second["sid"] == first["sid"]  # same open verification
    assert len(second["send_code_attempts"]) == 2

    for _ in range(3):
        start(client, service["sid"])
    response = client.post(
        f"/v2/Services/{service['sid']}/Verifications",
        data={"To": USER, "Channel": "sms"},
        auth=AUTH,
    )
    assert response.status_code == 429
    assert response.json()["code"] == 60203


def test_custom_code(client):
    service = create_service(client, CustomCodeEnabled="true")
    start(client, service["sid"], CustomCode="424242")
    assert check(client, service["sid"], "424242").json()["status"] == "approved"

    plain = create_service(client, FriendlyName="No custom")
    response = client.post(
        f"/v2/Services/{plain['sid']}/Verifications",
        data={"To": USER, "Channel": "sms", "CustomCode": "1234"},
        auth=AUTH,
    )
    assert response.json()["code"] == 60200


def test_non_sms_channel_rejected(client):
    service = create_service(client)
    response = client.post(
        f"/v2/Services/{service['sid']}/Verifications",
        data={"To": USER, "Channel": "email"},
        auth=AUTH,
    )
    assert response.status_code == 400
    assert response.json()["code"] == 60200


def test_expired_verification_404s(client):
    client.put("/api/settings", json={"verify_ttl_seconds": 0})
    service = create_service(client)
    start(client, service["sid"])

    response = check(client, service["sid"], "123456")
    assert response.status_code == 404

    verifications = client.get(f"/api/numbers/{USER}/verifications").json()
    assert verifications[0]["status"] == "expired"


def test_cancel_verification(client):
    service = create_service(client)
    verification = start(client, service["sid"])

    canceled = client.post(
        f"/v2/Services/{service['sid']}/Verifications/{verification['sid']}",
        data={"Status": "canceled"},
        auth=AUTH,
    )
    assert canceled.json()["status"] == "canceled"
    assert check(client, service["sid"], "123456").status_code == 404


def test_check_by_verification_sid(client):
    service = create_service(client)
    verification = start(client, service["sid"])
    code = client.get(f"/api/numbers/{USER}/latest-code").json()["code"]

    response = check(client, service["sid"], code, To="", VerificationSid=verification["sid"])
    assert response.json()["status"] == "approved"
