import re

from tests.conftest import AUTH, MESSAGES_URL, send_message

RFC2822 = re.compile(r"^[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} \+0000$")


def test_create_message_shape(client):
    data = send_message(client, Body="hello world")

    assert re.fullmatch(r"SM[0-9a-f]{32}", data["sid"])
    assert data["account_sid"] == AUTH[0]
    assert data["api_version"] == "2010-04-01"
    assert data["body"] == "hello world"
    assert data["from"] == "+15557654321"
    assert data["to"] == "+15551234567"
    assert data["direction"] == "outbound-api"
    assert data["status"] == "queued"
    # Twilio serializes these numerics as strings.
    assert data["num_segments"] == "1"
    assert data["num_media"] == "0"
    assert data["price"] is None
    assert data["price_unit"] == "USD"
    assert data["error_code"] is None
    assert RFC2822.match(data["date_created"])
    assert data["date_sent"] is None
    assert data["uri"] == f"/2010-04-01/Accounts/{AUTH[0]}/Messages/{data['sid']}.json"
    assert data["subresource_uris"]["media"].endswith(f"/Messages/{data['sid']}/Media.json")


def test_create_computes_segments(client):
    data = send_message(client, Body="a" * 161)
    assert data["num_segments"] == "2"


def test_media_message_gets_mm_sid(client):
    response = client.post(
        MESSAGES_URL,
        data={
            "To": "+15551234567",
            "From": "+15557654321",
            "Body": "pic",
            "MediaUrl": ["https://example.com/a.png", "https://example.com/b.png"],
        },
        auth=AUTH,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["sid"].startswith("MM")
    assert data["num_media"] == "2"


def test_missing_auth_is_twilio_401(client):
    response = client.post(MESSAGES_URL, data={"To": "+1", "From": "+2", "Body": "x"})
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == 20003
    assert body["status"] == 401
    assert body["more_info"].endswith("/20003")


def test_validation_errors(client):
    cases = [
        ({"From": "+15557654321", "Body": "x"}, 21604),
        ({"To": "+15551234567", "Body": "x"}, 21603),
        ({"To": "+15551234567", "From": "+15557654321"}, 21602),
        ({"To": "+15551234567", "From": "+15557654321", "Body": "a" * 1601}, 21617),
    ]
    for data, code in cases:
        response = client.post(MESSAGES_URL, data=data, auth=AUTH)
        assert response.status_code == 400, data
        assert response.json()["code"] == code


def test_list_pagination(client):
    sids = [send_message(client, Body=f"msg {i}")["sid"] for i in range(5)]

    response = client.get(MESSAGES_URL, params={"PageSize": 2}, auth=AUTH)
    assert response.status_code == 200
    page = response.json()
    assert [m["sid"] for m in page["messages"]] == [sids[4], sids[3]]  # newest first
    assert page["page"] == 0
    assert page["page_size"] == 2
    assert page["previous_page_uri"] is None
    assert "PageToken=PA" in page["next_page_uri"]

    # Follow next_page_uri like a Twilio SDK would.
    response = client.get(page["next_page_uri"], auth=AUTH)
    page2 = response.json()
    assert [m["sid"] for m in page2["messages"]] == [sids[2], sids[1]]

    response = client.get(page2["next_page_uri"], auth=AUTH)
    page3 = response.json()
    assert [m["sid"] for m in page3["messages"]] == [sids[0]]
    assert page3["next_page_uri"] is None


def test_list_filters_by_to_and_from(client):
    send_message(client, To="+15550000001")
    send_message(client, To="+15550000002")

    response = client.get(MESSAGES_URL, params={"To": "+15550000001"}, auth=AUTH)
    messages = response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["to"] == "+15550000001"

    response = client.get(MESSAGES_URL, params={"From": "+15557654321"}, auth=AUTH)
    assert len(response.json()["messages"]) == 2


def test_fetch_message(client):
    sid = send_message(client)["sid"]
    response = client.get(f"/2010-04-01/Accounts/{AUTH[0]}/Messages/{sid}.json", auth=AUTH)
    assert response.status_code == 200
    assert response.json()["sid"] == sid


def test_fetch_unknown_message_is_twilio_404(client):
    response = client.get(f"/2010-04-01/Accounts/{AUTH[0]}/Messages/SM{'0' * 32}.json", auth=AUTH)
    assert response.status_code == 404
    assert response.json()["code"] == 20404
