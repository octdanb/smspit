import httpx
import pytest

from app import media
from tests.conftest import AUTH, MESSAGES_URL

JPEG_BYTES = b"\xff\xd8\xff\xe0fakejpegdata"


@pytest.fixture
def media_source(monkeypatch):
    """Serve fake media bytes for MediaUrl fetches."""
    state = {"fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["fail"]:
            raise httpx.ConnectError("unreachable")
        return httpx.Response(200, content=JPEG_BYTES, headers={"Content-Type": "image/jpeg"})

    monkeypatch.setattr(media, "_transport", httpx.MockTransport(handler))
    return state


def send_with_media(client, urls):
    response = client.post(
        MESSAGES_URL,
        data={
            "To": "+15551234567",
            "From": "+15557654321",
            "Body": "with media",
            "MediaUrl": urls,
        },
        auth=AUTH,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_media_list_and_metadata(client):
    sent = send_with_media(client, ["https://example.com/a.jpg", "https://example.com/b.png"])

    listing = client.get(sent["subresource_uris"]["media"], auth=AUTH).json()
    assert len(listing["media_list"]) == 2
    item = listing["media_list"][0]
    assert item["sid"].startswith("ME")
    assert item["parent_sid"] == sent["sid"]
    assert item["content_type"] in ("image/jpeg", "image/png")

    metadata = client.get(item["uri"], auth=AUTH).json()
    assert metadata["sid"] == item["sid"]


def test_media_content_redirect_and_bytes(client, media_source):
    sent = send_with_media(client, ["https://example.com/a.jpg"])
    item = client.get(sent["subresource_uris"]["media"], auth=AUTH).json()["media_list"][0]

    bare_url = item["uri"].removesuffix(".json")
    redirect = client.get(bare_url, auth=AUTH, follow_redirects=False)
    assert redirect.status_code == 302
    assert redirect.headers["location"] == f"http://localhost:8025/api/media/{item['sid']}"

    content = client.get(f"/api/media/{item['sid']}")
    assert content.status_code == 200
    assert content.content == JPEG_BYTES
    assert content.headers["content-type"].startswith("image/jpeg")


def test_unreachable_media_serves_placeholder(client, media_source):
    media_source["fail"] = True
    sent = send_with_media(client, ["https://example.com/gone.jpg"])
    item = client.get(sent["subresource_uris"]["media"], auth=AUTH).json()["media_list"][0]

    content = client.get(f"/api/media/{item['sid']}")
    assert content.status_code == 200
    assert content.headers["content-type"].startswith("image/png")  # placeholder
    assert content.content == media.PLACEHOLDER_PNG


def test_delete_media(client):
    sent = send_with_media(client, ["https://example.com/a.jpg"])
    item = client.get(sent["subresource_uris"]["media"], auth=AUTH).json()["media_list"][0]

    response = client.delete(item["uri"], auth=AUTH)
    assert response.status_code == 204

    assert client.get(sent["subresource_uris"]["media"], auth=AUTH).json()["media_list"] == []
    message = client.get(
        f"/2010-04-01/Accounts/{AUTH[0]}/Messages/{sent['sid']}.json", auth=AUTH
    ).json()
    assert message["num_media"] == "0"


def test_unknown_media_404s(client):
    response = client.get(
        f"/2010-04-01/Accounts/{AUTH[0]}/Messages/SM{'0' * 32}/Media/ME{'0' * 32}.json",
        auth=AUTH,
    )
    assert response.status_code == 404
    assert response.json()["code"] == 20404
