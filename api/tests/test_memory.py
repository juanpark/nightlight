"""Memory Bank (slice 7): explicit remember tool, one recall per turn, purge on reset, per-uid isolation.

No cloud: the Memory Bank `memories` surface is replaced by an in-memory fake keyed by scope.
"""

import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from nightlight_api import demo, memory
from nightlight_api.config import settings
from nightlight_api.main import app
from nightlight_api.auth import current_uid
from fake_llm import FakeLlm
from test_chat import ask, events, fake_model, new_session  # noqa: F401 - fake_model is an autouse fixture


class FakeMemories:
    def __init__(self):
        self.store: dict[str, list[str]] = {}
        self.epochs: dict[tuple[str, str], str] = {}  # (uid, fact) -> epoch it was saved under ("0" if seeded)
        self.calls: list[tuple] = []
        self.fail = False
        self.deferred = False  # purge returns before deleting (like the real long-running operation)

    def _check(self, name, scope=None):
        assert name == f"reasoningEngines/{settings.memory_bank_id}"
        assert scope is None or scope["app_name"] == "nightlight"
        if self.fail:
            raise RuntimeError("memory bank down")

    def create(self, *, name, fact, scope, config=None):
        self.calls.append(("create", scope["user_id"], fact, config))
        self._check(name, scope)
        self.store.setdefault(scope["user_id"], []).append(fact)
        self.epochs[(scope["user_id"], fact)] = scope["epoch"]
        return SimpleNamespace(done=True)

    def retrieve(self, *, name, scope, similarity_search_params=None, simple_retrieval_params=None, config=None):
        self.calls.append(("retrieve", scope["user_id"], similarity_search_params or simple_retrieval_params))
        self._check(name, scope)
        at = datetime(2026, 10, 16, tzinfo=timezone.utc)
        return iter([SimpleNamespace(memory=SimpleNamespace(fact=f, name=f"{name}/memories/m{i}", update_time=at))
                     for i, f in enumerate(self.store.get(scope["user_id"], []))
                     if self.epochs.get((scope["user_id"], f), "0") == scope["epoch"]])  # exact scope match

    def purge(self, *, name, filter, force=False, config=None):
        uid = re.fullmatch(r'scope\.user_id="([^"]+)"', filter).group(1)
        self.calls.append(("purge", uid, force, config))
        self._check(name)
        if not self.deferred:
            self.store.pop(uid, None)
        return SimpleNamespace(done=False)

    def count(self, kind):
        return sum(1 for c in self.calls if c[0] == kind)


@pytest.fixture
def mem(monkeypatch):
    fake = FakeMemories()
    monkeypatch.setattr(settings, "memory_bank_id", "1234567890")
    monkeypatch.setattr(memory, "_api", lambda: fake)
    memory._cache.clear()
    return fake


def _remember_then_answer(fact):
    """FakeLlm behavior: call remember(fact) once, then answer in text."""
    async def gen(llm_request, stream):
        done = [p.function_response for c in llm_request.contents for p in (c.parts or []) if p.function_response]
        if not done:
            part = types.Part(function_call=types.FunctionCall(name="remember", args={"fact": fact}))
        else:
            part = types.Part(text=f"Got it ({done[0].response.get('status')}).")
        yield LlmResponse(content=types.Content(role="model", parts=[part]), partial=False, turn_complete=True)
    return gen


# ------------------------------------------------------------------ unit level

def test_disabled_is_a_no_op(monkeypatch, uid):
    monkeypatch.setattr(settings, "memory_bank_id", "")
    monkeypatch.setattr(memory, "_api", lambda: pytest.fail("memory client used while disabled"))
    assert memory.remember(uid, "kids play Minecraft on weekends") == {"status": "off"}
    assert memory.recall(uid, "minecraft") == []
    assert memory.list_all(uid) == []
    assert memory.forget_all(uid) is False


def test_remember_scrubs_secrets_and_bounds_length(mem, uid):
    for secret in ("the wifi password: hunter2hunter2", "my token is ghp_" + "a" * 36, "email me at me@example.com"):
        assert memory.remember(uid, secret)["status"] == "refused"
    assert mem.store == {} and mem.count("create") == 0  # a secret never reaches Memory Bank, not even scrubbed

    out = memory.remember(uid, "  The kids   play Minecraft\non weekends ")
    assert out == {"status": "saved", "fact": "The kids play Minecraft on weekends"}
    long = memory.remember(uid, "word " * 400)
    assert long["status"] == "saved" and len(long["fact"]) <= settings.memory_fact_chars
    assert all(len(f) <= settings.memory_fact_chars for f in mem.store[uid])
    create = next(c for c in mem.calls if c[0] == "create")
    assert create[3]["wait_for_completion"] is True  # "saved" is only said once it is stored
    assert memory.remember(uid, "   ")["status"] == "refused"


