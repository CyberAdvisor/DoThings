"""Read-only calendar diagnostic for Do Things.

Checks that Do Things can show today's calendar events in Today, as Things
does. It runs the same script Do Things uses (EventKit, the macOS calendar
framework, from JavaScript for Automation) and prints whether macOS grants
calendar access to the app running it (Terminal or Shortcuts), the calendars
it can see, today's events as Today would show them and how long reading
them took.

It only reads. If macOS hasn't asked yet, it asks for calendar access (that
answer is a macOS setting, not a change to any calendar). Nothing is written
to Calendar, Things or any Do Things file. --hide-titles replaces event
titles with "(title hidden)", for sharing the output.

Version: 2.0.1

Change log:
- v2.0.1 (2026-11-10): Synchronized module version metadata.
- v2.0.0 (2026-11-10): Synchronized module version metadata.
- v1.9.2 (2026-11-10): Synchronized module version metadata.
- v1.9.1 (2026-11-10): Synchronized module version metadata.
- v1.9.0 (2026-11-10): Synchronized module version metadata.
- v1.8.0 (2026-11-10): Uses the calendar script shared with Do Things
  (common.run_calendar_script) and Today's ordering and time labels
  (calendar_check); the AppleScript comparison (--applescript) is removed,
  since EventKit works.
- v1.7.1 (2026-11-10): New. Calendar access check through EventKit, with an
  optional AppleScript comparison.
"""

import argparse
import platform
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from calendar_check import STATUS_CANCELED, Event, event_time_label, order_events, parse_calendar_output
from common import PROJECT_VERSION, run_calendar_script, start_of_day

# EKAuthorizationStatus values. On macOS 14 and later 3 means full access;
# on earlier versions it is the single "authorized" state.
AUTH_STATUS = {
    0: "not determined (macOS hasn't asked yet)",
    1: "restricted (blocked by a profile or parental controls)",
    2: "denied",
    3: "full access",
    4: "write only (can add events but not read them)",
}


def describe_status(code: Optional[int]) -> str:
    """Describe an EventKit authorization status code."""
    return AUTH_STATUS.get(code, f"unknown ({code})") if code is not None else "unknown"


def event_line(event: Event, day_start: float, day_end: float, hide_titles: bool) -> str:
    """Describe one event as Today shows it, e.g. "  9:30 – 10:00 AM    Standup  [Work]"."""
    title = "(title hidden)" if hide_titles else event.title
    note = " (canceled, not shown in Today)" if event.status == STATUS_CANCELED else ""
    return f"  {event_time_label(event, day_start, day_end):<19} {title}  [{event.calendar}]{note}"


def report(raw: Optional[Dict[str, Any]], problem: str, seconds: float, hide_titles: bool) -> None:
    """Print what the calendar script found."""
    print("\nCalendar (EventKit)")
    if raw is None:
        print(f"  Could not run: {problem}")
        return
    print(f"  Access before this run: {describe_status(raw.get('status_before'))}")
    request = raw.get("request")
    if request:
        answer = "answered" if request.get("answered") else "no answer (the prompt may not have appeared)"
        print(f"  Asked for access ({request.get('method', '?')}): {answer}"
              + (f"; {request['error']}" if request.get("error") else ""))
    print(f"  Access now: {describe_status(raw.get('status'))}")
    read = parse_calendar_output(raw)
    if read.access != "allowed":
        print("  Without full access no events can be read.")
        print("  Check System Settings › Privacy & Security › Calendars for Terminal, and send this output.")
        return
    print(f"  Calendars: {len(read.calendars)}")
    for calendar in read.calendars:
        print(f"  - {calendar.title} ({calendar.source or 'no account'}) {calendar.color}")
    today = date.today()
    day_start, day_end = start_of_day(today), start_of_day(today + timedelta(days=1))
    print(f"  Today's events ({today.isoformat()}): {len(read.events)}")
    for event in order_events(read.events):
        print(event_line(event, day_start, day_end, hide_titles))
    print(f"  Time: {raw.get('read_ms', '?')} ms to read, {seconds:.1f} s for the whole run")


def run() -> None:
    """Print the calendar diagnostic report."""
    parser = argparse.ArgumentParser(description="Check whether Do Things can read today's calendar events.")
    parser.add_argument("--hide-titles", action="store_true", help="hide event titles in the output")
    args = parser.parse_args()
    print(f"Do Things v{PROJECT_VERSION} calendar diagnostic")
    print(f"Python {platform.python_version()}, macOS {platform.mac_ver()[0] or 'unknown'}, "
          f"{datetime.now().astimezone().strftime('%H:%M %Z')}")
    began = time.monotonic()
    raw, problem = run_calendar_script(request_access=True)
    report(raw, problem, time.monotonic() - began, args.hide_titles)
    print(f"\nDo Things v{PROJECT_VERSION} complete: calendar diagnostic finished")


if __name__ == "__main__":
    run()
