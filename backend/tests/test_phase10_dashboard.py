"""Phase 10: tags, unread, message detail/delete, retention, export,
webhook-log filters, scheduled view, dashboard token."""

import httpx
import pytest
from sqlmodel import Session

from app import webhooks
from tests.conftest import AUTH, MESSAGES_URL, send_message

USER = "+15551234567"
APP = "+15557654321"


# --- tags ---


def test_manual_tags_roundtrip(client):
    sent = send_message(client)
    response = client.put(f"/api/messages/{sent['sid']}/tags", json={"tags": ["otp", "smoke "]})
    assert response.status_code == 200
    assert response.json()["tags"] == ["otp", "smoke"]

    thread = client.get(f"/api/numbers/{USER}/messages").json()
    assert thread["messages"][-1]["tags"] == ["otp", "smoke"]
    numbers = client.get("/api/numbers").json()
    assert numbers[0]["tags"] == ["otp", "smoke"]
    assert client.get("/api/tags").json() == [
        {"tag": "otp", "count": 1},
        {"tag": "smoke", "count": 1},
    ]


def test_twilio_tags_param_surfaces_as_tags(client):
    response = client.post(
        MESSAGES_URL,
        data={
            "To": USER,
            "From": APP,
            "Body": "x",
            "Tags": '{"campaign_name": "spring_sale"}',
        },
        auth=AUTH,
    )
    assert response.status_code == 201
    thread = client.get(f"/api/numbers/{USER}/messages").json()
    assert thread["messages"][-1]["tags"] == ["campaign_name:spring_sale"]


def test_auto_tag_rules(client):
    client.put(
        "/api/settings",
        json={
            "auto_tag_rules": [
                {"tag": "otp", "body_regex": r"code is \d+"},
                {"tag": "vip", "to_suffix": "9999"},
            ]
        },
    )
    send_message(client, Body="Your code is 123456")
    send_message(client, To="+15550009999", Body="hello vip")
    send_message(client, To="+15550001111", Body="plain")

    threads = {t["number"]: t["tags"] for t in client.get("/api/numbers").json()}
    assert threads[USER] == ["otp"]
    assert threads["+15550009999"] == ["vip"]
    assert threads["+15550001111"] == []


def test_tag_search_filter(client):
    send_message(client, To="+15550001111", Body="alpha")
    send_message(client, To="+15550002222", Body="beta")
    sid = client.get("/api/numbers/+15550001111/messages").json()["messages"][0]["sid"]
    client.put(f"/api/messages/{sid}/tags", json={"tags": ["smoke"]})

    results = client.get("/api/numbers", params={"q": "tag:smoke"}).json()
    assert [t["number"] for t in results] == ["+15550001111"]
    # tag: combines with text search
    assert client.get("/api/numbers", params={"q": "tag:smoke beta"}).json() == []


# --- unread ---


def test_unread_counts_and_mark_read(client):
    send_message(client)
    send_message(client)
    numbers = client.get("/api/numbers").json()
    assert numbers[0]["unread_count"] == 2

    assert client.post(f"/api/numbers/{USER}/read").status_code == 204
    assert client.get("/api/numbers").json()[0]["unread_count"] == 0

    send_message(client, Body="new one")
    assert client.get("/api/numbers").json()[0]["unread_count"] == 1


# --- detail + delete ---


def test_message_detail(client):
    sent = send_message(client, Body="inspect me")
    detail = client.get(f"/api/messages/{sent['sid']}").json()
    assert detail["message"]["body"] == "inspect me"
    assert detail["twilio"]["num_segments"] == "1"  # Twilio shape preserved
    assert detail["raw_params"]["Body"] == "inspect me"


def test_dashboard_delete_any_status(client):
    sent = send_message(client)  # queued (non-terminal) — Twilio delete would 409
    assert client.delete(f"/api/messages/{sent['sid']}").status_code == 204
    assert client.get(f"/api/messages/{sent['sid']}").status_code == 404
    assert client.get("/api/numbers").json() == []


# --- retention ---


