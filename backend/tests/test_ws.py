from tests.conftest import send_message


def test_message_created_event(client):
    with client.websocket_connect("/api/ws") as websocket:
        sent = send_message(client, To="+15550000009", Body="ping")
        event = websocket.receive_json()

    assert event["type"] == "message.created"
    assert event["data"]["number"] == "+15550000009"
    assert event["data"]["message"]["sid"] == sent["sid"]
    assert event["data"]["message"]["body"] == "ping"


def test_messages_cleared_events(client):
    send_message(client, To="+15550000001")

    with client.websocket_connect("/api/ws") as websocket:
        client.delete("/api/numbers/+15550000001/messages")
        event = websocket.receive_json()
        assert event == {"type": "messages.cleared", "data": {"number": "+15550000001"}}

        client.delete("/api/messages")
        event = websocket.receive_json()
        assert event == {"type": "messages.cleared", "data": {"number": None}}


def test_multiple_clients_receive_broadcasts(client):
    with (
        client.websocket_connect("/api/ws") as first,
        client.websocket_connect("/api/ws") as second,
    ):
        send_message(client)
        assert first.receive_json()["type"] == "message.created"
        assert second.receive_json()["type"] == "message.created"
