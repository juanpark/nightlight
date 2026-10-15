"""Settings read from the environment. No secrets live in code."""

import os
from dataclasses import dataclass, field


def _list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    project_id: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "demo-nightlight")
    port: int = int(os.environ.get("PORT", "8080"))
    web_origins: list[str] = field(default_factory=lambda: _list("WEB_ORIGINS", "http://localhost:3000"))
    # Reset barrier lease and batch size.
    reset_lease_seconds: int = int(os.environ.get("RESET_LEASE_SECONDS", "60"))
    reset_batch_size: int = int(os.environ.get("RESET_BATCH_SIZE", "20"))
    # Trust: clean human-approved runs needed before a promotion offer.
    promotion_threshold: int = 3


settings = Settings()
