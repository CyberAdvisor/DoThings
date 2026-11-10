"""Tests for debug_calendar.py: running osascript, and the report it prints.

osascript is replaced with mocks, so these run anywhere; the JavaScript for
Automation itself can only run on a Mac.

Version: 1.7.1

Change log:
- v1.7.1 (2026-11-10): New.
"""

import io
import json
import os
import subprocess
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest import mock

import debug_calendar
from debug_calendar import describe_status, event_line, ordered_events, report_eventkit, run_jxa


def at(hour: int, minute: int = 0) -> float:
    """Unix time of today at hour:minute, local time."""
    return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()


def event(title: str, start: float = 0, end: float = 0, all_day: bool = False, **extra: object) -> dict:
    """An event as the EventKit script returns it."""
    fields = dict(id=title, title=title, all_day=all_day, start=start, end=end, calendar="Work", status=1,
                  repeating=False)
    fields.update(extra)
    return fields


class RunJxaTests(unittest.TestCase):
    """run_jxa passes the script on standard input and reports every way it can fail."""

    def test_json_result(self) -> None:
        done = subprocess.CompletedProcess([], 0, stdout='{"status": 3}\n', stderr="")
        with mock.patch("debug_calendar.subprocess.run", return_value=done) as ran:
            result, problem, _ = run_jxa("script", 5)
        self.assertEqual((result, problem), ({"status": 3}, ""))
        self.assertEqual(ran.call_args[0][0], ["osascript", "-l", "JavaScript", "-"])
        self.assertEqual(ran.call_args[1]["input"], "script")

    def test_failures(self) -> None:
        cases = (
            (FileNotFoundError(), "only runs on macOS"),
            (subprocess.TimeoutExpired("osascript", 5), "No answer within 5 seconds"),
            (subprocess.CompletedProcess([], 1, stdout="", stderr="execution error: -1743\n"), "osascript failed: execution error: -1743"),
            (subprocess.CompletedProcess([], 0, stdout="not json", stderr=""), "Unexpected output"),
        )
        for outcome, message in cases:
            with self.subTest(message=message):
                kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with mock.patch("debug_calendar.subprocess.run", **kwargs):
                    result, problem, _ = run_jxa("script", 5)
                self.assertIsNone(result)
                self.assertIn(message, problem)


class ReportTests(unittest.TestCase):
    """The report: access states, event order and wording, hidden titles."""

    def setUp(self) -> None:
        # Times print in the local zone; fix it so the wording is predictable.
        self.zone = os.environ.get("TZ")
        os.environ["TZ"] = "America/Denver"
        time.tzset()

    def tearDown(self) -> None:
        if self.zone is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = self.zone
        time.tzset()

    def report(self, result: object, problem: str = "", hide_titles: bool = False) -> str:
        """Return what report_eventkit prints."""
        out = io.StringIO()
        with redirect_stdout(out):
            report_eventkit(result, problem, 1.5, hide_titles)
        return out.getvalue()

    def test_describe_status(self) -> None:
        self.assertEqual(describe_status(3), "full access")
        self.assertIn("denied", describe_status(2))
        self.assertEqual(describe_status(9), "unknown (9)")
        self.assertEqual(describe_status(None), "unknown")

    def test_events_ordered_all_day_first_then_by_start(self) -> None:
        events = [event("Lunch", at(12), at(13)), event("Holiday", all_day=True), event("Standup", at(9, 30), at(10))]
        self.assertEqual([e["title"] for e in ordered_events(events)], ["Holiday", "Standup", "Lunch"])

    def test_event_line(self) -> None:
        line = event_line(event("Standup", at(9, 30), at(10)), hide_titles=False)
        self.assertEqual(line, "  9:30 AM–10:00 AM    Standup  [Work]")
        line = event_line(event("Trip", all_day=True, status=3, repeating=True), hide_titles=True)
        self.assertEqual(line, "  all day" + " " * 13 + "(title hidden)  [Work] (canceled, repeating)")

    def test_full_access_report(self) -> None:
        result = {"macos": "Version 15.1", "status_before": 3, "status": 3, "read_ms": 40,
                  "calendars": [{"id": "c1", "title": "Work", "source": "iCloud", "color": "#1badf8"}],
                  "events": [event("Lunch", at(12), at(13)), event("Holiday", all_day=True)]}
        text = self.report(json.loads(json.dumps(result)))
        self.assertIn("Access now: full access", text)
        self.assertIn("- Work (iCloud) #1badf8", text)
        self.assertLess(text.index("Holiday"), text.index("Lunch"))
        self.assertIn("40 ms to read", text)

    def test_denied_and_unanswered(self) -> None:
        text = self.report({"status_before": 0, "status": 0,
                            "request": {"method": "requestFullAccessToEventsWithCompletion", "answered": False}})
        self.assertIn("no answer (the prompt may not have appeared)", text)
        self.assertIn("Privacy & Security › Calendars", text)
        self.assertNotIn("Calendars: ", text)
        text = self.report({"status_before": 2, "status": 2})
        self.assertIn("Access now: denied", text)

    def test_could_not_run(self) -> None:
        self.assertIn("Could not run: osascript not found", self.report(None, "osascript not found"))

    def test_run_prints_both_parts(self) -> None:
        out = io.StringIO()
        with mock.patch("sys.argv", ["debug_calendar.py", "--applescript"]), redirect_stdout(out), \
                mock.patch.object(debug_calendar, "run_jxa", return_value=(None, "osascript not found", 0.0)) as ran:
            debug_calendar.run()
        self.assertEqual(ran.call_count, 2)
        self.assertIn("AppleScript through the Calendar app", out.getvalue())
        self.assertIn("complete: calendar diagnostic finished", out.getvalue())


if __name__ == "__main__":
    unittest.main()
