"""One error type for every API failure, rendered as {error, code, ...extra}."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_NAMES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 429: "rate_limited"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, **extra):
        super().__init__(code)
        self.status = status
        self.code = code
        self.extra = {k: v for k, v in extra.items() if v is not None}

    def body(self) -> dict:
        if self.status == 422:
            return {"error": "validation_error", "code": "invalid_body",
                    "detail": [{"loc": self.extra.get("loc", ["body"]), "msg": self.code}]}
        return {"error": _NAMES.get(self.status, "error"), "code": self.code, **self.extra}


class Outcome(ValueError):
    """A job that doesn't apply for a reason that is itself the answer (e.g. nothing to free): its code, plus what
    the caller can tell the person."""

    def __init__(self, code: str, **info):
        super().__init__(code)
        self.info = info


def not_found() -> ApiError:
    return ApiError(404, "not_found")


def invalid(field: str, msg: str) -> ApiError:
    return ApiError(422, msg, loc=["body", field])


def conflict(code: str, **extra) -> ApiError:
    return ApiError(409, code, **extra)


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    headers = {"Retry-After": str(exc.extra["retryAfter"])} if "retryAfter" in exc.extra else None
    return JSONResponse(exc.body(), status_code=exc.status, headers=headers)


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    detail = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()]
    return JSONResponse({"error": "validation_error", "code": "invalid_body", "detail": detail}, status_code=422)
