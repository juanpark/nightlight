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
    # key: value / key=value forms, quoted or not (YAML, .env, JSON), including prefixed names such as DB_PASSWORD;
    # plain sentences that merely mention a password are left alone.
    ("assignment", re.compile(r"""(?i)(["']?\b[A-Za-z0-9_.-]*(?:password|passwd|pwd|secret|token|api[_-]?key"""
                              r"""|access[_-]?key|private[_-]?key|client[_-]?secret|credentials?)\b["']?)(\s*[:=]\s*)"""
                              r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s,;}\]]+)""")),
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
                quote = m.group(3)[0] if m.group(3)[:1] in "\"'" else ""
                return f"{m.group(1)}{m.group(2)}{quote}[hidden]{quote}"
            if kind == "bearer":
                return f"{m.group(1)} [hidden]"
            if kind == "url_credentials":
                return f"{m.group(1)}[hidden]@"
            return "[hidden]"
        return _m

    for kind, pattern in _PATTERNS:
        text = pattern.sub(mask(kind), text)
    return text, count


SENSITIVE_KEY = re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key"
                           r"|client[_-]?secret|credentials?|authorization|cookie)")


def scrub_value(value):
    """Scrub a JSON-like value: values under sensitive keys are hidden whole; every other string is scrubbed.

    Returns (clean value, count).
    """
    total = 0

    def walk(v, key=None):
        nonlocal total
        if key is not None and SENSITIVE_KEY.search(str(key)) and v not in (None, "", [], {}):
            total += 1
            return "[hidden]"
        if isinstance(v, str):
            clean, n = scrub(v)
            total += n
            return clean
        if isinstance(v, dict):
            return {k: walk(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(value), total


class StreamScrubber:
    """Scrub text that arrives in chunks, so a secret split across two chunks is still caught.

    Text is released only once it is HOLD characters behind the newest input (and never from inside an unfinished
    private-key block); everything released has been scrubbed in the context of what followed it.
    """

    HOLD = 160

    def __init__(self):
        self.raw = ""
        self.sent = ""

    def _safe(self, final: bool) -> str:
        clean, _ = scrub(self.raw)
        if final:
            return clean
        cut = len(clean) - self.HOLD
        begin = clean.rfind("-----BEGIN")
        if begin != -1 and "-----END" not in clean[begin:]:
            cut = min(cut, begin)
        return clean[:max(cut, 0)]

    def push(self, chunk: str) -> str:
        """Add raw text; return the next scrubbed piece that is safe to show (may be empty)."""
        self.raw += chunk
        safe = self._safe(final=False)
        if not safe.startswith(self.sent):
            return ""  # an earlier piece changed under new context: hold everything until the end
        piece = safe[len(self.sent):]
        self.sent += piece
        return piece

    def finish(self, final_raw: str | None = None) -> tuple[str, str]:
        """Return (remaining piece to show, full scrubbed text that was shown)."""
        if final_raw is not None:
            self.raw = final_raw
        full = self._safe(final=True)
        if full.startswith(self.sent):
            piece = full[len(self.sent):]
            self.sent = full
            return piece, full
        # Already-shown text no longer matches (a secret straddled the hold window). What was shown was itself
        # scrubbed, so keep it and append nothing that could repeat or reveal: the stored text equals the shown text.
        return "", self.sent
