"""HTTP routes. Only these are public; the ADK agent runs in-process and is never exposed directly."""

from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from google.cloud import firestore
import re

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from . import __version__, actions, archive, db, expert, demo, knowledge, links, memory, notebook, playbooks, quota, release, real, runbooks, sim, trust as trustlib, turns, watch
from .auth import current_uid, owner_uid
from .config import settings
from .errors import ApiError, api_error_handler, conflict, invalid, not_found, validation_error_handler
from .ids import new_id
from .redact import scrub, scrub_value

app = FastAPI(title="Nightlight API", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_middleware(CORSMiddleware, allow_origins=settings.web_origins, allow_methods=["GET", "POST", "PUT", "DELETE"],
                   allow_headers=["Authorization", "Content-Type"], max_age=600)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartBody(Strict):
    template: Literal["home-pi", "empty"] = "home-pi"


class LayoutBody(Strict):
    x: int | None = Field(default=None, ge=-5000, le=5000)  # the map is a canvas: anywhere within reach
    y: int | None = Field(default=None, ge=-5000, le=5000)
    name: str | None = Field(default=None, min_length=1, max_length=40)
    tags: list[str] | None = Field(default=None, max_length=6)
    role: Literal["router", "printer", "fileshare", "smarthome", "server", "speaker", "computer", "other"] | None = None
    favorite: StrictBool | None = None  # starred by the owner: shown first and under the Favorites filter
    favoriteApps: list[Annotated[str, Field(min_length=1, max_length=80)]] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def short_tags(self):
        if self.tags is not None and not all(1 <= len(t.strip()) <= 20 for t in self.tags):
            raise ValueError("tags are 1 to 20 characters")
        return self


class WatchBody(Strict):
    name: str = Field(min_length=1, max_length=40)
    url: str = Field(min_length=8, max_length=300)
    tags: list[str] = Field(default_factory=list, max_length=6)


class PermissionsBody(Strict):
    diagnose: bool
    cleanup: bool = False
    updates: bool = True
    autoUpdate: bool = False
    logs: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,99}$")]] = Field(max_length=20)
    restart_container: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]] = \
        Field(max_length=20)
    restart_service: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,99}$")]] = \
        Field(max_length=20)


class IssueBody(Strict):
    state: Literal["new", "known", "snoozed"]
    days: int | None = Field(default=None, ge=1, le=90)


class Empty(Strict):
    pass


# Ids become Firestore path segments: letters, digits, '-' and '_' only, never empty.
Id = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")


class InjectBody(Strict):
    kind: Literal[tuple(sorted(sim.INCIDENTS))]
    deviceId: str = Id


class MessageBody(Strict):
    text: str = Field(min_length=1, max_length=2000)
    mode: Literal["quick", "investigate"] = "quick"  # investigate: a stronger model that digs in (slower)
    clientRequestId: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

    @model_validator(mode="after")
    def within_2kb(self):
        if len(self.text.encode()) > 2000:  # the documented limit is bytes, not characters
            raise ValueError("text must be at most 2,000 bytes")
        if not self.text.strip():
            raise ValueError("text must not be blank")
        return self


class DecideBody(Strict):
    decision: Literal["approve", "deny"]
    note: str | None = Field(default=None, max_length=280)


Level = Literal["ask", "ask_new", "auto"]


class TrustBody(Strict):
    level: Level
    deviceId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,40}$")
    svcId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,40}$")
    pinned: bool = False

    @model_validator(mode="after")
    def service_needs_device(self):
        if self.svcId and not self.deviceId:
            raise ValueError("svcId requires deviceId")
        return self


class PromotionBody(Strict):
    accept: bool
    offerId: str = Field(max_length=64)


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@app.post("/api/demo/start")
def demo_start(body: StartBody, uid: str = Depends(current_uid)):
    return demo.start(uid, body.template)


@app.post("/api/demo/template")
def demo_template(body: StartBody, uid: str = Depends(current_uid)):
    return demo.switch(uid, body.template)


