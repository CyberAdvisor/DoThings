"""Read-only calendar diagnostic for Do Things.

Checks whether Do Things could show today's calendar events in Today, as
Things does. Things reads events live from macOS Calendar (they are not in
the Things database), so Do Things would have to read Calendar too. This
script tries the planned way, EventKit (the macOS calendar framework) called
from JavaScript for Automation (`osascript -l JavaScript`), and prints:
whether macOS grants calendar access to the app running it (Terminal or
Shortcuts), the calendars it can see, today's events and how long reading
them took. With --applescript it also times the fallback, asking the
Calendar app through AppleScript, for comparison.

It only reads. The first run may make macOS ask whether Terminal may access
your calendars (that answer is a macOS setting, not a change to any
calendar). Nothing is written to Calendar, Things or any Do Things file.
--hide-titles replaces event titles with "(title hidden)", for sharing the
output.

Version: 1.7.1

Change log:
- v1.7.1 (2026-11-10): New. Calendar access check through EventKit, with an
  optional AppleScript comparison.
"""

import argparse
import json
import platform
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from common import PROJECT_VERSION

# How long to wait for each osascript run (the first one may sit on macOS's
# permission prompt until it is answered).
EVENTKIT_TIMEOUT_SECONDS = 90
APPLESCRIPT_TIMEOUT_SECONDS = 120

# EKAuthorizationStatus values. On macOS 14 and later 3 means full access;
# on earlier versions it is the single "authorized" state.
AUTH_STATUS = {
    0: "not determined (macOS hasn't asked yet)",
    1: "restricted (blocked by a profile or parental controls)",
    2: "denied",
    3: "full access",
    4: "write only (can add events but not read them)",
}

# EKEventStatus values that mean something to the reader.
EVENT_STATUS = {2: "tentative", 3: "canceled"}

# JavaScript for Automation run by osascript. It asks for calendar access if
# macOS hasn't asked yet, then reads the calendars and today's events
# (midnight to midnight in the Mac's time zone) and returns them as JSON.
# EventKit expands repeating events, so their occurrences today are included.
# It only reads: no EventKit save or remove call is made.
EVENTKIT_SCRIPT = r"""
ObjC.import('Foundation');
ObjC.import('AppKit');
ObjC.import('EventKit');

const ENTITY_EVENT = 0;  // EKEntityTypeEvent

// Turn an NSString (or nil) into a JS string.
function text(value) {
  return value === undefined || value === null || value.isNil() ? '' : ObjC.unwrap(value);
}

// A calendar's color as "#rrggbb" in sRGB, or '' if it has none.
function hexColor(color) {
  if (color === undefined || color.isNil()) return '';
  const rgb = color.colorUsingColorSpace($.NSColorSpace.sRGBColorSpace);
  if (rgb.isNil()) return '';
  const part = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0');
  return '#' + part(rgb.redComponent) + part(rgb.greenComponent) + part(rgb.blueComponent);
}

// Ask for access (full access on macOS 14+, the older request otherwise) and
// wait for the answer, running the run loop so the completion can arrive.
function requestAccess(store) {
  const answer = { answered: false, granted: false, error: '' };
  const done = (granted, error) => {
    answer.answered = true;
    answer.granted = !!granted;
    answer.error = error && !error.isNil() ? text(error.localizedDescription) : '';
  };
  try {
    if (typeof store.requestFullAccessToEventsWithCompletion === 'function') {
      answer.method = 'requestFullAccessToEventsWithCompletion';
      store.requestFullAccessToEventsWithCompletion(done);
    } else {
      answer.method = 'requestAccessToEntityTypeCompletion';
      store.requestAccessToEntityTypeCompletion(ENTITY_EVENT, done);
    }
  } catch (e) {
    answer.error = 'request failed: ' + e;
    return answer;
  }
  const until = Date.now() + 80000;
  while (!answer.answered && Date.now() < until) {
    $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.25));
  }
  return answer;
}

function run() {
  const out = { macos: text($.NSProcessInfo.processInfo.operatingSystemVersionString) };
  out.status_before = Number($.EKEventStore.authorizationStatusForEntityType(ENTITY_EVENT));
  if (out.status_before === 0) out.request = requestAccess($.EKEventStore.alloc.init);
  out.status = Number($.EKEventStore.authorizationStatusForEntityType(ENTITY_EVENT));
  if (out.status !== 3) return JSON.stringify(out);

  // A store made after access was granted, so it sees the calendars.
  const store = $.EKEventStore.alloc.init;
  const started = Date.now();
  const calendars = store.calendarsForEntityType(ENTITY_EVENT);
  out.calendars = [];
  for (let i = 0; i < calendars.count; i++) {
    const c = calendars.objectAtIndex(i);
    out.calendars.push({
      id: text(c.calendarIdentifier),
      title: text(c.title),
      source: c.source.isNil() ? '' : text(c.source.title),
      color: hexColor(c.color),
    });
  }
  const calendar = $.NSCalendar.currentCalendar;
  const start = calendar.startOfDayForDate($.NSDate.date);
  const DAY_UNIT = 16;  // NSCalendarUnitDay (1 << 4), written out in case the enum isn't bridged.
  const end = calendar.dateByAddingUnitValueToDateOptions(DAY_UNIT, 1, start, 0);
  const events = store.eventsMatchingPredicate(store.predicateForEventsWithStartDateEndDateCalendars(start, end, $()));
  out.events = [];
  for (let i = 0; i < events.count; i++) {
    const e = events.objectAtIndex(i);
    out.events.push({
      id: text(e.eventIdentifier),
      title: text(e.title),
      all_day: !!(e.allDay !== undefined ? e.allDay : e.isAllDay),  // Property name or getter.
      start: Number(e.startDate.timeIntervalSince1970),
      end: Number(e.endDate.timeIntervalSince1970),
      calendar: e.calendar.isNil() ? '' : text(e.calendar.title),
      status: Number(e.status),
      repeating: !!e.hasRecurrenceRules,
    });
  }
  out.read_ms = Date.now() - started;
  return JSON.stringify(out);
}
"""

