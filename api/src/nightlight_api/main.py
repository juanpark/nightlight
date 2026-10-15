"""HTTP routes. Only these are public; the ADK agent runs in-process and is never exposed directly."""

from typing import Literal

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field

from . import __version__, actions, db, demo, sim, trust as trustlib
from .auth import current_uid
from .config import settings
from .errors import ApiError, api_error_handler, conflict, not_found, validation_error_handler

app = FastAPI(title="Nightlight API", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_middleware(CORSMiddleware, allow_origins=settings.web_origins, allow_methods=["GET", "POST", "PUT"],
                   allow_headers=["Authorization", "Content-Type"], max_age=600)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartBody(Strict):
    template: Literal["home-pi"] = "home-pi"


class Empty(Strict):
    pass


class InjectBody(Strict):
    kind: str = Field(max_length=40)
    deviceId: str = Field(max_length=40)


class DecideBody(Strict):
    decision: Literal["approve", "deny"]
    note: str | None = Field(default=None, max_length=280)


Level = Literal["ask", "ask_new", "auto"]


class TrustBody(Strict):
    level: Level
    deviceId: str | None = Field(default=None, max_length=40)
    svcId: str | None = Field(default=None, max_length=40)
    pinned: bool = False


class PromotionBody(Strict):
    accept: bool
    offerId: str = Field(max_length=64)


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@app.post("/api/demo/start")
def demo_start(body: StartBody, uid: str = Depends(current_uid)):
    return demo.start(uid, body.template)


@app.post("/api/demo/reset")
def demo_reset(body: Empty, uid: str = Depends(current_uid)):
    return demo.reset(uid)


@app.post("/api/demo/inject", status_code=201)
def demo_inject(body: InjectBody, uid: str = Depends(current_uid)):
    return demo.inject(uid, body.kind, body.deviceId)


@app.post("/api/actions/{action_id}/decide")
def decide(action_id: str, body: DecideBody, uid: str = Depends(current_uid)):
    status, payload = actions.decide(uid, action_id, body.decision, body.note)
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
        if body.svcId and not body.deviceId:
            raise ApiError(422, "svc_requires_device")
        if body.deviceId:
            target = (db.services(uid, body.deviceId).document(body.svcId) if body.svcId
                      else db.device(uid, body.deviceId))
            if not target.get(transaction=tx).exists:
                raise not_found()
            tx.update(target, {f"trustOverride.{action_type}": level})
            return
        doc = {**doc, "level": level, "pinned": body.pinned}
        if body.pinned or level != "auto":
            doc["offer"] = None
        tx.set(ref, doc)

    run(db.client().transaction())
    return db.trust_doc(uid, "sim", action_type).get().to_dict()


@app.post("/api/trust/{action_type}/promotion")
def promotion(action_type: str, body: PromotionBody, uid: str = Depends(current_uid)):
    _trust_type(action_type)

    @firestore.transactional
    def run(tx):
        user_snap = db.user(uid).get(transaction=tx)
        ref = db.trust_doc(uid, "sim", action_type)
        snap = ref.get(transaction=tx)
        if not user_snap.exists or not snap.exists:
            raise not_found()
        user = user_snap.to_dict()
        if user.get("demo", {}).get("state") != "ready":
            raise conflict("resetting", retryAfter=5)
        updated = trustlib.accept_offer(snap.to_dict(), body.offerId, body.accept, user["demoGeneration"],
                                        firestore.SERVER_TIMESTAMP)
        if updated is None:
            raise conflict("offer_obsolete")
        tx.set(ref, updated)

    run(db.client().transaction())
    return db.trust_doc(uid, "sim", action_type).get().to_dict()
