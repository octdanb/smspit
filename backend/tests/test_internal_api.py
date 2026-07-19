from tests.conftest import send_message


def test_numbers_aggregation(client):
    send_message(client, To="+15550000001", Body="first")
    send_message(client, To="+15550000001", Body="second")
    send_message(client, To="+15550000002", Body="other")

    response = client.get("/api/numbers")
    assert response.status_code == 200
    numbers = response.json()
    assert [n["number"] for n in numbers] == ["+15550000002", "+15550000001"]  # latest first

    thread = next(n for n in numbers if n["number"] == "+15550000001")
    assert thread["message_count"] == 2
    assert thread["last_message"]["body"] == "second"
    assert thread["last_message"]["direction"] == "outbound-api"


def test_thread_messages_chat_order_and_pagination(client):
    for i in range(3):
        send_message(client, To="+15550000001", Body=f"msg {i}")
    send_message(client, To="+15550000002", Body="unrelated")

    response = client.get("/api/numbers/+15550000001/messages")
    assert response.status_code == 200
    thread = response.json()
    assert thread["total"] == 3
    assert [m["body"] for m in thread["messages"]] == ["msg 0", "msg 1", "msg 2"]
    assert thread["messages"][0]["num_segments"] == 1  # internal API keeps ints

    response = client.get("/api/numbers/+15550000001/messages", params={"page_size": 2})
    thread = response.json()
    assert [m["body"] for m in thread["messages"]] == ["msg 1", "msg 2"]  # newest page, chat order

    response = client.get("/api/numbers/+15550000001/messages", params={"page_size": 2, "page": 1})
    assert [m["body"] for m in response.json()["messages"]] == ["msg 0"]


def test_clear_thread_and_all(client):
    send_message(client, To="+15550000001")
    send_message(client, To="+15550000002")

    response = client.delete("/api/numbers/+15550000001/messages")
    assert response.status_code == 204
    assert [n["number"] for n in client.get("/api/numbers").json()] == ["+15550000002"]

    response = client.delete("/api/messages")
    assert response.status_code == 204
    assert client.get("/api/numbers").json() == []
