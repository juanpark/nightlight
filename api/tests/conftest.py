import os
import uuid

import pytest
from fastapi.testclient import TestClient

assert os.environ.get("FIRESTORE_EMULATOR_HOST"), "run tests via scripts/test_api.sh (Firestore emulator)"

from nightlight_api import actions, db, demo  # noqa: E402
from nightlight_api.auth import current_uid, owner_uid  # noqa: E402
from nightlight_api.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _private_home(tmp_path_factory, monkeypatch):
    """Every test runs with its own empty home folder, so nothing (above all the helper's install, uninstall and
    update code, whose paths come from the home folder) can touch a real installation on the machine running tests."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    yield


@pytest.fixture
def uid():
    return f"u_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(uid):
    app.dependency_overrides[current_uid] = lambda: uid
    app.dependency_overrides[owner_uid] = lambda: uid  # tests act as a signed-in owner
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def started(uid):
    demo.start(uid)
    return uid


def generation(uid):
    return db.user(uid).get().to_dict()["demoGeneration"]


def propose(uid, turn=None, device="pi-1", session="sess_test"):
    return actions.propose(uid, session_id=session, turn_id=turn or f"turn_{uuid.uuid4()}",
                           generation=generation(uid), action_type="rotate_logs", device_id=device, params={})


def device(uid, device_id="pi-1"):
    return db.device(uid, device_id).get().to_dict()


def trust(uid):
    return db.trust_doc(uid, "sim", "rotate_logs").get().to_dict()