@app.post("/api/devices/{device_id}/layout")
def device_layout(device_id: str, body: LayoutBody, uid: str = Depends(current_uid)):
    """Move a device on the map, or rename a real one. Position isn't device state: no version change."""
    if not re.fullmatch(r"[a-z0-9_-]{2,40}", device_id):
        raise not_found()
    ref = db.device(uid, device_id)
    name = scrub(body.name)[0] if body.name is not None else None
    tags = sorted({scrub(t.strip())[0] for t in body.tags}) if body.tags is not None else None
    if tags and any(len(t) > 20 for t in tags):  # hiding a secret can make a tag longer: check the stored value
        raise ApiError(422, "tag_too_long")

    @firestore.transactional
    def run(tx):
        user = (db.user(uid).get(transaction=tx).to_dict() or {})
        snap = ref.get(transaction=tx)
        d = snap.to_dict() if snap.exists else None
        if not d:
            raise not_found()
        if d.get("realm") != "real":  # sample devices: same barrier as every other demo write
            if user.get("demo", {}).get("state") != "ready":
                raise conflict("resetting", retryAfter=5)
            if d.get("demoGeneration") != user.get("demoGeneration"):
                raise not_found()
            if name is not None:
                raise ApiError(422, "sample_devices_keep_their_names")
        apps = None if body.favoriteApps is None else list(dict.fromkeys(body.favoriteApps))  # [] clears them
        update = {k: v for k, v in (("x", body.x), ("y", body.y), ("name", name), ("tags", tags),
                                    ("favorite", body.favorite), ("favoriteApps", apps)) if v is not None}
        if body.role is not None:
            if d.get("kind") != "watched":
                raise ApiError(422, "role_is_for_watched_things")
            watcher = (db.device(uid, d["watchedBy"]).get(transaction=tx).to_dict() or {}).get("name") \
                if d.get("watchedBy") else None  # a read, before this transaction's writes
            update.update(role=body.role, roleSetBy="user", purpose=real.role_purpose(body.role, watcher))
        if update:  # a name the person typed is theirs: the names switch never takes it back
            tx.update(ref, {**update, **({"nameFromSeen": False} if name is not None and d.get("nameFromSeen") else {})})
        return update

    return {"ok": True, **db.run_transaction(run)}


class LinkBody(Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    src: str = Field(alias="from", pattern=r"^[a-z0-9_-]{2,40}$")
    dst: str = Field(alias="to", pattern=r"^[a-z0-9_-]{2,40}$")
    kind: Literal["network", "backup", "depends", "power"]


@app.post("/api/links", status_code=201)
def link_put(body: LinkBody, uid: str = Depends(current_uid)):
    """Draw (or change the kind of) a line between two devices on the map. Layout only: no device is touched."""
    return links.put(uid, body.src, body.dst, body.kind)


@app.delete("/api/links/{link_id}")
def link_delete(link_id: str, uid: str = Depends(current_uid)):
    if not re.fullmatch(r"[a-z0-9_-]{2,40}__[a-z0-9_-]{2,40}", link_id):
        raise not_found()
    links.remove(uid, link_id)
    return {"ok": True}


@app.post("/api/devices/{device_id}/permissions")
def device_permissions(device_id: str, body: PermissionsBody, uid: str = Depends(owner_uid)):
    """The owner's switches for an app-managed device (the device itself chose to be managed from the app)."""
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id):
        raise not_found()
    return real.set_permissions(uid, device_id, body.model_dump())


@app.post("/api/devices/{device_id}/issues/{finding_id}")
def device_issue(device_id: str, finding_id: str, body: IssueBody, uid: str = Depends(current_uid)):
    """Mark one problem on a real device: needs a look (new), known (leaving it on purpose) or snoozed."""
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id) or not re.fullmatch(r"[A-Za-z0-9_.@:-]{1,140}", finding_id):
        raise not_found()
    if body.state == "snoozed" and not body.days:
        raise ApiError(422, "snooze_needs_days")
    return real.set_issue_state(uid, device_id, finding_id, body.state, body.days)


class NoteBody(Strict):
    text: str = Field(min_length=1, max_length=notebook.NOTE_CHARS)
    service: str | None = Field(default=None, min_length=1, max_length=100)  # a service on the device: id or name


def _generation(uid: str) -> int | None:
    return (db.user(uid).get().to_dict() or {}).get("demoGeneration")


@app.post("/api/devices/{device_id}/notes", status_code=201)
def add_note(device_id: str, body: NoteBody, uid: str = Depends(current_uid)):
    """Write a note in a device's notebook (Nightlight reads it before it looks into that device)."""
    if not re.fullmatch(r"[a-z0-9_-]{2,40}", device_id):
        raise not_found()
    return notebook.owner_add(uid, device_id, body.text, _generation(uid), body.service)


class ProfileBody(Strict):
    text: str = Field(min_length=1, max_length=notebook.PROFILE_CHARS)


@app.put("/api/devices/{device_id}/profile")
def put_profile(device_id: str, body: ProfileBody, uid: str = Depends(current_uid)):
    """The owner edits a device's profile (the notes Nightlight reads before it investigates)."""
    if not re.fullmatch(r"[a-z0-9_-]{2,40}", device_id):
        raise not_found()
    try:
        return notebook.set_profile(uid, device_id, body.text, "you", _generation(uid))
    except ValueError as e:
        raise invalid("text", str(e)) from None


@app.delete("/api/devices/{device_id}/notes/{note_id}")
def delete_note(device_id: str, note_id: str, uid: str = Depends(current_uid)):
    """Remove a note from a device's notebook (the owner's or Nightlight's)."""
    if not re.fullmatch(r"[a-z0-9_-]{2,40}", device_id) or not re.fullmatch(r"note_[0-9A-Za-z]{26}", note_id):
        raise not_found()
    return notebook.remove(uid, device_id, note_id)


