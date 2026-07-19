from tests.conftest import AUTH, send_message, wait_for_status


def message_url(sid: str) -> str:
    return f"/2010-04-01/Accounts/{AUTH[0]}/Messages/{sid}.json"


def test_redact_body(client):
    sent = send_message(client, Body="secret code 1234")

    response = client.post(message_url(sent["sid"]), data={"Body": ""}, auth=AUTH)
    assert response.status_code == 200
    assert response.json()["body"] == ""

    assert client.get(message_url(sent["sid"]), auth=AUTH).json()["body"] == ""


def test_redact_rejects_non_empty_body(client):
    sent = send_message(client)
    response = client.post(message_url(sent["sid"]), data={"Body": "new text"}, auth=AUTH)
    assert response.status_code == 400
    assert response.json()["code"] == 20001


def test_cancel_only_applies_to_scheduled(client):
    sent = send_message(client)  # simulation off: stays queued
    response = client.post(message_url(sent["sid"]), data={"Status": "canceled"}, auth=AUTH)
    assert response.status_code == 400
    assert response.json()["code"] == 20001


def test_delete_in_flight_conflicts(client):
    sent = send_message(client)  # queued, not terminal
    response = client.delete(message_url(sent["sid"]), auth=AUTH)
    assert response.status_code == 409
    assert response.json()["code"] == 20009


def test_delete_terminal_message(client):
    client.put("/api/settings", json={"simulate_delivery": True, "status_delay_ms": 0})
    sent = send_message(client)
    wait_for_status(client, sent["sid"], "delivered")

    response = client.delete(message_url(sent["sid"]), auth=AUTH)
    assert response.status_code == 204
    assert client.get(message_url(sent["sid"]), auth=AUTH).status_code == 404


def test_settings_roundtrip(client):
    response = client.put(
        "/api/settings",
        json={
            "status_delay_ms": 50,
            "failure_rate": 0.5,
            "forced_rules": [{"to_suffix": "1", "status": "failed", "error_code": 30004}],
        },
    )
    assert response.status_code == 200

    data = client.get("/api/settings").json()
    assert data["status_delay_ms"] == 50
    assert data["failure_rate"] == 0.5
    assert data["forced_rules"] == [{"to_suffix": "1", "status": "failed", "error_code": 30004}]
