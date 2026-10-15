"""The trust ladder: how much freedom the agent has for each kind of job.

Levels, in plain words: ask = "Always ask me", ask_new = "Ask me for new things", auto = "Just handle it and tell me".
Pure functions over plain dicts so they can run inside Firestore transactions.
"""

from .config import settings
from .ids import new_id
from .sim import ACTIONS

LEVELS = ["ask", "ask_new", "auto"]
CEILING = {"routine": "auto", "service": "ask_new", "destructive": "ask"}


def _min(a: str, b: str) -> str:
    return a if LEVELS.index(a) <= LEVELS.index(b) else b


def ceiling(action_type: str) -> str:
    return CEILING[ACTIONS[action_type]["riskClass"]]


def scope(device_id: str, svc_id: str | None) -> str:
    return f"{device_id}/{svc_id or '-'}"


def resolve(user: dict, trust: dict | None, device: dict, service: dict | None, action_type: str,
            params: dict) -> dict:
    """Which level applies, where it came from, and whether this proposal runs without asking.

    Precedence: service override > device override > the job's level > the global default; then the risk ceiling.
    `ask_new` runs on its own only for parameterless allowlisted jobs on a scope the user approved before.
    """
    trust = trust or {}
    for source, level in (("service", (service or {}).get("trustOverride", {}).get(action_type)),  # noqa: B007
                          ("device", device.get("trustOverride", {}).get(action_type)),
                          ("type", trust.get("level")),
                          ("default", user.get("trustDefault", "ask"))):
        if level:
            break
    level = _min(level, ceiling(action_type))
    if level == "auto":
        runs_alone = True
    elif level == "ask_new":
        runs_alone = (ACTIONS[action_type].get("allowlisted") and params == {}
                      and scope(device["id"], service and service["id"]) in trust.get("approvedScopes", []))
    else:
        runs_alone = False
    return {"level": level, "resolvedBy": source, "auto": bool(runs_alone)}


def demote(level: str) -> str:
    return LEVELS[max(LEVELS.index(level) - 1, 0)]


def demoted_overrides(doc: dict | None, action_type: str) -> dict | None:
    """Field updates that drop an unpinned device/service override one step after a failure, or None.

    Without this a scoped "just handle it" would outrank the demoted job level and keep running on its own.
    """
    level = (doc or {}).get("trustOverride", {}).get(action_type)
    if not level or (doc or {}).get("trustPinned", {}).get(action_type):
        return None
    return {f"trustOverride.{action_type}": demote(level)}


def new_doc(action_type: str, generation: int, realm: str = "sim") -> dict:
    return {"actionType": action_type, "realm": realm, "label": ACTIONS[action_type]["label"],
            "riskClass": ACTIONS[action_type]["riskClass"], "ceiling": ceiling(action_type),
            "level": "ask", "pinned": False, "successes": [], "failures": 0, "approvedScopes": [],
            "offer": None, "demoGeneration": generation}


def after_outcome(trust: dict, action: dict, ok: bool, by: str, now) -> dict:
    """Trust after an action finishes. Human-approved successes count; automatic ones never do.

    A failure (human or automatic) clears the track record, withdraws any offer and drops one step unless pinned.
    """
    t = dict(trust)
    if not ok:
        t["failures"] = t.get("failures", 0) + 1
        t["successes"] = []
        t["approvedScopes"] = []
        t["offer"] = None
        t["offerDeclined"] = False  # a fresh track record may earn a fresh offer
        if not t.get("pinned"):
            t["level"] = demote(t["level"])
        return t
    if by != "user":
        return t
    if action["id"] not in t.get("successes", []):
        t["successes"] = [*t.get("successes", []), action["id"]]
    s = scope(action["deviceId"], action.get("svcId"))
    if s not in t.get("approvedScopes", []):
        t["approvedScopes"] = [*t.get("approvedScopes", []), s]
    # The offer promises "handle it on my own", so only jobs whose ceiling allows that get one.
    eligible = (len(t["successes"]) >= settings.promotion_threshold and not t.get("pinned")
                and not t.get("offer") and not t.get("offerDeclined")
                and t["ceiling"] == "auto" and t["level"] != "auto")
    if eligible:
        n = len(t["successes"])
        t["offer"] = {"offerId": new_id("offer"), "demoGeneration": t["demoGeneration"],
                      "successes": t["successes"][-settings.promotion_threshold:], "at": now,
                      "text": f"{t['label']} has gone well {n} times. Let me handle it on my own next time?"}
    return t


def accept_offer(trust: dict, offer_id: str, accept: bool, generation: int, now) -> dict | None:
    """Apply the user's answer to a promotion offer, re-checked now. None means the offer is obsolete."""
    offer = trust.get("offer")
    if (not offer or offer["offerId"] != offer_id or offer["demoGeneration"] != generation
            or trust.get("demoGeneration") != generation
            or not set(offer["successes"]) <= set(trust.get("successes", []))
            or len(offer["successes"]) < settings.promotion_threshold or trust.get("pinned")):
        return None
    t = dict(trust)
    t["offer"] = None
    if accept:
        if trust["ceiling"] != "auto":
            return None
        t["level"] = "auto"
        t["promotionAccepted"] = {"offerId": offer_id, "at": now}
    else:
        t["promotionDeclined"] = {"offerId": offer_id, "at": now}
        t["offerDeclined"] = True  # offered once; not again until the track record resets
    return t