# JavaScript for Automation that asks the Calendar app (AppleScript's object
# model) for today's events, calendar by calendar, timing each. Repeating
# events that started on an earlier day are typically missed this way; the
# counts are compared with EventKit's.
APPLESCRIPT_SCRIPT = r"""
function run() {
  const app = Application('Calendar');
  const start = new Date(); start.setHours(0, 0, 0, 0);
  const end = new Date(start); end.setDate(end.getDate() + 1);
  const out = { calendars: [] };
  const names = app.calendars.name();
  for (let i = 0; i < names.length; i++) {
    const began = Date.now();
    const found = app.calendars[i].events.whose({ _and: [
      { startDate: { _greaterThanOrEquals: start } },
      { startDate: { _lessThan: end } },
    ] });
    out.calendars.push({ title: names[i], events: found.length, ms: Date.now() - began });
  }
  return JSON.stringify(out);
}
"""


def run_jxa(script: str, timeout: int) -> Tuple[Optional[Dict[str, Any]], str, float]:
    """Run a JavaScript for Automation script; return (its JSON result or None, a problem, seconds taken).

    The problem is '' when the script ran and returned JSON.
    """
    began = time.monotonic()
    try:
        # The script goes in on standard input, so it is never parsed as command-line options.
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-"],
            input=script, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except FileNotFoundError:
        return None, "osascript not found: this diagnostic only runs on macOS.", 0.0
    except subprocess.TimeoutExpired:
        return None, f"No answer within {timeout} seconds (a permission prompt left open?).", time.monotonic() - began
    seconds = time.monotonic() - began
    if result.returncode != 0:
        return None, f"osascript failed: {result.stderr.strip() or 'no message'}", seconds
    try:
        return json.loads(result.stdout), "", seconds
    except ValueError:
        return None, f"Unexpected output: {result.stdout.strip()[:300]!r}", seconds


def describe_status(code: Optional[int]) -> str:
    """Describe an EventKit authorization status code."""
    return AUTH_STATUS.get(code, f"unknown ({code})") if code is not None else "unknown"