def test_recall_scrubs_and_bounds_what_comes_back(mem, uid):
    mem.store[uid] = ["api_key=abcdef123456 is in the drawer", "x" * 1000, "kids play Minecraft"]
    facts = memory.recall(uid, "minecraft", top_k=5)
    assert "abcdef123456" not in " ".join(facts) and "[hidden]" in facts[0]
    assert all(len(f) <= settings.memory_fact_chars for f in facts)
    assert mem.calls[-1][2]["top_k"] == 5


def test_memory_errors_never_raise(mem, uid):
    mem.fail = True
    assert memory.remember(uid, "kids play Minecraft")["status"] == "error"
    assert memory.recall(uid, "anything") == []
    assert memory.list_all(uid) == []
    assert memory.forget_all(uid) is False


# ------------------------------------------------------------------ in a turn

def test_one_recall_per_turn_goes_into_the_instruction(client, started, mem):
    mem.store[started] = ["Never restart the game server on school nights {after 9}"]
    sid = new_session(client)
    ev = events(ask(client, sid, text="Is the game server okay?"))
    assert ev[-1]["type"] == "done" and ev[-1]["metrics"]["modelCalls"] == 3
    loads = mem.count("retrieve")
    assert 1 <= loads <= 2  # opening the session prefetches; the turn waits only if that hasn't landed yet
    assert "page_size" in mem.calls[0][2]  # a plain newest-first list, not a search per turn
    events(ask(client, sid, text="And the Pi?"))
    assert mem.count("retrieve") == loads  # later turns use the cached facts
    for call in FakeLlm.log:
        assert "remember" in call["tools"]
        assert "What you remember about this person" in call["system"]
        assert "school nights (after 9)" in call["system"] and "{after 9}" not in call["system"]
        assert "device facts win" in call["system"]


def test_disabled_turn_has_no_memory_tool_or_lookup(client, started, monkeypatch):
    monkeypatch.setattr(settings, "memory_bank_id", "")
    monkeypatch.setattr(memory, "_api", lambda: pytest.fail("memory client used while disabled"))
    sid = new_session(client)
    assert events(ask(client, sid))[-1]["type"] == "done"
    assert all("remember" not in c["tools"] and "remember" not in c["system"] for c in FakeLlm.log)


def test_continuation_does_no_lookup(client, started, mem):
    sid = new_session(client)
    action_id = next(e["actionId"] for e in events(ask(client, sid)) if e["type"] == "approval_request")
    cont = client.post(f"/api/actions/{action_id}/decide", json={"decision": "approve"}).json()["continuationTurnId"]
    before = mem.count("retrieve")
    assert events(client.post(f"/api/turns/{cont}/stream", json={}))[-1]["type"] == "done"
    assert mem.count("retrieve") == before


def test_model_saves_a_fact_with_the_remember_tool(client, started, mem):
    FakeLlm.behavior = _remember_then_answer("The kids play Minecraft on weekends")
    sid = new_session(client)
    ev = events(ask(client, sid, text="Remember: the kids play Minecraft on weekends"))
    assert ev[-1]["type"] == "done"
    assert mem.store[started] == ["The kids play Minecraft on weekends"]
    result = next(e for e in ev if e["type"] == "tool_result")
    assert result["name"] == "remember" and result["summary"].startswith("Saved: ")
    assert "saved" in "".join(e.get("delta", "") for e in ev)


def test_model_cannot_save_a_secret(client, started, mem):
    FakeLlm.behavior = _remember_then_answer("router password=SuperSecret99")
    sid = new_session(client)
    ev = events(ask(client, sid, text="remember my router login"))
    assert ev[-1]["type"] == "done" and mem.store == {}
    assert "SuperSecret99" not in str(ev)


def test_memory_failure_does_not_fail_the_turn(client, started, mem):
    mem.fail = True
    FakeLlm.behavior = _remember_then_answer("The kids play Minecraft on weekends")
    sid = new_session(client)
    ev = events(ask(client, sid))
    assert ev[-1]["type"] == "done"
    assert next(e for e in ev if e["type"] == "tool_result")["summary"].startswith("Couldn't: ")


def test_slow_recall_is_skipped(client, started, mem, monkeypatch):
    monkeypatch.setattr(settings, "memory_recall_seconds", 0.1)
    real_retrieve = mem.retrieve

    def slow(**kw):
        time.sleep(1)
        return real_retrieve(**kw)

    mem.retrieve = slow
    mem.store[started] = ["kids play Minecraft"]
    sid = new_session(client)
    assert events(ask(client, sid))[-1]["type"] == "done"
    assert all("What you remember about this person" not in c["system"] for c in FakeLlm.log)


# ------------------------------------------------------------------ reset and the API

def test_reset_keeps_an_owners_memories(started, mem):
    mem.store[started] = ["kids play Minecraft"]
    demo.reset(started)  # a signed-in owner (the default: fail safe) keeps what Nightlight remembered
    assert mem.store[started] == ["kids play Minecraft"]


