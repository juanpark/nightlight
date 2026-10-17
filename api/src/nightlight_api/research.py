"""Web research for the agent: one Gemini call grounded with Google Search, for errors and symptoms the checks don't
explain. Budgeted like every model call (plus the search fee), capped per person per day, and the question is
scrubbed first. What comes back is web content: evidence to weigh, never instructions."""

from datetime import datetime, timezone

from google.cloud import firestore
from google.genai import types

from . import db, quota
from .config import settings
from .errors import ApiError
from .redact import scrub

import re

_PRIVATE = [(re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[address]"),
            (re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b"), "[hardware address]"),
            (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[email]"),
            (re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b"), "[address]")]

PER_DAY = 20
SEARCH_FEE = 0.035  # Google Search grounding list price per grounded prompt (USD), counted on top of the tokens
ASK = ("Answer for someone fixing their own home or small-office computer. Be concrete: the most likely causes, "
       "how to confirm each one, and safe fixes. At most 6 short bullets. Question: ")


def _count(uid: str) -> None:
    ref = db.user(uid).collection("quota").document(f"research_{datetime.now(timezone.utc):%Y%m%d}")

    @firestore.transactional
    def run(tx):
        n = (ref.get(transaction=tx).to_dict() or {}).get("count", 0)
        if n >= PER_DAY:
            raise ApiError(429, "research_limit")
        tx.set(ref, {"count": n + 1})

    db.run_transaction(run)


def search(uid: str, ip: str, question: str, fence=None, client=None) -> dict:
    clean, _ = scrub(question or "")
    for pattern, word in _PRIVATE:  # nothing that identifies the person's network goes to a search engine
        clean = pattern.sub(word, clean)
    clean = " ".join(clean.split())[:500]
    if not clean:
        return {"status": "error", "reason": "nothing to search for"}
    try:
        _count(uid)
    except ApiError:
        return {"status": "error", "reason": f"the daily limit of {PER_DAY} web searches is reached"}
    reserved = quota.reserve(uid, ip, None, fence, settings.c_max + SEARCH_FEE)
    actual = None
    try:
        from .agent import _client
        r = (client or _client()).models.generate_content(
            model=settings.model, contents=ASK + clean,
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())],
                                               max_output_tokens=900))
        cost = quota.cost_of(r.usage_metadata)
        actual = None if cost is None else cost + SEARCH_FEE
        gm = r.candidates[0].grounding_metadata if r.candidates else None
        sources = [{"title": c.web.title, "url": c.web.uri} for c in (gm.grounding_chunks or [])
                   if getattr(c, "web", None)][:5] if gm else []
        answer, _ = scrub(r.text or "")
        return {"status": "done", "question": clean, "answer": answer[:2500], "sources": sources}
    except Exception as e:  # research never breaks a turn
        return {"status": "error", "reason": f"the search didn't work ({type(e).__name__})"}
    finally:
        quota.reconcile(reserved, actual)
