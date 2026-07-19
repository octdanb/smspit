"""X-Twilio-Signature computation (matches twilio.request_validator).

Algorithm: take the full request URL, append each POST param as key+value
(no separators) sorted by key, HMAC-SHA1 with the auth token, base64-encode.
Apps validating webhooks with Twilio's RequestValidator pass unchanged.
"""

import base64
import hashlib
import hmac


def compute_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    payload = url + "".join(key + value for key, value in sorted(params.items()))
    digest = hmac.new(auth_token.encode(), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()
