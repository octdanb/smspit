import base64
import hashlib
import hmac

from app.signature import compute_signature


def test_signature_matches_twilio_algorithm():
    auth_token = "12345"
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+14158675309",
        "Digits": "1234",
        "From": "+14158675309",
        "To": "+18005551212",
    }
    # Independent reconstruction of the documented algorithm:
    # URL + key/value pairs concatenated in sorted order, HMAC-SHA1, base64.
    payload = url + "".join(k + v for k, v in sorted(params.items()))
    expected = base64.b64encode(
        hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()

    assert compute_signature(auth_token, url, params) == expected


def test_signature_is_order_independent():
    token = "secret"
    url = "http://localhost/webhook"
    a = compute_signature(token, url, {"B": "2", "A": "1"})
    b = compute_signature(token, url, {"A": "1", "B": "2"})
    assert a == b


def test_signature_changes_with_token_and_params():
    url = "http://localhost/webhook"
    base = compute_signature("token", url, {"A": "1"})
    assert compute_signature("other", url, {"A": "1"}) != base
    assert compute_signature("token", url, {"A": "2"}) != base
