"""Tests for debug_calendar.py: the report it prints.

The calendar script is replaced with mocks, so these run anywhere; the
JavaScript for Automation itself can only run on a Mac.

Version: 1.9.1

Change log:
- v1.9.1 (2026-11-10): Synchronized module version metadata.
- v1.9.0 (2026-11-10): Synchronized module version metadata.
- v1.8.0 (2026-11-10): Report built from calendar_check (Today's order and
  labels); the osascript tests moved to test_common.py with run_jxa; the
  AppleScript comparison is gone.
- v1.7.1 (2026-11-10): New.
"""

import io
import os
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest import mock

import debug_calendar
from debug_calendar import describe_status, report


def at(hour: int, minute: int = 0) -> float:
    """Unix time of today at hour:minute, local time."""
    return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()


def raw_event(title: str, start: float, end: float, all_day: bool = False, status: int = 1) -> dict:
    """An event as the calendar script returns it."""
    return {"id": title.replace(" ", "-"), "title": title, "all_day": all_day, "start": start, "end": end,
            "calendar_id": "c1", "calendar": "Work", "status": status}


class ReportTests(unittest.TestCase):
    """The report: access states, event order and wording, hidden titles."""

    def setUp(self) -> None:
        self.zone = os.environ.get("TZ")
        os.environ["TZ"] = "America/Denver"
        time.tzset()

    def tearDown(self) -> None:
        if self.zone is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = self.zone
        time.tzset()

    def report(self, raw: object, problem: str = "", hide_titles: bool = False) -> str:
        """Return what report prints."""
        out = io.StringIO()
        with redirect_stdout(out):
            report(raw, problem, 0.2, hide_titles)
        return out.getvalue()

    def test_describe_status(self) -> None:
        self.assertEqual(describe_status(3), "full access")
        self.assertIn("denied", describe_status(2))
        self.assertEqual(describe_status(9), "unknown (9)")
        self.assertEqual(describe_status(None), "unknown")

    def test_full_access_report(self) -> None:
        raw = {"status_before": 3, "status": 3, "read_ms": 19,
               "calendars": [{"id": "c1", "title": "Work", "source": "iCloud", "color": "#1badf8"}],
               "events": [raw_event("Lunch", at(12), at(13)), raw_event("Holiday", at(0), at(0), all_day=True),
                          raw_event("Gone", at(9), at(10), status=3)]}
        text = self.report(raw, hide_titles=False)
        self.assertIn("Access now: full access", text)
        self.assertIn("- Work (iCloud) #1badf8", text)
        self.assertLess(text.index("Holiday"), text.index("Lunch"))
        self.assertIn("12:00 – 1:00 PM     Lunch  [Work]", text)
        self.assertIn("Gone  [Work] (canceled, not shown in Today)", text)
        self.assertIn("19 ms to read", text)
        hidden = self.report(raw, hide_titles=True)
        self.assertNotIn("Lunch", hidden)
        self.assertEqual(hidden.count("(title hidden)"), 3)

    def test_asked_and_not_allowed(self) -> None:
        text = self.report({"status_before": 0, "status": 0,
                            "request": {"method": "requestFullAccessToEventsWithCompletion", "answered": False}})
        self.assertIn("no answer (the prompt may not have appeared)", text)
        self.assertIn("Privacy & Security › Calendars", text)
        self.assertNotIn("Calendars: ", text)
        self.assertIn("Access now: denied", self.report({"status_before": 2, "status": 2}))

    def test_could_not_run(self) -> None:
        self.assertIn("Could not run: osascript not found", self.report(None, "osascript not found"))

    def test_run_asks_then_reports(self) -> None:
        out = io.StringIO()
        with mock.patch("sys.argv", ["debug_calendar.py", "--hide-titles"]), redirect_stdout(out), \
                mock.patch.object(debug_calendar, "run_calendar_script", return_value=(None, "not a Mac")) as ran:
            debug_calendar.run()
        ran.assert_called_once_with(request_access=True)
        self.assertIn("Could not run: not a Mac", out.getvalue())
        self.assertIn("complete: calendar diagnostic finished", out.getvalue())


if __name__ == "__main__":
    unittest.main()
