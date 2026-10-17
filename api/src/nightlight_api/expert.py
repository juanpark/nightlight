"""Expert sessions: commands the agent proposes that run on a device only after the owner signs them with a passkey.

The owner's passkey (WebAuthn, ES256) is registered here; its public key is pinned on each device by the owner at the
device (`nightlight expert`, after comparing a fingerprint). A command card carries a payload (device, command,
expiry, nonce); the browser signs sha256(payload) with the passkey; the helper verifies that signature itself and
runs the command. The cloud relays signed commands but can't create or change one. See docs/DESIGN-trust.md."""

import base64
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from google.cloud import firestore

from . import db
from .config import settings
from .errors import ApiError, not_found

COMMAND_TTL = 15 * 60  # seconds a signed command stays valid
MAX_COMMAND = 500


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def challenge_for(payload: dict) -> str:
    return b64u(hashlib.sha256(canonical(payload)).digest())


def _origin(request_origin: str | None) -> str:
    """The web origin the passkey belongs to: the request's, if it is one of ours."""
    if request_origin and request_origin in settings.web_origins:
        return request_origin
    https = [o for o in settings.web_origins if o.startswith("https://")]
    return (https or settings.web_origins)[-1]


def _fingerprint(der: bytes) -> str:
    """64 bits of SHA-256 over the key's DER bytes, as XXXX-XXXX-XXXX-XXXX (the device and the browser compute the
    same code themselves; this copy is only for display)."""
    h = hashlib.sha256(der).hexdigest()[:16].upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def _ref(uid: str):
    return db.user(uid).collection("expert").document("passkey")


def register_options(uid: str, request_origin: str | None) -> dict:
    origin = _origin(request_origin)
    rp_id = urlparse(origin).hostname
    challenge = b64u(secrets.token_bytes(32))
    _ref(uid).set({"pending": {"challenge": challenge, "origin": origin, "rpId": rp_id, "at": time.time()}}, merge=True)
    return {"challenge": challenge, "rp": {"id": rp_id, "name": "Nightlight expert sessions"},
            "user": {"id": b64u(hashlib.sha256(uid.encode()).digest()[:16]), "name": "Nightlight owner",
                     "displayName": "Nightlight owner"}}