@app.get("/api/devices/{device_id}/knowledge")
def device_knowledge(device_id: str, uid: str = Depends(current_uid)):
    """What Nightlight knows about a device: its profile, its notes (device-wide and per service) and its runbooks."""
    if not re.fullmatch(r"[a-z0-9_-]{2,40}", device_id):
        raise not_found()
    return knowledge.view(uid, device_id, _generation(uid))


@app.get("/api/devices/{device_id}/log")
def device_log(device_id: str, limit: int = 50, service: str | None = None, uid: str = Depends(current_uid)):
    """Every job that finished on a device, newest first; `service` (an app's id or name) keeps that app's jobs."""
    if not re.fullmatch(r"[a-z0-9_-]{2,40}", device_id):
        raise not_found()
    if not 1 <= limit <= knowledge.LOG_LIMIT:
        raise invalid("limit", "out_of_range")
    if service is not None and not 1 <= len(service) <= 120:
        raise invalid("service", "out_of_range")
    return {"jobs": knowledge.log(uid, device_id, _generation(uid), limit=limit, service=service)}


class RunbookBody(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=runbooks.TITLE_CHARS)
    when: str | None = Field(default=None, min_length=1, max_length=runbooks.WHEN_CHARS)


def _runbook_ids(device_id: str, runbook_id: str) -> None:
    if not re.fullmatch(r"[a-z0-9_-]{2,40}", device_id) or not re.fullmatch(r"rb_[0-9A-Za-z]{26}", runbook_id):
        raise not_found()


@app.post("/api/devices/{device_id}/runbooks/{runbook_id}")
def edit_runbook(device_id: str, runbook_id: str, body: RunbookBody, uid: str = Depends(current_uid)):
    """The owner renames a runbook or rewrites when it helps (its steps stay as Nightlight saved them)."""
    _runbook_ids(device_id, runbook_id)
    return runbooks.edit(uid, device_id, runbook_id, _generation(uid), body.title, body.when)


@app.delete("/api/devices/{device_id}/runbooks/{runbook_id}")
def delete_runbook(device_id: str, runbook_id: str, uid: str = Depends(current_uid)):
    _runbook_ids(device_id, runbook_id)
    return runbooks.remove(uid, device_id, runbook_id, _generation(uid))


class PlaybookRunBody(Strict):
    sessionId: str = Field(pattern=r"^sess_[0-9A-Z]{26}$")


@app.get("/api/devices/{device_id}/playbooks")
def device_playbooks(device_id: str, uid: str = Depends(current_uid)):
    """The playbooks this device can run, suggested ones (matching a current problem) first."""
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id):
        raise not_found()
    snap = db.device(uid, device_id).get()
    if not snap.exists:
        raise not_found()
    return {"playbooks": playbooks.offered(snap.to_dict())}


@app.post("/api/devices/{device_id}/playbooks/{book_id}/run", status_code=202)
def run_playbook(device_id: str, book_id: str, body: PlaybookRunBody, uid: str = Depends(current_uid)):
    """Run a playbook on a real device: its read-only checks now (no card), then cards for the clean-ups it finds."""
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id) or book_id not in playbooks.library():
        raise not_found()
    if not db.session(uid, body.sessionId).get().exists:
        raise not_found()
    try:
        a = playbooks.start(uid, device_id, book_id, session_id=body.sessionId, turn_id=new_id("pbrun"),
                            generation=_generation(uid))
    except ValueError as e:
        raise ApiError(409, str(e)) from None
    return {"actionId": a["id"], "status": a["status"]}


@app.post("/api/watches", status_code=201)
def add_watch(body: WatchBody, uid: str = Depends(owner_uid)):
    """Watch a public web address (website, game server status page, API): checked every 5 minutes."""
    return watch.add_watch(uid, body.name, body.url, sorted({scrub(t.strip())[0][:20] for t in body.tags if t.strip()}))


@app.delete("/api/watches/{watch_id}")
def remove_watch(watch_id: str, uid: str = Depends(current_uid)):
    if not re.fullmatch(r"w_[0-9a-z]{26}", watch_id):
        raise not_found()
    return watch.remove_watch(uid, watch_id)


@app.post("/internal/sweep")
def internal_sweep(request: Request):
    """Called by Cloud Scheduler only: the Google-signed token must name our audience and scheduler account."""
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not settings.sweep_audience or not token:
        raise ApiError(401, "invalid_token")
    try:
        claims = id_token.verify_oauth2_token(token, g_requests.Request(), audience=settings.sweep_audience)
    except Exception:
        raise ApiError(401, "invalid_token") from None
    if claims.get("email") != settings.sweep_invoker or not claims.get("email_verified"):
        raise ApiError(403, "forbidden")
    return watch.sweep()


