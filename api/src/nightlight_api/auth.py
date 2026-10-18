"""The caller's uid comes only from a verified Firebase ID token. Nothing in a request body can choose it."""

import re
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
    if "nl_lease" in claims:  # a live demo machine's pool account: valid only while that lease lasts
        from . import live
        if not live.lease_live(str(claims.get("nl_slot")), str(claims["nl_lease"])):
            raise ApiError(401, "lease_ended")
        if POOL_DENY.search(f"{request.method} {request.url.path}"):
            raise ApiError(403, "live_demo_machine")
    return claims


# What a visitor on a live demo machine may not do: things that would unpair, replace or outlive the machine for the
# next visitor (remove/forget/revoke it, pair other devices, self-update, register a passkey, account settings).
POOL_DENY = re.compile(r"^(POST /api/devices/enrol-code|\w+ /api/devices/pair/|POST /api/devices/[^/]+/(remove|revoke|update)$"
                       r"|DELETE /api/devices/[^/]+$|POST /api/expert/register|POST /api/settings$)")


def current_uid(request: Request) -> str:
    return _claims(request)["uid"]


def live_lease(request: Request) -> tuple[str, str]:
    """(slot, lease id) of a live demo machine's token; anything else is not a lease holder."""
    claims = _claims(request)
    if "nl_lease" not in claims:
        raise ApiError(403, "not_live_demo")
    return str(claims["nl_slot"]), str(claims["nl_lease"])


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
