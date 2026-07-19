"""OTP / verification-code extraction from message bodies."""

import re

# 4-8 digit runs on word boundaries; (?<![.\d-]) avoids matching pieces of
# longer numbers, decimals, or phone-number fragments.
DEFAULT_PATTERN = re.compile(r"(?<![\d.-])(\d{4,8})(?![\d.-])")


def extract_code(body: str, regex: str | None = None) -> str | None:
    """Return the verification code in a message body, or None.

    A custom regex overrides the default; its first capture group (or the
    whole match) is the code.
    """
    if regex:
        match = re.search(regex, body)
        if match is None:
            return None
        return match.group(1) if match.groups() else match.group(0)
    match = DEFAULT_PATTERN.search(body)
    return match.group(1) if match else None