@app.post("/api/demo/reset")
def demo_reset(body: Empty, uid: str = Depends(current_uid)):
    return demo.reset(uid)


@app.post("/api/demo/inject", status_code=201)
def demo_inject(body: InjectBody, uid: str = Depends(current_uid)):
    return demo.inject(uid, body.kind, body.deviceId)


@app.post("/api/actions/{action_id}/decide")
def decide(action_id: str, body: DecideBody, uid: str = Depends(current_uid)):
    if not re.fullmatch(r"act_[0-9a-f]{26}", action_id):
        raise not_found()
    note = scrub(body.note)[0] if body.note else None
    status, payload = actions.decide(uid, action_id, body.decision, note)
    return JSONResponse(payload, status_code=status)


def _trust_type(action_type: str) -> None:
    if action_type not in sim.ACTIONS:
        raise not_found()


@app.put("/api/trust/{action_type}")
def set_trust(action_type: str, body: TrustBody, uid: str = Depends(current_uid)):
    """Set a level globally for this job, or as a device or service override. Clamped to the job's ceiling."""
    _trust_type(action_type)
    level = trustlib._min(body.level, trustlib.ceiling(action_type))

    @firestore.transactional
    def run(tx):
        user_snap = db.user(uid).get(transaction=tx)
        if not user_snap.exists:
            raise not_found()
        user = user_snap.to_dict()
        if user.get("demo", {}).get("state") != "ready":
            raise conflict("resetting", retryAfter=5)
        ref = db.trust_doc(uid, "sim", action_type)
        snap = ref.get(transaction=tx)
        doc = snap.to_dict() if snap.exists else trustlib.new_doc(action_type, user["demoGeneration"])
        if body.deviceId:
            target = (db.services(uid, body.deviceId).document(body.svcId) if body.svcId
                      else db.device(uid, body.deviceId))
            if not target.get(transaction=tx).exists:
                raise not_found()
            tx.update(target, {f"trustOverride.{action_type}": level, f"trustPinned.{action_type}": body.pinned})
            return
        doc = {**doc, "level": level, "pinned": body.pinned}
        if body.pinned or level != "auto":
            doc["offer"] = None
        tx.set(ref, doc)

    db.run_transaction(run)
    return db.trust_doc(uid, "sim", action_type).get().to_dict()


@app.post("/api/trust/{action_type}/promotion")
def promotion(action_type: str, body: PromotionBody, uid: str = Depends(current_uid)):
    _trust_type(action_type)

    @firestore.transactional
    def run(tx):
        user_snap = db.user(uid).get(transaction=tx)
        ref = db.trust_doc(uid, "sim", action_type)
        snap = ref.get(transaction=tx)
        if not user_snap.exists:
            raise not_found()
        user = user_snap.to_dict()
        if user.get("demo", {}).get("state") != "ready":
            raise conflict("resetting", retryAfter=5)  # before not-found: trust docs vanish mid-reset
        if not snap.exists:
            raise conflict("offer_obsolete")
        updated = trustlib.accept_offer(snap.to_dict(), body.offerId, body.accept, user["demoGeneration"],
                                        firestore.SERVER_TIMESTAMP)
        if updated is None:
            raise conflict("offer_obsolete")
        tx.set(ref, updated)

    db.run_transaction(run)
    return db.trust_doc(uid, "sim", action_type).get().to_dict()


# ------------------------------------------------------------------ chat

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _client_ip(request: Request) -> str:
    """The visitor's address for the per-visitor limit.

    Cloud Run's front end appends the real client address to X-Forwarded-For, so the rightmost entry is the one
    Google added; anything to its left came from the client and is ignored.
    """
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    ip = forwarded[-1] if forwarded else (request.client.host if request.client else "")
    return quota.ip_hash(ip)


def _session_id_ok(session_id: str) -> None:
    if not re.fullmatch(r"sess_[0-9A-Z]{26}", session_id):
        raise not_found()


@app.post("/api/chat/sessions", status_code=201)
def chat_session(body: Empty, uid: str = Depends(current_uid)):
    memory.prefetch(uid)  # so the first answer doesn't wait for Memory Bank
    return turns.create_session(uid)


@app.post("/api/chat/sessions/{session_id}/messages")
def chat_message(session_id: str, body: MessageBody, request: Request, uid: str = Depends(current_uid)):
    _session_id_ok(session_id)
    turn_id = turns.accept_message(uid, session_id, body.text, body.clientRequestId, body.mode)
    claimed = turns.claim(uid, turn_id)
    return StreamingResponse(turns.stream(uid, claimed, _client_ip(request)), media_type="text/event-stream",
                             headers=SSE_HEADERS)


