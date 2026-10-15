"""The turn fence: a write made on behalf of a turn only lands if that turn still owns its session."""

from . import db
from .errors import conflict


def turn_fence(uid: str, session_id: str, turn_id: str, attempt: int, generation: int):
    """Return fence(tx) for use inside any transaction. Reads only; raises 409 stale when superseded."""

    def fence(tx):
        user = db.user(uid).get(transaction=tx)
        session = db.session(uid, session_id).get(transaction=tx)
        u = user.to_dict() if user.exists else {}
        active = (session.to_dict() or {}).get("activeTurn") if session.exists else None
        if (u.get("demo", {}).get("state") != "ready" or u.get("demoGeneration") != generation or not active
                or active.get("turnId") != turn_id or active.get("attempt") != attempt):
            raise conflict("stale")

    return fence
