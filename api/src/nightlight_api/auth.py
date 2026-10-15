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


def current_uid(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "invalid_token") from None
    try:
        claims = fb_auth.verify_id_token(token, app=_app())
    except Exception:  # expired, revoked, malformed, wrong project: all the same to the caller
        raise ApiError(401, "invalid_token") from None
    return claims["uid"]