@app.post("/api/turns/{turn_id}/stream")
def turn_stream(turn_id: str, body: Empty, request: Request, uid: str = Depends(current_uid)):
    if not re.fullmatch(r"(turn_[0-9a-f-]{36}|cont_act_[0-9a-f]{26})", turn_id):
        raise not_found()
    try:
        claimed = turns.claim(uid, turn_id)
    except ApiError as e:
        # A follow-up waiting on a device job that never reported: once its time is up the job ends as failed and
        # this follow-up says so, instead of the browser waiting on a turn that would never exist.
        if e.code != "not_found" or not turn_id.startswith("cont_") \
                or not actions.expire_unreported(uid, turn_id.removeprefix("cont_")):
            raise
        claimed = turns.claim(uid, turn_id)
    return StreamingResponse(turns.stream(uid, claimed, _client_ip(request)), media_type="text/event-stream",
                             headers=SSE_HEADERS)


# ------------------------------------------------------------------ memory (what Nightlight remembers)

@app.get("/api/me/memories")
def my_memories(uid: str = Depends(current_uid)):
    return {"enabled": memory.enabled(), "memories": memory.list_all(uid)}


@app.delete("/api/me/memories")
def forget_my_memories(uid: str = Depends(current_uid)):
    return {"ok": memory.forget_all(uid) if memory.enabled() else True}


# ------------------------------------------------------------------ real devices (read-only helper)

class EnrolBody(Strict):
    code: str = Field(pattern=r"^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$")
    name: str = Field(min_length=1, max_length=40)


class Container(Strict):
    name: str = Field(max_length=64)
    image: str | None = Field(default=None, max_length=128)
    state: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=64)


class WatchResult(Strict):
    cid: str = Field(pattern=r"^[0-9a-f]{12}$")
    up: bool
    ms: int | None = Field(default=None, ge=0, le=60000)


TAG = r"^[0-9a-f]{20}$"
MACHINE = r"^[0-9a-f]{32}$"  # SHA-256 (first 32 hex) of the machine's own hardware id; never the id itself


class Peer(Strict):
    tag: str = Field(pattern=TAG)
    why: str = Field(pattern=f"^(time_machine|network_drive|service:({'|'.join(map(str, links.SERVICE_PORTS))}))$")


class Net(Strict):
    """Keyed fingerprints of private addresses (HMAC-SHA256 with the account's netKey, 20 hex characters): enough to
    match two devices of one account, never the address itself."""
    self: str | None = Field(default=None, pattern=TAG)
    selves: list[Annotated[str, Field(pattern=TAG)]] = Field(default_factory=list, max_length=8)  # one per interface
    gateway: str | None = Field(default=None, pattern=TAG)
    peers: list[Peer] = Field(default_factory=list, max_length=20)


class Found(Strict):
    """The helper's fixed words, plus an allow-listed maker and a model that is an Apple model or a product code
    (real.product), and, while the account shows them, the name the thing announces (real.found_name). Nothing can
    carry an address off the device."""
    cid: str = Field(pattern=r"^[0-9a-f]{12}$")
    guess: Literal[tuple(real.FOUND_GUESSES)]
    vendor: Literal[tuple(real.FOUND_VENDORS)] | None = None
    services: list[Literal[tuple(real.FOUND_SERVICES)]] = Field(default_factory=list, max_length=8)
    ports: list[Literal[tuple(real.FOUND_PORTS)]] = Field(default_factory=list, max_length=8)
    tag: str | None = Field(default=None, pattern=TAG)  # its address's keyed fingerprint (see Net), never the address
    hw: str | None = Field(default=None, pattern=TAG)  # its hardware address's keyed fingerprint, never the address
    name: str | None = Field(default=None, min_length=1, max_length=60, pattern=r"^[^\x00-\x1f\x7f]+$")
    maker: Literal[tuple(real.MAKERS)] | None = None
    model: str | None = Field(default=None, pattern=real.MODEL_CHARS)


class DiscoveriesBody(Strict):
    items: list[Found] = Field(max_length=30)


class AddFoundBody(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=40)  # none: the name it announced, else its guess


class SettingsBody(Strict):
    deviceNames: StrictBool


