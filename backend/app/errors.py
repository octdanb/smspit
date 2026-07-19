"""Twilio-shaped error envelope: {code, message, more_info, status}."""

from fastapi import Request
from fastapi.responses import JSONResponse


class TwilioError(Exception):
    def __init__(self, code: int, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)

    def to_response(self) -> JSONResponse:
        headers = {}
        if self.http_status == 401:
            headers["WWW-Authenticate"] = 'Basic realm="Twilio API"'
        return JSONResponse(
            status_code=self.http_status,
            content={
                "code": self.code,
                "message": self.message,
                "more_info": f"https://www.twilio.com/docs/errors/{self.code}",
                "status": self.http_status,
            },
            headers=headers,
        )


def auth_error() -> TwilioError:
    return TwilioError(20003, "Authentication Error - No credentials provided", 401)


def not_found(sid: str) -> TwilioError:
    return TwilioError(20404, f"The requested resource /{sid} was not found", 404)


async def twilio_error_handler(request: Request, exc: TwilioError) -> JSONResponse:
    return exc.to_response()
