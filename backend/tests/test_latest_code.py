from tests.conftest import send_message

USER = "+15551234567"


def test_latest_code_returns_most_recent(client):
    send_message(client, Body="Your code is 111111")
    send_message(client, Body="Your code is 222222")

    data = client.get(f"/api/numbers/{USER}/latest-code").json()
    assert data["code"] == "222222"
    assert data["message_sid"].startswith("SM")
    assert data["age_seconds"] >= 0


def test_latest_code_skips_codeless_messages(client):
    send_message(client, Body="Your code is 333333")
    send_message(client, Body="Thanks for signing up!")

    assert client.get(f"/api/numbers/{USER}/latest-code").json()["code"] == "333333"


def test_latest_code_404_when_none(client):
    send_message(client, Body="No digits here")
    assert client.get(f"/api/numbers/{USER}/latest-code").status_code == 404
    assert client.get("/api/numbers/+15550009999/latest-code").status_code == 404


def test_latest_code_regex_override(client):
    send_message(client, Body="Your token is XY-99887 (code 123456)")

    data = client.get(
        f"/api/numbers/{USER}/latest-code", params={"regex": r"token is ([A-Z]+-\d+)"}
    ).json()
    assert data["code"] == "XY-99887"


def test_latest_code_invalid_regex_400(client):
    send_message(client, Body="code 123456")
    response = client.get(f"/api/numbers/{USER}/latest-code", params={"regex": "(unclosed"})
    assert response.status_code == 400


def test_latest_code_only_counts_messages_to_number(client):
    # Inbound (user -> app) codes must not leak into the user's latest-code.
    send_message(client, Body="app to user 444444")
    client.post(f"/api/numbers/{USER}/reply", json={"body": "user to app 555555"})

    assert client.get(f"/api/numbers/{USER}/latest-code").json()["code"] == "444444"
