"""Live demo machines: leases are exclusive under concurrency, idempotent per visitor, limited per address; pool
tokens can't unpair the machine; the waiting-screen phases follow the real VM state. Compute calls are faked."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from nightlight_api import live
from nightlight_api.auth import POOL_DENY
from nightlight_api.config import settings
from nightlight_api.errors import ApiError


@pytest.fixture
def pool(monkeypatch):
    tag = uuid.uuid4().hex[:6]
    names = [f"nl-live-t{tag}-{n}" for n in range(1, 6)]
    monkeypatch.setattr(settings, "live_pool", [f"{n}=pool-{tag}-{i}" for i, n in enumerate(names, 1)])
    calls = []
    monkeypatch.setattr(live, "vm_command", lambda name, value: calls.append(("cmd", name, value)))
    monkeypatch.setattr(live, "vm_start", lambda name: calls.append(("start", name)))
    monkeypatch.setattr(live, "vm_stop", lambda name: calls.append(("stop", name)))
    monkeypatch.setattr(live, "vm_status", lambda name, max_age=0: "TERMINATED")
    monkeypatch.setattr(live, "mint_token", lambda uid, slot, lease_id: f"tok:{uid}:{lease_id}")
    yield names, calls
    for n in names:
        live.slots().document(n).delete()


def test_six_at_once_get_five_distinct_machines_and_one_clear_refusal(pool):
    names, calls = pool
    visitors = [f"v{i}" for i in range(6)]

    def ask(v):
        try:
            return live.lease(v, f"ip-{v}")
        except ApiError as e:
            return e

    with ThreadPoolExecutor(6) as ex:
        out = list(ex.map(ask, visitors))
    ok = [o for o in out if isinstance(o, dict)]
    refused = [o for o in out if isinstance(o, ApiError)]
    assert len({o["slot"] for o in ok}) == 5 and len(ok) == 5
    assert len(refused) == 1 and refused[0].status == 409 and refused[0].code == "live_all_busy"
    assert sorted(c[1] for c in calls if c[0] == "start") == sorted(names)


def test_same_visitor_gets_the_same_machine_back_as_resumed(pool):
    first = live.lease("v1", "ip1")
    again = live.lease("v1", "ip1")
    assert again["slot"] == first["slot"] and again["leaseId"] == first["leaseId"]
    assert first["resumed"] is False and again["resumed"] is True


def test_one_address_holds_at_most_live_per_ip(pool, monkeypatch):
    monkeypatch.setattr(settings, "live_per_ip", 2)
    live.lease("a", "same")
    live.lease("b", "same")
    with pytest.raises(ApiError) as e:
        live.lease("c", "same")
    assert e.value.status == 429


def test_expired_lease_token_stops_working(pool):
    got = live.lease("v1", "ip1")
    assert live.lease_live(got["slot"], got["leaseId"], max_age=0)
    live.slots().document(got["slot"]).update({"expiresAt": datetime.now(timezone.utc) - timedelta(seconds=1)})
    assert not live.lease_live(got["slot"], got["leaseId"], max_age=0)


@pytest.mark.parametrize("line,denied", [
    ("POST /api/devices/dev_x/remove", True), ("DELETE /api/devices/dev_x", True),
    ("POST /api/devices/enrol-code", True), ("GET /api/devices/pair/ABCD-EFGH", True),
    ("POST /api/devices/dev_x/revoke", True), ("POST /api/devices/dev_x/update", True),
    ("POST /api/expert/register/options", True), ("POST /api/settings", True),
    ("POST /api/chat/sessions", False), ("POST /api/devices/dev_x/permissions", False),
    ("POST /api/demo/live/reset", False), ("GET /api/devices/dev_x/knowledge", False),
])
def test_pool_tokens_cannot_unpair_or_replace_the_machine(line, denied):
    assert bool(POOL_DENY.search(line)) is denied


def test_phases_follow_the_machine():
    now = datetime.now(timezone.utc)
    d = {"command": "c1"}
    assert live._phase({**d, "restore": {"op": "r"}}, "RUNNING", None, None) == "stopping"
    assert live._phase({**d, "restore": {"op": "r"}}, "TERMINATED", None, None) == "restoring"
    assert live._phase(d, "STAGING", None, None) == "starting"
    assert live._phase(d, "RUNNING", ("resetting", "c1", now.timestamp()), None) == "reconnecting"
    assert live._phase(d, "RUNNING", ("ready", "c0", now.timestamp()), now) == "reconnecting"  # an older command
    assert live._phase(d, "RUNNING", ("ready", "c1", now.timestamp() - 5), now - timedelta(seconds=10)) == "reconnecting"
    assert live._phase(d, "RUNNING", ("ready", "c1", now.timestamp() - 5), now) == "ready"