def test_visitor_reset_purges_memories(started, mem):
    mem.store[started] = ["kids play Minecraft"]
    mem.store["someone_else"] = ["keep me"]
    demo.reset(started, anonymous=True)
    assert started not in mem.store and mem.store["someone_else"] == ["keep me"]
    assert ("purge", started, True, {"wait_for_completion": False}) in mem.calls
    mem.fail = True
    assert demo.reset(started, anonymous=True)["ok"] is True  # a purge failure never fails the reset


def test_memories_api_is_per_uid(client, uid, mem):
    other = uid + "_other"
    mem.store[uid] = ["kids play Minecraft on weekends"]
    mem.store[other] = ["other person's fact"]
    r = client.get("/api/me/memories")
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert [m["fact"] for m in r.json()["memories"]] == ["kids play Minecraft on weekends"]
    assert r.json()["memories"][0]["id"] == "m0" and r.json()["memories"][0]["updatedAt"].startswith("2026-10-16")
    assert client.delete("/api/me/memories").json() == {"ok": True}
    assert uid not in mem.store and mem.store[other] == ["other person's fact"]
    app.dependency_overrides[current_uid] = lambda: other
    assert [m["fact"] for m in client.get("/api/me/memories").json()["memories"]] == ["other person's fact"]


def test_memories_api_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "memory_bank_id", "")
    assert client.get("/api/me/memories").json() == {"enabled": False, "memories": []}
    assert client.delete("/api/me/memories").json() == {"ok": True}


def test_memories_api_needs_a_token():
    from fastapi.testclient import TestClient
    app.dependency_overrides.clear()
    assert TestClient(app).get("/api/me/memories").status_code == 401


def test_cache_follows_saves_and_purges(mem, uid):
    assert memory.cached(uid, 0) is None
    mem.store[uid] = ["kids play Minecraft on weekends"]
    assert memory.load(uid) == ["kids play Minecraft on weekends"]
    memory.remember(uid, "no restarts after 10pm")
    assert memory.cached(uid, 0)[0] == "no restarts after 10pm"
    memory.forget_all(uid)
    assert memory.cached(uid, memory.epoch(uid)) is None and memory.epoch(uid) == 1


def test_purge_is_started_not_awaited(mem, uid):  # review 7 #1
    memory.forget_all(uid)
    purge = next(c for c in mem.calls if c[0] == "purge")
    assert purge[3] == {"wait_for_completion": False}


def test_a_load_that_overlaps_a_purge_is_never_served(mem, uid):  # review 7 #2
    mem.store[uid] = ["old fact"]
    before = memory.epoch(uid)
    real_list = memory.list_all

    def list_then_purge(u, limit=50, ep=None):
        out = real_list(u, limit, ep)  # the old fact was read...
        memory.forget_all(u)  # ...then the person said "forget everything"
        return out

    memory.list_all = list_then_purge
    try:
        assert memory.load(uid, before) == []  # not returned
    finally:
        memory.list_all = real_list
    assert memory.cached(uid, memory.epoch(uid)) is None  # and not served from the cache under the new epoch


def test_a_save_from_before_a_purge_is_refused_or_undone(mem, uid):  # review 7 #3
    start = memory.epoch(uid)
    memory.forget_all(uid)
    assert memory.remember(uid, "kids play on weekends", start)["status"] == "error"  # stale turn: refused
    start = memory.epoch(uid)
    real_create = mem.create

    def create_then_purge(**kw):
        real_create(**kw)
        memory.forget_all(uid)  # the purge lands while the save is in flight

    mem.create = create_then_purge
    purges = mem.count("purge")
    assert memory.remember(uid, "kids play on weekends", start)["status"] == "error"
    assert mem.count("purge") == purges + 2  # the reset's purge, then ours: forgetting wins


def test_facts_are_invisible_as_soon_as_a_purge_starts(mem, uid):  # review 7 rev2 #1
    mem.store[uid] = ["old preference"]
    assert memory.load(uid) == ["old preference"]
    mem.deferred = True  # the purge is accepted but hasn't deleted anything yet
    memory.forget_all(uid)
    assert mem.store[uid] == ["old preference"]  # still stored...
    ep = memory.epoch(uid)
    assert memory.load(uid, ep) == [] and memory.cached(uid, ep) == []  # ...but never recalled or cached again
    assert memory.recall(uid, "preference") == [] and memory.list_all(uid) == []


def test_an_old_save_never_lands_in_a_newer_cache(mem, uid):  # review 7 rev3 #1
    start = memory.epoch(uid)
    real_create = mem.create

    def create_then_forget_and_reload(**kw):
        real_create(**kw)
        memory.forget_all(uid)  # purge lands right after the backend write...
        memory.load(uid)  # ...and a new turn loads the (empty) new-epoch cache

    mem.create = create_then_forget_and_reload
    memory.remember(uid, "old preference")  # no started epoch: the end-of-save check can't catch it
    assert memory.cached(uid, memory.epoch(uid)) == [] and memory.epoch(uid) == start + 1