class HeartbeatBody(Strict):
    helperVersion: str = Field(max_length=16)
    os: str | None = Field(default=None, max_length=80)
    arch: str | None = Field(default=None, max_length=16)
    cpuPct: float | None = Field(default=None, ge=0, le=100)
    memPct: float | None = Field(default=None, ge=0, le=100)
    diskPct: float | None = Field(default=None, ge=0, le=100)
    uptimeSec: int | None = Field(default=None, ge=0)
    containers: list[Container] = Field(default_factory=list, max_length=50)
    failedUnits: list[str] = Field(default_factory=list, max_length=50)
    updatesPending: int | None = Field(default=None, ge=0, le=100000)
    # What the owner allowed on the device itself (job type -> targets). The server can't widen it.
    allowedJobs: dict[Literal["restart_container", "restart_service", "diagnose", "logs", "inspect", "fix", "update",
                              "expert"],
                      list[str]] = \
        Field(default_factory=dict)
    watchResults: list[WatchResult] = Field(default_factory=list, max_length=10)
    manage: Literal["app", "strict"] | None = None  # chosen on the device; the server can't change it
    macFolders: Literal["allowed", "declined"] | None = None  # a Mac's answer about its private folders
    failedAgents: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=20)
    safety: dict[Literal["passwordlessSudo", "sshPasswordLogin"], bool | None] = Field(default_factory=dict)
    net: Net | None = None  # for lines on the map; helpers before 0.9.20 send none
    machine: str | None = Field(default=None, pattern=MACHINE)  # lets a reinstall continue this device (0.9.33+)

    @model_validator(mode="after")
    def short_units(self):
        if any(len(u) > 128 for u in self.failedUnits):
            raise ValueError("unit names must be at most 128 characters")
        for kind, targets in self.allowedJobs.items():
            pattern = real.CONTAINER_NAME if kind == "restart_container" else real.TARGET_NAME
            if kind == "inspect" and not all(t in real.INSPECT for t in targets):
                raise ValueError("allowedJobs: unknown check")
            if kind == "fix" and not all(t in real.FIX for t in targets):
                raise ValueError("allowedJobs: unknown clean-up")
            if kind == "expert" and targets != ["on"]:
                raise ValueError("allowedJobs: expert is [\"on\"]")
            if kind == "update" and targets != ["signed"]:
                raise ValueError("allowedJobs: update is [\"signed\"]")
            if len(targets) > 20 or not all(pattern.fullmatch(t) for t in targets):
                raise ValueError("allowedJobs: at most 20 valid names per job")
        return self


class JobResultBody(Strict):
    ok: bool
    summary: str = Field(max_length=200)
    state: Literal["created", "restarting", "running", "removing", "paused", "exited", "dead"] | None = None
    output: str | None = Field(default=None, max_length=4000)  # what a read-only look found (scrubbed on the device)


def _remember_owner_hint(request: Request, uid: str) -> None:
    hint = getattr(request.state, "owner_hint", None)
    if hint:  # shown by `nightlight status` on the owner's devices, so they can check they joined the right account
        db.user(uid).set({"ownerHint": hint}, merge=True)


@app.post("/api/devices/enrol-code", status_code=201)
def enrol_code(body: Empty, request: Request, uid: str = Depends(owner_uid)):
    _remember_owner_hint(request, uid)
    return real.create_code(uid)


@app.post("/api/devices/{device_id}/revoke")
def revoke_device(device_id: str, body: Empty, uid: str = Depends(current_uid)):
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id):
        raise not_found()
    snap = db.device(uid, device_id).get()
    if snap.exists and (snap.to_dict() or {}).get("kind") == "watched":
        return real.remove_watched(uid, device_id)  # watched devices have no token: just stop watching
    return real.revoke(uid, device_id)


class PairStartBody(Strict):
    name: str = Field(min_length=1, max_length=40)
    os: str | None = Field(default=None, max_length=80)
    machine: str | None = Field(default=None, pattern=MACHINE)  # to offer "continue its history" (0.9.33+)
    via: Literal["installer", "command_line"] | None = None


class PairPollBody(Strict):
    code: str = Field(pattern=r"^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$")
    pollSecret: str = Field(min_length=20, max_length=64)


class PairDecideBody(Strict):
    approve: bool
    # Continue the device the preview offered (`continues`); the server finds it again itself, never by an id from here
    continueDevice: bool = False


def _pair_code(code: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}", code):
        raise not_found()
    return code


@app.post("/helper/pair/start", status_code=201)
def helper_pair_start(body: PairStartBody, request: Request):
    return real.pair_start(scrub(body.name)[0], scrub(body.os)[0] if body.os else None, _client_ip(request),
                           machine=body.machine, via=body.via)


@app.post("/helper/pair/poll")
def helper_pair_poll(body: PairPollBody):
    status, payload = real.pair_poll(body.code, body.pollSecret)
    return JSONResponse(payload, status_code=status)


@app.get("/api/devices/pair/{code}")
def pair_preview(code: str, uid: str = Depends(owner_uid)):
    return real.pair_preview(uid, _pair_code(code))


@app.post("/api/devices/pair/{code}")
def pair_decide(code: str, body: PairDecideBody, request: Request, uid: str = Depends(owner_uid)):
    _remember_owner_hint(request, uid)
    return real.pair_decide(uid, _pair_code(code), body.approve, body.continueDevice)


class LeaveBody(Strict):
    cleanup: Literal["full", "files_left"] | None = None


