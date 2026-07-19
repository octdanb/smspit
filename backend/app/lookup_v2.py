"""Twilio Lookup v2 emulation: GET /v2/PhoneNumbers/{number}.

Real parsing/formatting via the phonenumbers library. The
line_type_intelligence package returns "mobile" by default, overridable
per number in settings (lookup_line_types) so tests can exercise
"reject VoIP/landline" logic.
"""

import json

import phonenumbers
from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBasicCredentials
from phonenumbers import NumberParseException
from sqlmodel import Session

from .db import get_session, get_settings
from .twilio_api import require_basic_auth

router = APIRouter(prefix="/v2/PhoneNumbers")

PACKAGES = (
    "caller_name",
    "sim_swap",
    "call_forwarding",
    "line_status",
    "line_type_intelligence",
    "identity_match",
    "reassigned_number",
    "sms_pumping_risk",
    "phone_number_quality_score",
    "pre_fill",
)

PARSE_ERRORS = {
    NumberParseException.INVALID_COUNTRY_CODE: "INVALID_COUNTRY_CODE",
    NumberParseException.NOT_A_NUMBER: "NOT_A_NUMBER",
    NumberParseException.TOO_SHORT_AFTER_IDD: "TOO_SHORT",
    NumberParseException.TOO_SHORT_NSN: "TOO_SHORT",
    NumberParseException.TOO_LONG: "TOO_LONG",
}


@router.get("/{number:path}")
def lookup(
    number: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
    fields: str | None = Query(None, alias="Fields"),
    country_code: str | None = Query(None, alias="CountryCode"),
) -> dict:
    requested = {f.strip() for f in (fields or "").split(",") if f.strip()}
    result: dict = {
        "calling_country_code": None,
        "country_code": None,
        "phone_number": number,
        "national_format": None,
        "valid": False,
        "validation_errors": [],
        **{package: None for package in PACKAGES},
        "url": f"/v2/PhoneNumbers/{number}",
    }

    try:
        parsed = phonenumbers.parse(number, country_code)
    except NumberParseException as exc:
        result["validation_errors"] = [PARSE_ERRORS.get(exc.error_type, "NOT_A_NUMBER")]
        return result

    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    result["calling_country_code"] = str(parsed.country_code)
    result["country_code"] = phonenumbers.region_code_for_number(parsed)
    result["phone_number"] = e164
    result["national_format"] = phonenumbers.format_number(
        parsed, phonenumbers.PhoneNumberFormat.NATIONAL
    )
    if phonenumbers.is_valid_number(parsed):
        result["valid"] = True
    else:
        result["validation_errors"] = ["INVALID_LENGTH"]

    if "line_type_intelligence" in requested and result["valid"]:
        overrides = json.loads(get_settings(session).lookup_line_types or "{}")
        result["line_type_intelligence"] = {
            "type": overrides.get(e164, "mobile"),
            "carrier_name": "smspit mock carrier",
            "error_code": None,
            "mobile_country_code": "310",
            "mobile_network_code": "160",
        }
    return result
