"""Calendar events for Do Things' Today: pure logic, no I/O.

Things shows today's calendar events above its Today list; Do Things does the
same. The events come from macOS Calendar through EventKit (read in
common.read_calendar); this module checks what that read returned, keeps
the calendars the user chose, orders the events as Things does (all-day
first, then by start time) and words their times. Nothing here writes to
Calendar.

Version: 2.0.1

Change log:
- v2.0.1 (2026-11-10): Synchronized module version metadata.
- v2.0.0 (2026-11-10): Synchronized module version metadata.
- v1.9.2 (2026-11-10): Synchronized module version metadata.
- v1.9.1 (2026-11-10): Synchronized module version metadata.
- v1.9.0 (2026-11-10): Synchronized module version metadata.
- v1.8.0 (2026-11-10): New. Calendar, Event and CalendarRead models;
  parse_calendar_output, visible_events, order_events, event_time_label and
  event_state.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, List, Optional

# What EventKit's authorization status means for Do Things. "unavailable"
# means Calendar couldn't be read at all (osascript failed, not a Mac, bad
# output); the read's `problem` says why.
ACCESS_BY_STATUS = {0: "not_asked", 1: "restricted", 2: "denied", 3: "allowed", 4: "write_only"}
ACCESS_UNAVAILABLE = "unavailable"

STATUS_CANCELED = 3  # EKEventStatusCanceled: not shown, as in Calendar's own day view.

# Calendar colors arrive as "#rrggbb"; anything else is shown gray.
COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")
DEFAULT_COLOR = "#8e8e93"
# EventKit identifiers are letters, digits and a few separators (e.g. "UUID:UUID").
# Anything else is refused before it reaches a URL.
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9:._@-]{1,200}$")


@dataclass(frozen=True)
class Calendar:
    """One calendar from macOS Calendar."""

    id: str
    title: str
    source: str  # The account it belongs to, e.g. "iCloud".
    color: str  # "#rrggbb".


@dataclass(frozen=True)
class Event:
    """One event of today (or an occurrence of a repeating event)."""

    id: str
    title: str
    all_day: bool
    start: float  # Unix time.
    end: float
    calendar_id: str
    calendar: str  # The calendar's title.
    color: str  # The calendar's color, "#rrggbb".
    status: int = 0


@dataclass
class CalendarRead:
    """What one read of Calendar returned: the access state, the calendars and today's events."""

    access: str
    calendars: List[Calendar] = field(default_factory=list)
    events: List[Event] = field(default_factory=list)
    problem: str = ""  # Why the read failed, for the log; "" when it worked.


def is_valid_event_id(event_id: object) -> bool:
    """Return True if `event_id` looks like an EventKit event identifier."""
    return isinstance(event_id, str) and bool(EVENT_ID_RE.match(event_id))


def _color(value: object) -> str:
    """Return a valid "#rrggbb" color, or gray."""
    return value if isinstance(value, str) and COLOR_RE.match(value) else DEFAULT_COLOR


def _text(value: object) -> str:
    """Return `value` if it is a string, else ""."""
    return value if isinstance(value, str) else ""


def parse_calendar_output(raw: object) -> CalendarRead:
    """Turn the calendar script's JSON into a CalendarRead, failing safe.

    Malformed calendars and events are skipped rather than shown; output that
    isn't an object with a known status is reported as unavailable.
    """
    if not isinstance(raw, dict) or raw.get("status") not in ACCESS_BY_STATUS:
        return CalendarRead(ACCESS_UNAVAILABLE, problem="Unexpected output from the calendar script.")
    calendars = [
        Calendar(c["id"], _text(c.get("title")), _text(c.get("source")), _color(c.get("color")))
        for c in raw.get("calendars") or []
        if isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"]
    ]
    colors = {c.id: c.color for c in calendars}
    events = []
    for e in raw.get("events") or []:
        if not isinstance(e, dict) or not is_valid_event_id(e.get("id")):
            continue
        start, end = e.get("start"), e.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end < start:
            continue
        calendar_id = _text(e.get("calendar_id"))
        status = e.get("status")
        events.append(Event(
            id=e["id"], title=_text(e.get("title")) or "(No title)", all_day=e.get("all_day") is True,
            start=float(start), end=float(end), calendar_id=calendar_id, calendar=_text(e.get("calendar")),
            color=colors.get(calendar_id, DEFAULT_COLOR), status=status if isinstance(status, int) else 0,
        ))
    return CalendarRead(ACCESS_BY_STATUS[raw["status"]], calendars, events)


def visible_events(events: Iterable[Event], hidden_calendars: Iterable[str]) -> List[Event]:
    """Return the events to show, in Today's order: not canceled, not in a calendar the user unchecked."""
    hidden = set(hidden_calendars)
    return order_events(e for e in events if e.calendar_id not in hidden and e.status != STATUS_CANCELED)


def order_events(events: Iterable[Event]) -> List[Event]:
    """Order events as Things' Today does: all-day first, then by start time, then title."""
    return sorted(events, key=lambda e: (not e.all_day, e.start, e.title.lower()))


def _clock(moment: float) -> datetime:
    """Return a Unix time as a local (Mac time zone) datetime."""
    return datetime.fromtimestamp(moment)


def _time(moment: datetime, with_period: bool = True) -> str:
    """Word a time as Calendar does: "9:30 AM", or "9:30" without the AM/PM."""
    text = f"{moment.hour % 12 or 12}:{moment.minute:02d}"
    return f"{text} {'AM' if moment.hour < 12 else 'PM'}" if with_period else text


def event_time_label(event: Event, day_start: float, day_end: float) -> str:
    """Word an event's time for Today, in the Mac's time zone.

    "All day"; "9:30 – 10:30 AM" (AM/PM once when both are the same);
    "11:00 AM – 1:00 PM"; "6:05 PM" for an event with no length; "Until
    10:00 AM" for one that started before today; "From 8:00 PM" for one that
    goes on after today. `day_start` and `day_end` are today's local
    midnights.
    """
    if event.all_day:
        return "All day"
    start, end = _clock(event.start), _clock(event.end)
    began_before, ends_after = event.start < day_start, event.end > day_end
    if began_before and ends_after:
        return "All day"
    if began_before:
        return f"Until {_time(end)}"
    if ends_after:
        return f"From {_time(start)}"
    if event.end == event.start:
        return _time(start)
    same_period = (start.hour < 12) == (end.hour < 12)
    return f"{_time(start, with_period=not same_period)} – {_time(end)}"


def event_state(event: Event, now: float) -> Optional[str]:
    """Return "past" for an event that has ended, "now" for one under way, else None.

    All-day events are neither (Today dims or highlights timed events only).
    """
    if event.all_day:
        return None
    if event.end <= now and (event.end < now or event.end > event.start):
        return "past"  # Ended; an event with no length counts as ended once its moment has passed.
    if event.start <= now < event.end:
        return "now"
    return None
