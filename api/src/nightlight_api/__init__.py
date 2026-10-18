"""Nightlight API: a house-sitter for home and small-office servers."""

import os

# The app's version (web and API share it; the repo's VERSION file) and the exact build (git commit), both stamped by
# scripts/deploy_api.sh. The helper on devices has its own version (helper/nightlight_helper.py).
__version__ = os.environ.get("APP_VERSION", "dev")
__build__ = os.environ.get("GIT_SHA", "")


def main() -> None:
    import uvicorn

    from .config import settings

    uvicorn.run("nightlight_api.main:app", host="0.0.0.0", port=settings.port)
