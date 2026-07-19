from tests.conftest import AUTH, MESSAGES_URL, send_message, wait_for_status


def enable_simulation(client, **extra):
    payload = {"simulate_delivery": True, "status_delay_ms": 0}
    payload.update(extra)
    response = client.put("/api/settings", json=payload)
    assert response.status_code == 200, response.text


def test_message_progresses_to_delivered(client):
    enable_simulation(client)
    sent = send_message(client)
    assert sent["status"] == "queued"

    data = wait_for_status(client, sent["sid"], "delivered")
    assert data["date_sent"] is not None
    assert data["price"] == "-0.00750"
    assert data["error_code"] is None


def test_forced_undelivered_rule(client):
    enable_simulation(
        client,
        forced_rules=[{"to_suffix": "9999", "status": "undelivered", "error_code": 30007}],
    )
    sent = send_message(client, To="+15550009999")

    data = wait_for_status(client, sent["sid"], "undelivered")
    assert data["error_code"] == 30007
    assert data["error_message"] == "Message filtered"
    assert data["date_sent"] is not None  # undelivered happens after the carrier accepted it


def test_forced_failed_rule_never_reaches_carrier(client):
    enable_simulation(
        client,
        forced_rules=[{"to_suffix": "0000", "status": "failed", "error_code": 30004}],
    )
    sent = send_message(client, To="+15550000000")

    data = wait_for_status(client, sent["sid"], "failed")
    assert data["error_code"] == 30004
    assert data["date_sent"] is None  # failed straight from queued


def test_status_changed_ws_events(client):
    enable_simulation(client)
    with client.websocket_connect("/api/ws") as websocket:
        send_message(client)
        events = [websocket.receive_json() for _ in range(4)]

    assert events[0]["type"] == "message.created"
    statuses = [e["data"]["message"]["status"] for e in events[1:]]
    assert statuses == ["sending", "sent", "delivered"]


def test_scheduled_message_waits_and_can_be_canceled(client):
    enable_simulation(client)
    response = client.post(
        MESSAGES_URL,
        data={
            "To": "+15551234567",
            "From": "+15557654321",
            "Body": "later",
            "ScheduleType": "fixed",
            "SendAt": "2030-01-01T00:00:00Z",
        },
        auth=AUTH,
    )
    assert response.status_code == 201
    sent = response.json()
    assert sent["status"] == "scheduled"

    url = f"/2010-04-01/Accounts/{AUTH[0]}/Messages/{sent['sid']}.json"
    canceled = client.post(url, data={"Status": "canceled"}, auth=AUTH)
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"


def test_scheduled_message_fires_when_due(client):
    enable_simulation(client)
    response = client.post(
        MESSAGES_URL,
        data={
            "To": "+15551234567",
            "From": "+15557654321",
            "Body": "due now",
            "ScheduleType": "fixed",
            "SendAt": "2020-01-01T00:00:00Z",  # already past: fires immediately
        },
        auth=AUTH,
    )
    assert response.status_code == 201
    wait_for_status(client, response.json()["sid"], "delivered")


def test_schedule_requires_send_at(client):
    response = client.post(
        MESSAGES_URL,
        data={
            "To": "+15551234567",
            "From": "+15557654321",
            "Body": "x",
            "ScheduleType": "fixed",
        },
        auth=AUTH,
    )
    assert response.status_code == 400
    assert response.json()["code"] == 20001
