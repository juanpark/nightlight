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
    from . import live
    if live.pool_slot(claims.get("uid")):
        raise ApiError(401, "lease_ended")  # a pool account itself never signs in; visits have their own identity
    visit = live.visit_account(claims.get("uid"))
    if visit or "nl_lease" in claims:
        # A visit to a live demo machine: its own Firebase identity, mapped by the server (liveVisits) to the pool
        # account whose data it sees, only with a custom token for THIS slot's current lease.
        if not visit or claims.get("nl_slot") != visit[0] or claims.get("nl_lease") != visit[2] \
                or (claims.get("firebase") or {}).get("sign_in_provider") != "custom":
            raise ApiError(401, "lease_ended")
        slot = visit[0]
        claims = {**claims, "uid": visit[1], "visit_uid": claims.get("uid")}  # every route acts on the account
        line = f"{request.method} {request.url.path}"
        changes = request.method != "GET"
        d = live.lease_doc(slot, str(claims["nl_lease"]), fresh=changes)
        if d is None:
            raise ApiError(401, "lease_ended")
        if POOL_DENY.search(line):
            raise ApiError(403, "live_demo_machine")
        if not request.url.path.startswith("/api/demo/live"):
            if changes and (d.get("restore") or d.get("wiping")):
                raise ApiError(409, "machine_resetting", retryAfter=10)  # no writes race the wipe of a Start fresh
            # And every transaction this request makes re-checks the lease (not wiping, same visit) together with its
            # write: a request admitted just before the lease ended can't write into the next visit.
            from . import db
            holder = db.fence_holder()
            if holder is not None:
                holder["check"] = live.visitor_check(slot, str(claims["nl_lease"]))
    return claims


# What a visitor on a live demo machine may not do by route (the same changes are refused again where they're made:
# live.forbid_pool, and actions for remove/update cards): unpair, replace or outlive the machine for the next visitor.
POOL_DENY = re.compile(r"^(POST /api/devices/enrol-code|\w+ /api/devices/pair/"
                       r"|POST /api/devices/[^/]+/(remove|revoke|update|permissions|setup|mac-folders)$"
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


def anonymous(request: Request) -> bool:
    """Whether this is a one-click (anonymous) account: such a request never reaches real devices."""
    return (_claims(request).get("firebase") or {}).get("sign_in_provider") == "anonymous"


def mask_email(email: str | None) -> str | None:
    """'juanpark@gmail.com' -> 'ju***@gmail.com': enough for the owner to recognise, not enough to read off."""
    if not email or "@" not in email:
        return None
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"
