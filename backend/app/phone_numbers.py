"""Twilio IncomingPhoneNumbers emulation (2010-04-01): per-number webhook config.

The mock has no number inventory to purchase from — POST provisions whatever
PhoneNumber you give it. The SMS-relevant config subset is supported:
SmsUrl/SmsMethod, SmsFallbackUrl/Method, StatusCallback/Method.
"""

import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBasicCredentials
from sqlmodel import Session, col, select

from .db import get_session
from .errors import TwilioError, not_found
from .models import IncomingPhoneNumber, utcnow
from .twilio_api import require_basic_auth, rfc2822

router = APIRouter()

BASE = "/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers"


def number_to_json(number: IncomingPhoneNumber) -> dict:
    base_uri = f"/2010-04-01/Accounts/{number.account_sid}/IncomingPhoneNumbers/{number.sid}"
    return {
        "sid": number.sid,
        "account_sid": number.account_sid,
        "phone_number": number.phone_number,
        "friendly_name": number.friendly_name or number.phone_number,
        "sms_url": number.sms_url,
        "sms_method": number.sms_method,
        "sms_fallback_url": number.sms_fallback_url,
        "sms_fallback_method": number.sms_fallback_method,
        "status_callback": number.status_callback,
        "status_callback_method": number.status_callback_method,
        "capabilities": {"voice": False, "sms": True, "mms": True, "fax": False},
        "api_version": "2010-04-01",
        "date_created": rfc2822(number.date_created),
        "date_updated": rfc2822(number.date_updated),
        "uri": f"{base_uri}.json",
    }


def _apply_params(number: IncomingPhoneNumber, form) -> None:
    for param, attr in (
        ("FriendlyName", "friendly_name"),
        ("SmsUrl", "sms_url"),
        ("SmsFallbackUrl", "sms_fallback_url"),
        ("StatusCallback", "status_callback"),
    ):
        if param in form:
            setattr(number, attr, str(form[param]) or None)
    for param, attr in (
        ("SmsMethod", "sms_method"),
        ("SmsFallbackMethod", "sms_fallback_method"),
        ("StatusCallbackMethod", "status_callback_method"),
    ):
        if form.get(param):
            method = str(form[param]).upper()
            if method not in ("GET", "POST"):
                raise TwilioError(20001, f"{param} must be GET or POST.")
            setattr(number, attr, method)
    if number.friendly_name is None:
        number.friendly_name = ""


def find_by_number(session: Session, phone_number: str) -> IncomingPhoneNumber | None:
    return session.exec(
        select(IncomingPhoneNumber).where(IncomingPhoneNumber.phone_number == phone_number)
    ).first()


@router.post(f"{BASE}.json", status_code=201)
async def create_number(
    account_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    form = await request.form()
    phone_number = str(form.get("PhoneNumber") or "").strip()
    if not phone_number:
        raise TwilioError(21601, "PhoneNumber is required.")
    if find_by_number(session, phone_number) is not None:
        raise TwilioError(21452, f"{phone_number} is already provisioned.")
    number = IncomingPhoneNumber(
        sid="PN" + secrets.token_hex(16),
        account_sid=account_sid,
        phone_number=phone_number,
    )
    _apply_params(number, form)
    session.add(number)
    session.commit()
    session.refresh(number)
    return number_to_json(number)


@router.get(f"{BASE}.json")
def list_numbers(
    account_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    stmt = select(IncomingPhoneNumber).order_by(col(IncomingPhoneNumber.phone_number))
    if request.query_params.get("PhoneNumber"):
        stmt = stmt.where(IncomingPhoneNumber.phone_number == request.query_params["PhoneNumber"])
    numbers = session.exec(stmt).all()
    path = f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json"
    return {
        "incoming_phone_numbers": [number_to_json(n) for n in numbers],
        "page": 0,
        "page_size": max(len(numbers), 50),
        "first_page_uri": f"{path}?PageSize=50&Page=0",
        "previous_page_uri": None,
        "next_page_uri": None,
        "uri": path,
        "start": 0,
        "end": max(len(numbers) - 1, 0),
    }


def _get_number(session: Session, account_sid: str, sid: str) -> IncomingPhoneNumber:
    number = session.get(IncomingPhoneNumber, sid)
    if number is None:
        raise not_found(f"2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers/{sid}.json")
    return number


@router.get(f"{BASE}/{{sid}}.json")
def fetch_number(
    account_sid: str,
    sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    return number_to_json(_get_number(session, account_sid, sid))


@router.post(f"{BASE}/{{sid}}.json")
async def update_number(
    account_sid: str,
    sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    number = _get_number(session, account_sid, sid)
    _apply_params(number, await request.form())
    number.date_updated = utcnow()
    session.add(number)
    session.commit()
    session.refresh(number)
    return number_to_json(number)


@router.delete(f"{BASE}/{{sid}}.json", status_code=204)
def delete_number(
    account_sid: str,
    sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> None:
    session.delete(_get_number(session, account_sid, sid))
    session.commit()