def event_line(event: Dict[str, Any], hide_titles: bool) -> str:
    """Describe one event as Today would order it, e.g. "  9:30 AM–10:00 AM  Standup  [Work]"."""
    if event.get("all_day"):
        when = "all day"
    else:
        start, end = (datetime.fromtimestamp(event[k]).strftime("%-I:%M %p") for k in ("start", "end"))
        when = f"{start}–{end}"
    title = "(title hidden)" if hide_titles else event.get("title") or "(no title)"
    notes = [EVENT_STATUS[event["status"]]] if event.get("status") in EVENT_STATUS else []
    if event.get("repeating"):
        notes.append("repeating")
    extra = f" ({', '.join(notes)})" if notes else ""
    return f"  {when:<19} {title}  [{event.get('calendar', '')}]{extra}"


def ordered_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Order events as Things' Today shows them: all-day first, then by start time."""
    return sorted(events, key=lambda e: (not e.get("all_day"), e.get("start", 0), e.get("title", "")))


def report_eventkit(result: Optional[Dict[str, Any]], problem: str, seconds: float, hide_titles: bool) -> None:
    """Print what the EventKit check found."""
    print("\nEventKit (the planned way)")
    if result is None:
        print(f"  Could not run: {problem}")
        return
    print(f"  macOS: {result.get('macos', '?')}")
    print(f"  Access before this run: {describe_status(result.get('status_before'))}")
    request = result.get("request")
    if request:
        answer = "granted" if request.get("granted") else "not granted"
        if not request.get("answered"):
            answer = "no answer (the prompt may not have appeared)"
        print(f"  Asked for access ({request.get('method', '?')}): {answer}"
              + (f"; {request['error']}" if request.get("error") else ""))
    print(f"  Access now: {describe_status(result.get('status'))}")
    if result.get("status") != 3:
        print("  Without full access no events can be read.")
        print("  Check System Settings › Privacy & Security › Calendars for Terminal, and send this output.")
        return
    calendars = result.get("calendars", [])
    print(f"  Calendars: {len(calendars)}")
    for calendar in calendars:
        print(f"  - {calendar['title']} ({calendar['source'] or 'no account'}) {calendar['color']}")
    events = result.get("events", [])
    print(f"  Today's events: {len(events)}")
    for event in ordered_events(events):
        print(event_line(event, hide_titles))
    print(f"  Time: {result.get('read_ms', '?')} ms to read, {seconds:.1f} s for the whole run")


def report_applescript(result: Optional[Dict[str, Any]], problem: str, seconds: float) -> None:
    """Print what the AppleScript comparison found."""
    print("\nAppleScript through the Calendar app (fallback, for comparison)")
    if result is None:
        print(f"  Could not run: {problem}")
        return
    for calendar in result.get("calendars", []):
        print(f"  - {calendar['title']}: {calendar['events']} event(s) starting today, {calendar['ms']} ms")
    print(f"  Time: {seconds:.1f} s for the whole run")


def run() -> None:
    """Print the calendar diagnostic report."""
    parser = argparse.ArgumentParser(description="Check whether Do Things can read today's calendar events.")
    parser.add_argument("--applescript", action="store_true", help="also time reading through the Calendar app")
    parser.add_argument("--hide-titles", action="store_true", help="hide event titles in the output")
    args = parser.parse_args()
    print(f"Do Things v{PROJECT_VERSION} calendar diagnostic")
    print(f"Python {platform.python_version()}, macOS {platform.mac_ver()[0] or 'unknown'}")
    report_eventkit(*run_jxa(EVENTKIT_SCRIPT, EVENTKIT_TIMEOUT_SECONDS), args.hide_titles)
    if args.applescript:
        report_applescript(*run_jxa(APPLESCRIPT_SCRIPT, APPLESCRIPT_TIMEOUT_SECONDS))
    print(f"\nDo Things v{PROJECT_VERSION} complete: calendar diagnostic finished")


if __name__ == "__main__":
    run()
