"""Scrub secrets from any text before it is stored or shown to the model.

Best effort by design: patterns catch the common shapes (private keys, tokens, passwords in config lines, cloud keys,
WireGuard keys, bearer headers, email addresses). The real protection is upstream: device helpers never send
credentials, and the demo uses synthetic data. Every replacement is counted so the UI can say "2 secrets hidden".
"""

import re

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
                               re.S)),
    ("bearer", re.compile(r"(?i)\b(bearer|authorization:)\s+[A-Za-z0-9._~+/=-]{8,}")),
    ("aws_key", re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    # key: value / key=value forms, including prefixed names such as DB_PASSWORD; plain sentences that merely
    # mention a password are left alone.
    ("assignment", re.compile(r"(?i)\b([A-Za-z0-9_-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key"
                              r"|private[_-]?key|client[_-]?secret))\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)")),
    ("wireguard_key", re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{42,43}=(?![A-Za-z0-9+/=])")),
    ("url_credentials", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]


def scrub(text: str) -> tuple[str, int]:
    """Return (clean text, number of secrets hidden)."""
    if not text:
        return text, 0
    count = 0

    def mask(kind):
        def _m(m):
            nonlocal count
            count += 1
            if kind == "assignment":
                return f"{m.group(1)}{m.group(2)}[hidden]"
            if kind == "bearer":
                return f"{m.group(1)} [hidden]"
            if kind == "url_credentials":
                return f"{m.group(1)}[hidden]@"
            return "[hidden]"
        return _m

    for kind, pattern in _PATTERNS:
        text = pattern.sub(mask(kind), text)
    return text, count


def scrub_value(value):
    """Scrub every string inside a JSON-like value. Returns (clean value, count)."""
    total = 0

    def walk(v):
        nonlocal total
        if isinstance(v, str):
            clean, n = scrub(v)
            total += n
            return clean
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(value), total
