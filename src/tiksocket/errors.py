from __future__ import annotations


class TikSocketError(Exception):
    code = "error"
    status = 500

    def __init__(self, message: str = "", code: str | None = None):
        if code:
            self.code = code
        super().__init__(message or self.code)

    def to_dict(self) -> dict:
        return {"error": self.code, "message": str(self)}


class NotConnected(TikSocketError):
    code = "not_connected"
    status = 409


class LoggedOut(TikSocketError):
    code = "logged_out"
    status = 409


class CaptchaRequired(TikSocketError):
    code = "captcha"
    status = 429


class RateLimited(TikSocketError):
    code = "rate_limited"
    status = 429


class Unavailable(TikSocketError):
    code = "unavailable"
    status = 502


class PageChanged(TikSocketError):
    code = "changed"
    status = 502


class BadMedia(TikSocketError):
    code = "bad_media"
    status = 400


class PublishFailed(TikSocketError):
    code = "failed"
    status = 502


class RequestPending(TikSocketError):
    code = "request_pending"
    status = 409


class NotDelivered(TikSocketError):
    code = "not_delivered"
    status = 409


class NotFound(TikSocketError):
    code = "not_found"
    status = 404


class BadInput(TikSocketError):
    code = "bad_input"
    status = 400


class LoginExpired(TikSocketError):
    code = "qr_expired"
    status = 410


ERRORS = {cls.code: cls for cls in (NotConnected, LoggedOut, CaptchaRequired, RateLimited, Unavailable, PageChanged,
                                    BadMedia, PublishFailed, RequestPending, NotDelivered, NotFound, BadInput,
                                    LoginExpired)}


def from_code(code: str, message: str = "") -> TikSocketError:
    cls = ERRORS.get(code)
    return cls(message) if cls else TikSocketError(message or code, code=code)
