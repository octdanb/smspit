from tests.conftest import AUTH, MESSAGES_URL, send_message


def test_strict_auth_rejects_wrong_credentials(client):
    client.put(
        "/api/settings",
        json={"strict_auth": True, "account_sid": AUTH[0], "auth_token": "right-token"},
    )

    response = client.post(
        MESSAGES_URL,
        data={"To": "+15551234567", "From": "+15557654321", "Body": "x"},
        auth=(AUTH[0], "wrong-token"),
    )
    assert response.status_code == 401
    assert response.json()["code"] == 20003

    assert (
        client.post(
            MESSAGES_URL,
            data={"To": "+15551234567", "From": "+15557654321", "Body": "x"},
            auth=(AUTH[0], "right-token"),
        ).status_code
        == 201
    )


def test_strict_validation_to_and_from(client):
    client.put("/api/settings", json={"strict_validation": True})

    bad_to = client.post(
        MESSAGES_URL, data={"To": "+1555", "From": "+15557654321", "Body": "x"}, auth=AUTH
    )
    assert bad_to.status_code == 400
    assert bad_to.json()["code"] == 21211

    bad_from = client.post(
        MESSAGES_URL, data={"To": "+15551234567", "From": "not!valid!", "Body": "x"}, auth=AUTH
    )
    assert bad_from.json()["code"] == 21212

    # Valid sender shapes still pass: E.164, short code, alpha sender, whatsapp.
    for sender in ("+15557654321", "44755", "OCTAVE", "whatsapp:+15557654321"):
        response = client.post(
            MESSAGES_URL, data={"To": "+15551234567", "From": sender, "Body": "x"}, auth=AUTH
        )
        assert response.status_code == 201, sender


def test_strict_validation_landline_21614(client):
    client.put(
        "/api/settings",
        json={
            "strict_validation": True,
            "lookup_line_types": {"+15551234567": "landline"},
        },
    )
    response = client.post(
        MESSAGES_URL, data={"To": "+15551234567", "From": "+15557654321", "Body": "x"}, auth=AUTH
    )
    assert response.status_code == 400
    assert response.json()["code"] == 21614


def test_trial_mode_requires_verified_numbers(client):
    client.put(
        "/api/settings",
        json={"trial_mode": True, "verified_numbers": ["+15550001111"]},
    )

    blocked = client.post(
        MESSAGES_URL, data={"To": "+15551234567", "From": "+15557654321", "Body": "x"}, auth=AUTH
    )
    assert blocked.status_code == 400
    assert blocked.json()["code"] == 21608

    assert (
        client.post(
            MESSAGES_URL,
            data={"To": "+15550001111", "From": "+15557654321", "Body": "x"},
            auth=AUTH,
        ).status_code
        == 201
    )


def test_rate_limit_simulation(client):
    client.put("/api/settings", json={"rate_limit_per_minute": 3})

    for _ in range(3):
        send_message(client)
    response = client.post(
        MESSAGES_URL,
        data={"To": "+15551234567", "From": "+15557654321", "Body": "over the limit"},
        auth=AUTH,
    )
    assert response.status_code == 429
    assert response.json()["code"] == 20429


def test_permissive_by_default(client):
    # None of the strict checks apply out of the box.
    response = client.post(
        MESSAGES_URL, data={"To": "anything", "From": "whatever!", "Body": "x"}, auth=AUTH
    )
    assert response.status_code == 201


def test_numbers_search(client):
    send_message(client, To="+15550001111", Body="Your pizza is ready")
    send_message(client, To="+15550002222", Body="Your login code is 123456")

    results = client.get("/api/numbers", params={"q": "pizza"}).json()
    assert [t["number"] for t in results] == ["+15550001111"]

    results = client.get("/api/numbers", params={"q": "0002222"}).json()
    assert [t["number"] for t in results] == ["+15550002222"]

    assert len(client.get("/api/numbers", params={"q": "your"}).json()) == 2
    assert client.get("/api/numbers", params={"q": "zzz"}).json() == []
    assert len(client.get("/api/numbers").json()) == 2