@app.post("/helper/leave")
def helper_leave(body: LeaveBody, request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    return real.leave(token, body.cleanup)


@app.post("/api/devices/{device_id}/remove", status_code=202)
def remove_device(device_id: str, body: Empty, uid: str = Depends(owner_uid)):
    """Remove a real device (the owner confirmed in the app): its helper uninstalls itself if it can; otherwise its
    access is cut now. Either way it leaves the map and is archived for 30 days."""
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id):
        raise not_found()
    return archive.request(uid, device_id)


@app.get("/api/devices/removed")
def removed_devices(uid: str = Depends(current_uid)):
    return {"devices": archive.removed(uid)}


@app.delete("/api/devices/{device_id}")
def forget_device(device_id: str, uid: str = Depends(owner_uid)):
    """Forget a removed device for good: its history, notes and activity are deleted now."""
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id):
        raise not_found()
    return archive.forget(uid, device_id)


@app.post("/helper/enrol", status_code=201)
def helper_enrol(body: EnrolBody):
    return real.enrol(body.code, scrub(body.name)[0])


@app.post("/helper/heartbeat")
def helper_heartbeat(body: HeartbeatBody, request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    # ?jobs=0: a report from the helper's command line (after a change made at the device): it never takes jobs,
    # which stay for the background service that runs them
    return real.heartbeat(token, body.model_dump(), take_jobs=request.query_params.get("jobs") != "0")


@app.post("/helper/jobs/{action_id}/result")
def helper_job_result(action_id: str, body: JobResultBody, request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    if not re.fullmatch(r"act_[0-9a-f]{26}", action_id):
        raise not_found()
    return actions.job_result(token, action_id, body.ok, body.summary, body.state, body.output)


@app.get("/helper/release")
def helper_release():
    """The signed helper version on offer ({version, sha256}); devices verify the signature themselves."""
    offer = release.latest()
    if not offer:
        raise not_found()
    return offer


@app.get("/helper/release/{name}")
def helper_release_file(name: str):
    data = release.read(name)
    if data is None:
        raise not_found()
    kind = "text/x-python; charset=utf-8" if name.endswith(".py") else "application/octet-stream"
    return Response(content=data, media_type=kind, headers={"Cache-Control": "no-store"})


@app.post("/api/devices/{device_id}/update", status_code=202)
def update_device(device_id: str, body: Empty, uid: str = Depends(owner_uid)):
    """Install the signed helper release on a real device (the owner's tap is the approval)."""
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id):
        raise not_found()
    try:
        offer = release.latest()
        a = actions.request(uid, "update_helper", device_id, {"version": offer["version"]} if offer else {},
                            session_id=None, turn_id="app_update", origin="app")
    except ValueError as e:
        raise (not_found() if str(e) == "not_applicable" else ApiError(409, str(e))) from None
    return {"actionId": a["id"], "status": a["status"], "version": a["params"]["version"]}


class SetupBody(Strict):
    preset: Literal["watch", "fix", "custom"]
    autoUpdate: bool = False
    macFolders: bool = False


@app.post("/api/devices/{device_id}/setup")
def device_setup(device_id: str, body: SetupBody, uid: str = Depends(owner_uid)):
    """The one-time setup card: what Nightlight may do on a newly connected device (asked once; Settings later)."""
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id):
        raise not_found()
    return real.device_setup(uid, device_id, body.preset, body.autoUpdate, body.macFolders)


@app.post("/api/devices/{device_id}/mac-folders", status_code=202)
def ask_mac_folders(device_id: str, body: Empty, uid: str = Depends(owner_uid)):
    """Ask a Mac (again) to let Nightlight measure its private folders: macOS asks on the Mac right away. A request
    still under way is that request."""
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id):
        raise not_found()
    try:
        return real.request_mac_folders(uid, device_id)
    except ValueError as e:
        raise ApiError(409, str(e)) from None


class PlaceBody(Strict):
    name: str = Field(min_length=1, max_length=40)


@app.post("/api/places/{place_id}")
def name_place(place_id: str, body: PlaceBody, uid: str = Depends(current_uid)):
    """Name a place: the devices behind one router (`place_id` is that router's fingerprint, as devices report it in
    net.gateway). Names are the owner's own words, scrubbed like every other label."""
    if not re.fullmatch(r"[0-9a-f]{20}", place_id):
        raise not_found()
    name = scrub(body.name.strip())[0]
    if not name or len(name) > 40:
        raise ApiError(422, "bad_name")
    places = db.user(uid).collection("places")

    @firestore.transactional
    def run(tx):
        # Only a router one of your own devices reports can be named, and at most MAX_PLACES of them.
        mine = {(d.to_dict().get("net") or {}).get("gateway") for d in db.devices(uid).get(transaction=tx)
                if not d.to_dict().get("archived")}
        if place_id not in mine:
            raise not_found()
        existing = places.document(place_id).get(transaction=tx)
        if not existing.exists and len(list(places.limit(MAX_PLACES).get(transaction=tx))) >= MAX_PLACES:
            raise ApiError(409, "too_many_places")
        tx.set(places.document(place_id), {"name": name, "at": firestore.SERVER_TIMESTAMP})

    db.run_transaction(run)
    return {"ok": True, "placeId": place_id, "name": name}


