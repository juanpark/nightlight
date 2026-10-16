"""The signed helper release the API offers to devices. The file and its signature are copied in at deploy time
(scripts/deploy_api.sh); the signing key never leaves the maintainer's machine. Devices check the signature
themselves against the key built into the helper they already run, so this server can offer, never forge."""

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from .config import settings

FILE, SIG = "nightlight_helper.py", "nightlight_helper.py.sig"


def _dir() -> Path:
    return Path(settings.release_dir) if settings.release_dir else Path(__file__).with_name("release")


@lru_cache(maxsize=1)
def latest() -> dict | None:
    """{version, sha256} of the release on offer, or None when this deployment carries none."""
    f, s = _dir() / FILE, _dir() / SIG
    if not f.is_file() or not s.is_file():
        return None
    data = f.read_bytes()
    m = re.search(rb'^VERSION = "([0-9]+(?:\.[0-9]+)*)"$', data, re.M)
    return {"version": m.group(1).decode(), "sha256": hashlib.sha256(data).hexdigest()} if m else None


def read(name: str) -> bytes | None:
    return (_dir() / name).read_bytes() if name in (FILE, SIG) and latest() else None


def newer(a: str | None, b: str | None) -> bool:
    """True when version a is newer than b."""
    def key(v):
        try:
            return tuple(int(x) for x in str(v).split("."))
        except ValueError:
            return ()
    return bool(a) and key(a) > key(b)
