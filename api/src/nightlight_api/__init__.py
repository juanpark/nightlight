"""Nightlight API: a house-sitter for home and small-office servers."""

__version__ = "0.1.0"


def main() -> None:
    import uvicorn

    from .config import settings

    uvicorn.run("nightlight_api.main:app", host="0.0.0.0", port=settings.port)
