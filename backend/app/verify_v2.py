"""Twilio Verify v2 emulation: /v2/Services, Verifications, VerificationCheck.

Only the sms channel is functional. Generated codes are recorded as real SMS
messages, so they appear in the dashboard thread and are picked up by
/api/numbers/{number}/latest-code.
"""

import json
import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBasicCredentials
from sqlmodel import Session, col, select

from . import inbound, lifecycle
from .db import get_session, get_settings
from .errors import TwilioError, not_found
from .models import Verification, VerifyService, utcnow
from .twilio_api import parse_bool, require_basic_auth
from .ws import manager

router = APIRouter(prefix="/v2/Services")

MAX_CHECK_ATTEMPTS = 5
MAX_SEND_ATTEMPTS = 5
ALPHA_SENDER = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9 _&+-]{1,11}$")


def iso(dt: datetime) -> str:
    return dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def service_to_json(service: VerifyService) -> dict:
    return {
        "sid": service.sid,
        "account_sid": service.account_sid,
        "friendly_name": service.friendly_name,
        "code_length": service.code_length,
        "custom_code_enabled": service.custom_code_enabled,
        "lookup_enabled": service.lookup_enabled,
        "skip_sms_to_landlines": service.skip_sms_to_landlines,
        "dtmf_input_required": service.dtmf_input_required,
        "tts_name": service.tts_name,
        "psd2_enabled": service.psd2_enabled,
        "do_not_share_warning_enabled": service.do_not_share_warning_enabled,
        "date_created": iso(service.date_created),
        "date_updated": iso(service.date_updated),
        "url": f"/v2/Services/{service.sid}",
    }


def verification_to_json(verification: Verification) -> dict:
    return {
        "sid": verification.sid,
        "service_sid": verification.service_sid,
        "account_sid": verification.account_sid,
        "to": verification.to,
        "channel": verification.channel,
        "status": verification.status,
        "valid": verification.status == "approved",
        "amount": None,
        "payee": None,
        "sna": None,
        "lookup": {},
        "send_code_attempts": json.loads(verification.send_attempts or "[]"),
        "date_created": iso(verification.date_created),
        "date_updated": iso(verification.date_updated),
        "url": f"/v2/Services/{verification.service_sid}/Verifications/{verification.sid}",
    }


def _get_service(session: Session, sid: str) -> VerifyService:
    service = session.get(VerifyService, sid)
    if service is None:
        raise not_found(f"v2/Services/{sid}")
    return service


def _apply_service_params(service: VerifyService, form) -> None:
    if form.get("FriendlyName"):
        name = str(form["FriendlyName"])
        if len(name) > 32:
            raise TwilioError(60200, "FriendlyName must be 32 characters or fewer.")
        service.friendly_name = name
    if form.get("CodeLength"):
        length = int(form["CodeLength"])
        if not 4 <= length <= 10:
            raise TwilioError(60200, "CodeLength must be between 4 and 10.")
        service.code_length = length
    for param, attr in (
        ("CustomCodeEnabled", "custom_code_enabled"),
        ("LookupEnabled", "lookup_enabled"),
        ("SkipSmsToLandlines", "skip_sms_to_landlines"),
        ("DtmfInputRequired", "dtmf_input_required"),
        ("Psd2Enabled", "psd2_enabled"),
        ("DoNotShareWarningEnabled", "do_not_share_warning_enabled"),
    ):
        if param in form:
            setattr(service, attr, parse_bool(str(form[param])))
    if form.get("TtsName"):
        service.tts_name = str(form["TtsName"])


