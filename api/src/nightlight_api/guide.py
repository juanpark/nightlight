"""Nightlight's own guide (guide.yaml), so the agent repeats how the product works instead of inventing steps."""

from functools import lru_cache
from pathlib import Path

import yaml

from .config import settings


def _web() -> str:
    https = [o for o in settings.web_origins if o.startswith("https://")]
    return (https or settings.web_origins or ["the Nightlight app"])[-1]


@lru_cache(maxsize=1)
def topics() -> dict[str, dict]:
    return yaml.safe_load(Path(__file__).with_name("guide.yaml").read_text())


def read(topic: str) -> dict:
    t = topics().get((topic or "").strip().lower().replace(" ", "_").replace("-", "_"))
    if not t:
        return {"error": "unknown topic", "topics": {k: v["title"] for k, v in topics().items()}}
    return {"title": t["title"], "text": t["text"].replace("{web}", _web()).strip()}
