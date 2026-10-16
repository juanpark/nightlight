"""The caller's uid comes only from a verified Firebase ID token. Nothing in a request body can choose it."""

from functools import lru_cache

import firebase_admin
from fastapi import Request
from firebase_admin import auth as fb_auth

from .config import settings
from .errors import ApiError


@lru_cache
def _app():
    return firebase_admin.initialize_app(options={"projectId": settings.project_id})


def _claims(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "invalid_token") from None
    try:
        claims = fb_auth.verify_id_token(token, app=_app())
    except Exception:  # expired, revoked, malformed, wrong project: all the same to the caller
        raise ApiError(401, "invalid_token") from None
    return claims


def current_uid(request: Request) -> str:
    return _claims(request)["uid"]


def owner_uid(request: Request) -> str:
    """A signed-in (not one-click demo) account: real devices stay linked to it even if browser storage is cleared."""
    claims = _claims(request)
    if (claims.get("firebase") or {}).get("sign_in_provider") == "anonymous":
        raise ApiError(403, "sign_in_required")
    request.state.owner_hint = mask_email(claims.get("email"))
    return claims["uid"]


def mask_email(email: str | None) -> str | None:
    """'juanpark@gmail.com' -> 'ju***@gmail.com': enough for the owner to recognise, not enough to read off."""
    if not email or "@" not in email:
        return None
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"