@router.post("", status_code=201)
@router.post("/", status_code=201, include_in_schema=False)
async def create_service(
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    form = await request.form()
    if not form.get("FriendlyName"):
        raise TwilioError(60200, "FriendlyName is required.")
    service = VerifyService(
        sid="VA" + secrets.token_hex(16),
        account_sid=get_settings(session).account_sid,
        friendly_name="",
    )
    _apply_service_params(service, form)
    session.add(service)
    session.commit()
    session.refresh(service)
    return service_to_json(service)


@router.get("")
@router.get("/", include_in_schema=False)
def list_services(
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    services = session.exec(select(VerifyService).order_by(col(VerifyService.sid))).all()
    return {
        "services": [service_to_json(s) for s in services],
        "meta": {
            "page": 0,
            "page_size": 50,
            "first_page_url": "/v2/Services?PageSize=50&Page=0",
            "previous_page_url": None,
            "next_page_url": None,
            "url": "/v2/Services?PageSize=50&Page=0",
            "key": "services",
        },
    }


@router.get("/{service_sid}")
def fetch_service(
    service_sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    return service_to_json(_get_service(session, service_sid))


@router.post("/{service_sid}")
async def update_service(
    service_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    service = _get_service(session, service_sid)
    _apply_service_params(service, await request.form())
    service.date_updated = utcnow()
    session.add(service)
    session.commit()
    session.refresh(service)
    return service_to_json(service)


@router.delete("/{service_sid}", status_code=204)
def delete_service(
    service_sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> None:
    session.delete(_get_service(session, service_sid))
    session.commit()


def _sender_for(service: VerifyService) -> str:
    if ALPHA_SENDER.match(service.friendly_name or ""):
        return service.friendly_name
    return "Verify"


def _find_pending(session: Session, service_sid: str, to: str) -> Verification | None:
    return session.exec(
        select(Verification)
        .where(
            Verification.service_sid == service_sid,
            Verification.to == to,
            Verification.status == "pending",
        )
        .order_by(col(Verification.date_created).desc())
    ).first()


def _expire_if_due(session: Session, verification: Verification) -> bool:
    if verification.expires_at < utcnow():
        verification.status = "expired"
        verification.date_updated = utcnow()
        session.add(verification)
        session.commit()
        return True
    return False


@router.post("/{service_sid}/Verifications", status_code=201)
async def start_verification(
    service_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    service = _get_service(session, service_sid)
    form = await request.form()
    to = str(form.get("To") or "").strip()
    channel = str(form.get("Channel") or "").strip()
    custom_code = str(form.get("CustomCode") or "").strip()

    if not to:
        raise TwilioError(60200, "To is required.")
    if channel != "sms":
        raise TwilioError(60200, f"Channel '{channel or '(none)'}' is not supported (sms only).")
    if custom_code and not service.custom_code_enabled:
        raise TwilioError(60200, "CustomCode is not enabled for this service.")

    settings = get_settings(session)
    verification = _find_pending(session, service_sid, to)
    if verification is not None and _expire_if_due(session, verification):
        verification = None

    if verification is None:
        code = custom_code or "".join(
            secrets.choice("0123456789") for _ in range(service.code_length)
        )
        verification = Verification(
            sid="VE" + secrets.token_hex(16),
            service_sid=service_sid,
            account_sid=service.account_sid,
            to=to,
            channel="sms",
            code=code,
            expires_at=utcnow() + timedelta(seconds=settings.verify_ttl_seconds),
        )
        event = "verification.created"
    else:
        if custom_code:
            verification.code = custom_code
        event = "verification.updated"

    attempts = json.loads(verification.send_attempts or "[]")
    if len(attempts) >= MAX_SEND_ATTEMPTS:
        raise TwilioError(60203, "Max send attempts reached.", http_status=429)
    attempts.append(
        {"attempt_sid": "VL" + secrets.token_hex(16), "channel": "sms", "time": iso(utcnow())}
    )
    verification.send_attempts = json.dumps(attempts)
    verification.date_updated = utcnow()
    session.add(verification)
    session.commit()
    session.refresh(verification)

    message = await inbound.record_message(
        session,
        account_sid=service.account_sid,
        direction="outbound-api",
        from_number=_sender_for(service),
        to_number=to,
        body=f"Your {service.friendly_name} verification code is: {verification.code}",
        status="queued",
    )
    if settings.simulate_delivery:
        lifecycle.start(message.sid)

    await manager.broadcast(
        event, {"number": to, "verification": verification_to_json(verification)}
    )
    return verification_to_json(verification)


@router.get("/{service_sid}/Verifications/{sid_or_to}")
def fetch_verification(
    service_sid: str,
    sid_or_to: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    _get_service(session, service_sid)
    verification = _lookup(session, service_sid, sid_or_to)
    if verification is None:
        raise not_found(f"v2/Services/{service_sid}/Verifications/{sid_or_to}")
    return verification_to_json(verification)


def _lookup(session: Session, service_sid: str, sid_or_to: str) -> Verification | None:
    if sid_or_to.startswith("VE"):
        verification = session.get(Verification, sid_or_to)
        if verification is not None and verification.service_sid == service_sid:
            return verification
        return None
    return _find_pending(session, service_sid, sid_or_to)


@router.post("/{service_sid}/Verifications/{sid_or_to}")
async def update_verification(
    service_sid: str,
    sid_or_to: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    """Status=canceled cancels a pending verification."""
    _get_service(session, service_sid)
    form = await request.form()
    if str(form.get("Status") or "").lower() != "canceled":
        raise TwilioError(60200, "Status must be 'canceled'.")
    verification = _lookup(session, service_sid, sid_or_to)
    if verification is None or verification.status != "pending":
        raise not_found(f"v2/Services/{service_sid}/Verifications/{sid_or_to}")
    verification.status = "canceled"
    verification.date_updated = utcnow()
    session.add(verification)
    session.commit()
    session.refresh(verification)
    await manager.broadcast(
        "verification.updated",
        {"number": verification.to, "verification": verification_to_json(verification)},
    )
    return verification_to_json(verification)


@router.post("/{service_sid}/VerificationCheck")
async def check_verification(
    service_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    _get_service(session, service_sid)
    form = await request.form()
    code = str(form.get("Code") or "").strip()
    to = str(form.get("To") or "").strip()
    verification_sid = str(form.get("VerificationSid") or "").strip()

    if not code:
        raise TwilioError(60200, "Code is required.")
    if not to and not verification_sid:
        raise TwilioError(60200, "Either To or VerificationSid is required.")

    verification = _lookup(session, service_sid, verification_sid or to)
    if verification is None or verification.status != "pending":
        raise not_found(f"v2/Services/{service_sid}/VerificationCheck")
    if _expire_if_due(session, verification):
        raise not_found(f"v2/Services/{service_sid}/VerificationCheck")
    if verification.check_attempts >= MAX_CHECK_ATTEMPTS:
        verification.status = "max_attempts_reached"
        verification.date_updated = utcnow()
        session.add(verification)
        session.commit()
        await manager.broadcast(
            "verification.updated",
            {"number": verification.to, "verification": verification_to_json(verification)},
        )
        raise TwilioError(60202, "Max check attempts reached.", http_status=429)

    if code == verification.code:
        verification.status = "approved"
    else:
        verification.check_attempts += 1
    verification.date_updated = utcnow()
    session.add(verification)
    session.commit()
    session.refresh(verification)

    await manager.broadcast(
        "verification.updated",
        {"number": verification.to, "verification": verification_to_json(verification)},
    )
    result = verification_to_json(verification)
    result.pop("send_code_attempts", None)
    result.pop("lookup", None)
    result["sna_attempts_error_codes"] = []
    return result
