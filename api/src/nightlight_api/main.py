"""HTTP routes. Only these are public; the ADK agent runs in-process and is never exposed directly."""

from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from google.cloud import firestore
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import __version__, actions, db, demo, memory, quota, real, sim, trust as trustlib, turns, watch
from .auth import current_uid, owner_uid
from .config import settings
from .errors import ApiError, api_error_handler, conflict, not_found, validation_error_handler
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
    x: int | None = Field(default=None, ge=0, le=2000)
    y: int | None = Field(default=None, ge=0, le=2000)
    name: str | None = Field(default=None, min_length=1, max_length=40)
    tags: list[str] | None = Field(default=None, max_length=6)

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
        update = {k: v for k, v in (("x", body.x), ("y", body.y), ("name", name), ("tags", tags)) if v is not None}
        if update:
            tx.update(ref, update)
        return update

    return {"ok": True, **db.run_transaction(run)}


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
    turn_id = turns.accept_message(uid, session_id, body.text, body.clientRequestId)
    claimed = turns.claim(uid, turn_id)
    return StreamingResponse(turns.stream(uid, claimed, _client_ip(request)), media_type="text/event-stream",
                             headers=SSE_HEADERS)


@app.post("/api/turns/{turn_id}/stream")
def turn_stream(turn_id: str, body: Empty, request: Request, uid: str = Depends(current_uid)):
    if not re.fullmatch(r"(turn_[0-9a-f-]{36}|cont_act_[0-9a-f]{26})", turn_id):
        raise not_found()
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


class Found(Strict):
    """Only the helper's fixed words: nothing free-form can carry an address or a name off the device."""
    cid: str = Field(pattern=r"^[0-9a-f]{12}$")
    guess: Literal[tuple(real.FOUND_GUESSES)]
    vendor: Literal[tuple(real.FOUND_VENDORS)] | None = None
    services: list[Literal[tuple(real.FOUND_SERVICES)]] = Field(default_factory=list, max_length=8)
    ports: list[Literal[tuple(real.FOUND_PORTS)]] = Field(default_factory=list, max_length=8)


class DiscoveriesBody(Strict):
    items: list[Found] = Field(max_length=30)


class AddFoundBody(Strict):
    name: str = Field(min_length=1, max_length=40)


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
    allowedJobs: dict[Literal["restart_container", "restart_service", "diagnose", "logs"], list[str]] = \
        Field(default_factory=dict)
    watchResults: list[WatchResult] = Field(default_factory=list, max_length=10)
    manage: Literal["app", "strict"] | None = None  # chosen on the device; the server can't change it
    failedAgents: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=20)
    safety: dict[Literal["passwordlessSudo", "sshPasswordLogin"], bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def short_units(self):
        if any(len(u) > 128 for u in self.failedUnits):
            raise ValueError("unit names must be at most 128 characters")
        for kind, targets in self.allowedJobs.items():
            pattern = real.CONTAINER_NAME if kind == "restart_container" else real.TARGET_NAME
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


class PairPollBody(Strict):
    code: str = Field(pattern=r"^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$")
    pollSecret: str = Field(min_length=20, max_length=64)


class PairDecideBody(Strict):
    approve: bool


def _pair_code(code: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}", code):
        raise not_found()
    return code


@app.post("/helper/pair/start", status_code=201)
def helper_pair_start(body: PairStartBody, request: Request):
    return real.pair_start(scrub(body.name)[0], scrub(body.os)[0] if body.os else None, _client_ip(request))


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
    return real.pair_decide(uid, _pair_code(code), body.approve)


@app.post("/helper/leave")
def helper_leave(body: Empty, request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    return real.leave(token)


@app.post("/helper/enrol", status_code=201)
def helper_enrol(body: EnrolBody):
    return real.enrol(body.code, scrub(body.name)[0])


@app.post("/helper/heartbeat")
def helper_heartbeat(body: HeartbeatBody, request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    return real.heartbeat(token, body.model_dump())


@app.post("/helper/jobs/{action_id}/result")
def helper_job_result(action_id: str, body: JobResultBody, request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    if not re.fullmatch(r"act_[0-9a-f]{26}", action_id):
        raise not_found()
    return actions.job_result(token, action_id, body.ok, body.summary, body.state, body.output)


@app.post("/helper/discoveries")
def helper_discoveries(body: DiscoveriesBody, request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    items, _ = scrub_value([i.model_dump() for i in body.items])
    return real.save_discoveries(token, items)


@app.post("/api/discoveries/{helper_id}/{cid}/add", status_code=201)
def add_found(helper_id: str, cid: str, body: AddFoundBody, uid: str = Depends(current_uid)):
    if not re.fullmatch(r"dev_[0-9a-z]{26}", helper_id) or not re.fullmatch(r"[0-9a-f]{12}", cid):
        raise not_found()
    return real.add_found(uid, helper_id, cid, scrub(body.name)[0])


@app.post("/helper/jobs/claim")
def helper_claim(body: Empty, request: Request):
    token = request.headers.get("x-device-token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", token):
        raise ApiError(401, "invalid_token")
    return real.claim(token)