MAX_PLACES = 20


class DiscoverBody(Strict):
    everyDevice: bool = False


@app.post("/api/discover", status_code=202)
def discover_everywhere(body: DiscoverBody, uid: str = Depends(owner_uid)):
    """Look nearby on every network the owner has a device on: one device per router, or every device that can
    (`everyDevice`: more complete, since each sees mostly what it talked to lately). The tap is the approval."""
    return real.discover_everywhere(uid, body.everyDevice)


@app.get("/api/found")
def found(uid: str = Depends(current_uid)):
    """Found nearby, once per thing: merged across the devices that saw it, without your own devices."""
    return {"items": real.found_view(uid)}


@app.post("/api/devices/{device_id}/discover", status_code=202)
def discover_from_device(device_id: str, body: Empty, uid: str = Depends(owner_uid)):
    """Look for devices nearby from one of the owner's devices (the tap is the approval). The helper sends what it
    finds, without addresses, to Found nearby; strict devices only look when someone runs it there."""
    if not re.fullmatch(r"dev_[0-9a-z]{26}", device_id):
        raise not_found()
    try:
        a = real.request_discover(uid, device_id)
    except ValueError as e:
        raise (not_found() if str(e) == "not_applicable" else ApiError(409, str(e))) from None
    return {"actionId": a["id"], "status": a["status"]}


class SignBody(Strict):
    authenticatorData: str = Field(max_length=2000, pattern=r"^[A-Za-z0-9_-]+$")
    clientDataJSON: str = Field(max_length=4000, pattern=r"^[A-Za-z0-9_-]+$")
    signature: str = Field(max_length=400, pattern=r"^[A-Za-z0-9_-]+$")


@app.get("/api/expert")
def expert_status(uid: str = Depends(current_uid)):
    return expert.status(uid)


@app.post("/api/expert/register/options")
def expert_register_options(body: Empty, request: Request, uid: str = Depends(owner_uid)):
    return expert.register_options(uid, request.headers.get("origin"))


@app.post("/api/expert/register")
def expert_register(body: dict, uid: str = Depends(owner_uid)):
    """The new passkey's registration (WebAuthn), checked by the webauthn library."""
    return expert.register(uid, body)


@app.post("/api/actions/{action_id}/sign")
def sign_action(action_id: str, body: SignBody, uid: str = Depends(owner_uid)):
    """Approve an expert card with a passkey signature (the device checks it again before running anything)."""
    if not re.fullmatch(r"act_[0-9a-f]{26}", action_id):
        raise not_found()
    return expert.sign(uid, action_id, body.model_dump())


@app.get("/helper/expert-key")
def helper_expert_key(request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    t = real.tokens_ref().document(real._sha(token)).get().to_dict()
    if not t or t.get("revoked"):
        raise ApiError(401, "invalid_token")
    return expert.key_for_device(t["uid"])


@app.post("/helper/discoveries")
def helper_discoveries(body: DiscoveriesBody, request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    items, _ = scrub_value([i.model_dump() for i in body.items])
    for it in items:
        it["maker"], it["model"] = real.product(it.get("maker"), it.get("model"))
    return real.save_discoveries(token, items)


@app.post("/api/discoveries/{helper_id}/{cid}/add", status_code=201)
def add_found(helper_id: str, cid: str, body: AddFoundBody, uid: str = Depends(current_uid)):
    if not re.fullmatch(r"dev_[0-9a-z]{26}", helper_id) or not re.fullmatch(r"[0-9a-f]{12}", cid):
        raise not_found()
    return real.add_found(uid, helper_id, cid, scrub(body.name)[0] if body.name else None)


@app.post("/api/settings")
def account_settings(body: SettingsBody, uid: str = Depends(owner_uid)):
    """The owner's account switches. `deviceNames: false` stops keeping the names things nearby announce and removes
    the ones already kept."""
    return real.set_device_names(uid, body.deviceNames)


@app.post("/helper/jobs/claim")
def helper_claim(body: Empty, request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    return real.claim(token)


@app.post("/helper/jobs/wait")
def helper_wait(body: Empty, request: Request):
    """The work channel: held up to 25 s, answered as soon as this device has approved work (ADR 0003)."""
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    try:  # the helper asks to be answered by the time its next report is due (at most 25 s)
        hold = float(request.query_params.get("hold", real.WAIT_SECONDS))
    except ValueError:
        hold = real.WAIT_SECONDS
    return real.wait_for_jobs(token, hold)
