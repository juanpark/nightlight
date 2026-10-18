"""Times in the owner's own time zone. Stored timestamps stay UTC; only what a person (or the agent, on their behalf)
reads is rendered here: "18 Oct 13:50 KST", or "18 Oct 04:50 UTC" when the account's zone is not known.

The zone of the turn being answered is a context variable, set once when the turn starts (turns.stream), so every
helper that writes a time into words picks it up without threading it through each call."""

import contextvars
import re
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

ZONE: contextvars.ContextVar[str | None] = contextvars.ContextVar("nightlight_zone", default=None)


@lru_cache(maxsize=1)
def _known() -> frozenset[str]:
    return frozenset(available_timezones()) | {"UTC"}


def valid(name) -> str | None:
    """The IANA zone name when it is a real one ("Asia/Seoul"), else None (empty, unknown, "localtime", paths...)."""
    if not isinstance(name, str) or not 1 <= len(name) <= 64 or name not in _known():
        return None
    return name


def _tz(zone: str | None):
    z = valid(zone)
    return ZoneInfo(z) if z else timezone.utc


def fmt(at: datetime, zone: str | None = None, now: datetime | None = None) -> str:
    """'18 Oct 13:50 KST' in the zone (the turn's when not given); the year is added when it isn't this year."""
    zone = zone if zone is not None else ZONE.get()
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    tz = _tz(zone)
    local = at.astimezone(tz)
    label = "UTC" if tz is timezone.utc else (local.strftime("%Z") or zone)
    this_year = (now or datetime.now(timezone.utc)).astimezone(tz).year
    return f"{local.day} {local:%b}{'' if local.year == this_year else f' {local.year}'} {local:%H:%M} {label}"


def day(at: datetime, zone: str | None = None) -> str:
    """The calendar date in the zone, ISO style ("2026-10-18")."""
    zone = zone if zone is not None else ZONE.get()
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(_tz(zone)).date().isoformat()


# A full timestamp with its offset, as isoformat() or str() of an aware datetime writes it.
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})")


def localize(value, zone: str | None = None):
    """A copy of a result with every timestamp (datetime, or a string that is exactly an aware timestamp) written in
    the zone with its abbreviation. Everything else is left as it is."""
    if isinstance(value, datetime):
        return fmt(value, zone)
    if isinstance(value, str):
        if 16 <= len(value) <= 40 and _STAMP.fullmatch(value):
            try:
                return fmt(datetime.fromisoformat(value.replace("Z", "+00:00")), zone)
            except ValueError:
                return value
        return value
    if isinstance(value, dict):
        return {k: localize(v, zone) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [localize(v, zone) for v in value]
    return value


def line(zone: str | None) -> str:
    """The agent's instruction line about time."""
    z = valid(zone)
    return (f"Times are shown in the owner's time zone ({z}); use that zone when you mention times."
            if z else "Times are shown in UTC (the owner's time zone is not known); say \"UTC\" when you mention times.")