def test_retention_by_count(client):
    from app import db
    from app.retention import purge_once

    client.put("/api/settings", json={"retention_max_messages": 2})
    for index in range(4):
        send_message(client, Body=f"msg {index}")

    with Session(db.get_engine()) as session:
        assert purge_once(session) == 2

    thread = client.get(f"/api/numbers/{USER}/messages").json()
    assert [m["body"] for m in thread["messages"]] == ["msg 2", "msg 3"]


def test_retention_off_by_default(client):
    from app import db
    from app.retention import purge_once

    send_message(client)
    with Session(db.get_engine()) as session:
        assert purge_once(session) == 0


# --- export ---


def test_export_json_and_csv(client):
    send_message(client, Body="first")
    send_message(client, To="+15550002222", Body="second")
    sid = client.get(f"/api/numbers/{USER}/messages").json()["messages"][0]["sid"]
    client.put(f"/api/messages/{sid}/tags", json={"tags": ["exported"]})

    full = client.get("/api/export")
    assert full.headers["content-disposition"].endswith('.json"')
    assert len(full.json()) == 2

    thread_only = client.get("/api/export", params={"number": USER}).json()
    assert len(thread_only) == 1
    assert thread_only[0]["tags"] == ["exported"]

    csv_export = client.get("/api/export", params={"format": "csv"})
    assert csv_export.headers["content-type"].startswith("text/csv")
    lines = csv_export.text.strip().splitlines()
    assert lines[0].startswith("sid,direction,from_number")
    assert len(lines) == 3
    assert "exported" in csv_export.text


# --- webhook log filters ---


@pytest.fixture
def receiver(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if "fail" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(204)

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(handler))


def test_webhook_log_filters(client, receiver):
    client.put(
        "/api/settings",
        json={
            "simulate_delivery": True,
            "status_delay_ms": 0,
            "inbound_webhook_url": "http://app.test/fail",
        },
    )
    sent = send_message(client, StatusCallback="http://app.test/ok")
    from tests.conftest import wait_for_status

    wait_for_status(client, sent["sid"], "delivered")
    client.post(f"/api/numbers/{USER}/reply", json={"body": "hi"})

    assert client.get("/api/webhook-log", params={"kind": "inbound"}).json()["total"] == 1
    assert client.get("/api/webhook-log", params={"kind": "status_callback"}).json()["total"] == 3
    assert client.get("/api/webhook-log", params={"result": "error"}).json()["total"] == 1
    assert client.get("/api/webhook-log", params={"result": "success"}).json()["total"] == 3
    by_message = client.get("/api/webhook-log", params={"message_sid": sent["sid"]}).json()
    assert by_message["total"] == 3


# --- scheduled view ---


def test_scheduled_list_and_cancel(client):
    response = client.post(
        MESSAGES_URL,
        data={
            "To": USER,
            "From": APP,
            "Body": "later",
            "ScheduleType": "fixed",
            "SendAt": "2030-01-01T00:00:00Z",
        },
        auth=AUTH,
    )
    sid = response.json()["sid"]

    scheduled = client.get("/api/scheduled").json()
    assert [m["sid"] for m in scheduled] == [sid]
    assert scheduled[0]["send_at"] == "2030-01-01T00:00:00Z"

    canceled = client.post(f"/api/scheduled/{sid}/cancel")
    assert canceled.json()["status"] == "canceled"
    assert client.get("/api/scheduled").json() == []
    assert client.post(f"/api/scheduled/{sid}/cancel").status_code == 404


# --- dashboard token ---


def test_dashboard_token_guards_api(monkeypatch, client):
    from app.config import config

    monkeypatch.setattr(config, "dashboard_token", "sekret")

    assert client.get("/api/numbers").status_code == 401
    assert client.get("/api/health").status_code == 200  # probes stay open
    assert client.get("/api/numbers", headers={"X-Smspit-Token": "sekret"}).status_code == 200
    assert client.get("/api/numbers", params={"token": "sekret"}).status_code == 200
    # Twilio-shaped routes unaffected
    assert (
        client.post(
            MESSAGES_URL, data={"To": USER, "From": APP, "Body": "x"}, auth=AUTH
        ).status_code
        == 201
    )