def register(uid: str, credential: dict) -> dict:
    """Check the new passkey (webauthn library) and keep its public key as PEM, with a short fingerprint."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from webauthn import verify_registration_response
    from webauthn.helpers import decode_credential_public_key
    from webauthn.helpers.decode_credential_public_key import DecodedEC2PublicKey

    pending = (_ref(uid).get().to_dict() or {}).get("pending")
    if not pending or time.time() - pending["at"] > 300:
        raise ApiError(409, "start_again")
    try:
        v = verify_registration_response(credential=credential, expected_challenge=unb64u(pending["challenge"]),
                                         expected_origin=pending["origin"], expected_rp_id=pending["rpId"],
                                         require_user_verification=True)
    except Exception:
        raise ApiError(422, "passkey_not_accepted") from None
    key = decode_credential_public_key(v.credential_public_key)
    if not isinstance(key, DecodedEC2PublicKey):
        raise ApiError(422, "passkey_type_unsupported")  # the helper verifies ES256 (P-256) with openssl
    pub = ec.EllipticCurvePublicNumbers(int.from_bytes(key.x, "big"), int.from_bytes(key.y, "big"),
                                        ec.SECP256R1()).public_key()
    der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    doc = {"pem": pem, "cose": b64u(v.credential_public_key), "credentialId": b64u(v.credential_id),
           "rpId": pending["rpId"], "origin": pending["origin"],
           "fingerprint": _fingerprint(der), "createdAt": datetime.now(timezone.utc)}
    _ref(uid).set({**doc, "pending": firestore.DELETE_FIELD}, merge=True)
    return {k: doc[k] for k in ("fingerprint", "credentialId", "rpId")}


def status(uid: str) -> dict:
    d = _ref(uid).get().to_dict() or {}
    if not d.get("pem"):
        return {"enabled": False}
    return {"enabled": True, **{k: d[k] for k in ("fingerprint", "credentialId", "rpId")}}


def key_for_device(uid: str) -> dict:
    """What the helper pins (after the owner compares the fingerprint at the device)."""
    d = _ref(uid).get().to_dict() or {}
    if not d.get("pem"):
        raise not_found()
    return {k: d[k] for k in ("pem", "rpId", "origin", "fingerprint")}


def card(device: dict, params: dict) -> tuple[dict, dict]:
    """(card fields, params with the payload to sign) for an expert command on a device that switched it on."""
    command = params.get("command")
    if set(params) - {"command", "why"} or not isinstance(command, str) or not command.strip() \
            or len(command) > MAX_COMMAND or "\x00" in command:
        raise ValueError("bad_target")
    if "on" not in (device.get("allowedJobs") or {}).get("expert", []):
        raise ValueError("not_allowed_on_device")
    payload = {"device": device["id"], "command": command.strip(), "expires": int(time.time()) + COMMAND_TTL,
               "nonce": b64u(secrets.token_bytes(12))}
    why = str(params.get("why") or "")[:300]
    fields = {"svcId": None, "plan": f"Run on the {device.get('name')}: {payload['command']}",
              "dryRun": (why + " " if why else "") + "It runs only after you sign it with your passkey; the device "
                        "checks your signature itself. Valid for 15 minutes.",
              "rollback": "Depends on the command: read it before you sign. Commands that only read are safe.",
              "blastRadius": [device["id"]], "riskClass": "destructive"}
    return fields, {"command": payload["command"], "why": why, "payload": payload, "challenge": challenge_for(payload)}


GRANT_TTL = 15 * 60


def _resume(uid: str, a: dict, action_id: str) -> str:
    """Queue the turn that continues the investigation now that the owner approved it (tools on, Investigate mode)."""
    from .ids import continuation_turn_id
    turn_id = continuation_turn_id(action_id)
    why = (a.get("params") or {}).get("why") or "the problem we were looking into"
    db.turns(uid, a["sessionId"]).document(turn_id).set({
        "kind": "user", "status": "queued", "attempt": 0, "demoGeneration": a.get("demoGeneration"),
        "mode": "investigate", "actionId": action_id,
        "input": ("[The owner approved the read-only investigation of this device with their passkey; it is active for "
                  f"15 minutes.] Continue investigating now with run_command: {why}. Run the commands you need one "
                  "at a time, then answer in the usual Investigate shape and update the device's profile."),
        "createdAt": datetime.now(timezone.utc)}, merge=False)
    db.user(uid).collection("turnIndex").document(turn_id).set({"sessionId": a["sessionId"],
                                                               "demoGeneration": a.get("demoGeneration")})
    return turn_id


def grant_card(device: dict, params: dict) -> tuple[dict, dict]:
    """The card that unlocks an investigation: read-only commands on one device for 15 minutes, one passkey tap."""
    if "on" not in (device.get("allowedJobs") or {}).get("expert", []):
        raise ValueError("not_allowed_on_device")
    payload = {"device": device["id"], "mode": "read-only", "expires": int(time.time()) + GRANT_TTL,
               "nonce": b64u(secrets.token_bytes(12))}
    why = str(params.get("why") or "")[:300]
    fields = {"svcId": None, "plan": f"Let Nightlight investigate the {device.get('name')} with read-only commands "
                                     "for 15 minutes.",
              "dryRun": (why + " " if why else "") + "It may run commands that only read (system logs, disk use, "
                        "running programs, network) and shows you each one. The device itself refuses anything "
                        "that could change something or touch where secrets are kept.",
              "rollback": "Nothing to undo: it only reads. It ends by itself after 15 minutes.",
              "blastRadius": [device["id"]], "riskClass": "read"}
    return fields, {"why": why, "payload": payload, "challenge": challenge_for(payload)}


def _grants(uid: str):
    return db.user(uid).collection("expert")


def active_grant(uid: str, device_id: str) -> dict | None:
    g = _grants(uid).document(f"grant_{device_id}").get().to_dict()
    return g if g and g["payload"]["expires"] > time.time() + 10 else None


def read_params(uid: str, device: dict, command) -> dict:
    """Params for one investigation command: the command plus the signed grant the device checks."""
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND or "\x00" in command:
        raise ValueError("bad_target")
    g = active_grant(uid, device["id"])
    if not g:
        raise ValueError("no_investigation")
    return {"command": command.strip(), "grant": g["payload"], "signed": g["signed"]}


def sign(uid: str, action_id: str, assertion: dict) -> dict:
    """The owner signed a pending expert command: check it here too (for a clear answer), then hand it over."""
    from webauthn import verify_authentication_response

    k = _ref(uid).get().to_dict() or {}
    ref = db.action(uid, action_id)
    a = ref.get().to_dict()
    if not a or a.get("type") not in ("expert_command", "expert_grant"):
        raise not_found()
    if a.get("status") != "pending":
        raise ApiError(409, "not_pending")
    if not k.get("pem") or a["params"]["payload"]["expires"] < time.time():
        raise ApiError(409, "expired" if k.get("pem") else "no_passkey")
    credential = {"id": k["credentialId"], "rawId": k["credentialId"], "type": "public-key",
                  "response": {**{x: assertion[x] for x in ("authenticatorData", "clientDataJSON", "signature")}}}
    try:
        v = verify_authentication_response(credential=credential,
                                           expected_challenge=unb64u(challenge_for(a["params"]["payload"])),
                                           expected_rp_id=k["rpId"], expected_origin=k["origin"],
                                           credential_public_key=unb64u(k["cose"]),
                                           credential_current_sign_count=int(k.get("signCount") or 0),
                                           require_user_verification=True)
    except Exception:
        raise ApiError(422, "signature_not_accepted") from None
    if v.new_sign_count:  # counterless passkeys stay at 0; a counter that goes backwards was refused above
        _ref(uid).update({"signCount": v.new_sign_count})
    signed = {x: assertion[x] for x in ("authenticatorData", "clientDataJSON", "signature")}
    decision = {"by": "user", "decision": "approve", "with": "passkey"}
    if a["type"] == "expert_grant":  # nothing runs now: the grant lets the agent run read-only commands for a while
        payload = a["params"]["payload"]
        _grants(uid).document(f"grant_{a['deviceId']}").set({"payload": payload, "signed": signed,
                                                            "actionId": action_id})
        until = datetime.fromtimestamp(payload["expires"], timezone.utc)
        update = {"status": "done", "params.signed": signed, "decision": decision, "followUp": "none",
                  "result": {"ok": True, "summary": f"Investigation unlocked until {until:%H:%M} UTC."}}
        if a.get("sessionId"):  # the chat that asked carries on by itself, in Investigate mode, with the commands
            update["continuationTurnId"] = _resume(uid, a, action_id)
        ref.update(update)
        return {"ok": True, "actionId": action_id, "status": "done",
                **({"continuationTurnId": update["continuationTurnId"]} if "continuationTurnId" in update else {})}
    ref.update({"status": "approved", "params.signed": signed, "decision": decision})
    return {"ok": True, "actionId": action_id, "status": "approved"}

