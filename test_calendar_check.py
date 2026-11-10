"""Tests for calendar_check.py: checking the calendar script's output, ordering, labels and states.

Version: 1.8.0

Change log:
- v1.8.0 (2026-11-10): New.
"""

import os
import time
import unittest
from datetime import datetime

from calendar_check import (
    ACCESS_UNAVAILABLE,
    DEFAULT_COLOR,
    Event,
    event_state,
    event_time_label,
    is_valid_event_id,
    order_events,
    parse_calendar_output,
    visible_events,
)


def at(hour: int, minute: int = 0, day: int = 10) -> float:
    """Unix time of 2026-11-<day> at hour:minute, local time."""
    return datetime(2026, 11, day, hour, minute).timestamp()


def event(title: str = "E", start: float = 0, end: float = 0, all_day: bool = False, calendar_id: str = "c1",
          status: int = 0) -> Event:
    """An event for tests."""
    return Event(id=f"id-{title}", title=title, all_day=all_day, start=start, end=end, calendar_id=calendar_id,
                 calendar="Work", color="#0088ff", status=status)


class LocalTimeTestCase(unittest.TestCase):
    """Times are worded in the local zone; fix it so the tests are predictable."""

    def setUp(self) -> None:
        self.zone = os.environ.get("TZ")
        os.environ["TZ"] = "America/Denver"
        time.tzset()
        self.day_start, self.day_end = at(0), at(0, day=11)

    def tearDown(self) -> None:
        if self.zone is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = self.zone
        time.tzset()


class ParseTests(unittest.TestCase):
    """parse_calendar_output keeps what is well formed and fails safe on the rest."""

    def test_full_access(self) -> None:
        raw = {
            "status": 3,
            "calendars": [{"id": "c1", "title": "Home", "source": "iCloud", "color": "#0088ff"},
                          {"id": "c2", "title": "Odd", "source": "", "color": "blue"},
                          {"title": "No id"}],
            "events": [{"id": "E1:A", "title": "Dentist", "all_day": False, "start": 100, "end": 200,
                        "calendar_id": "c1", "calendar": "Home", "status": 1},
                       {"id": "E2", "title": "", "start": 100, "end": 100, "calendar_id": "c2", "calendar": "Odd"},
                       {"id": "bad id!", "start": 1, "end": 2},
                       {"id": "E3", "start": 200, "end": 100},
                       {"id": "E4", "start": "noon", "end": 1},
                       "not an event"],
        }
        read = parse_calendar_output(raw)
        self.assertEqual(read.access, "allowed")
        self.assertEqual([(c.id, c.color) for c in read.calendars], [("c1", "#0088ff"), ("c2", DEFAULT_COLOR)])
        self.assertEqual([e.id for e in read.events], ["E1:A", "E2"])
        self.assertEqual((read.events[0].color, read.events[0].status), ("#0088ff", 1))
        self.assertEqual((read.events[1].title, read.events[1].all_day), ("(No title)", False))

    def test_states(self) -> None:
        for status, access in ((0, "not_asked"), (1, "restricted"), (2, "denied"), (4, "write_only")):
            with self.subTest(status=status):
                read = parse_calendar_output({"status": status})
                self.assertEqual((read.access, read.calendars, read.events), (access, [], []))
        for raw in ([], {"status": 9}, {"calendars": []}, None):
            with self.subTest(raw=raw):
                read = parse_calendar_output(raw)
                self.assertEqual(read.access, ACCESS_UNAVAILABLE)
                self.assertTrue(read.problem)

    def test_event_ids(self) -> None:
        self.assertTrue(is_valid_event_id("8F2A-11:ABC.d_e@x"))
        for bad in ("", "a b", "a/b", "x" * 201, None, 5, "a?b=c"):
            with self.subTest(bad=bad):
                self.assertFalse(is_valid_event_id(bad))


class OrderTests(LocalTimeTestCase):
    """Today's order and which events show."""

    def test_order_all_day_first_then_start(self) -> None:
        events = [event("Lunch", at(12), at(13)), event("Holiday", all_day=True), event("standup", at(9), at(9, 15)),
                  event("Breakfast", at(9), at(10))]
        self.assertEqual([e.title for e in order_events(events)], ["Holiday", "Breakfast", "standup", "Lunch"])

    def test_hidden_calendars_and_canceled_left_out(self) -> None:
        events = [event("A", at(9), at(10)), event("B", at(8), at(9), calendar_id="c2"),
                  event("C", at(7), at(8), status=3)]
        self.assertEqual([e.title for e in visible_events(events, ["c2"])], ["A"])
        self.assertEqual([e.title for e in visible_events(events, [])], ["B", "A"])


class LabelTests(LocalTimeTestCase):
    """event_time_label words times as Calendar does."""

    def label(self, start: float, end: float, all_day: bool = False) -> str:
        """Label an event on 2026-11-10."""
        return event_time_label(event(start=start, end=end, all_day=all_day), self.day_start, self.day_end)

    def test_labels(self) -> None:
        self.assertEqual(self.label(at(0), at(0, day=11), all_day=True), "All day")
        self.assertEqual(self.label(at(9, 30), at(10, 30)), "9:30 – 10:30 AM")
        self.assertEqual(self.label(at(11), at(13)), "11:00 AM – 1:00 PM")
        self.assertEqual(self.label(at(12, 5), at(12, 45)), "12:05 – 12:45 PM")
        self.assertEqual(self.label(at(18, 5), at(18, 5)), "6:05 PM")  # No length.
        self.assertEqual(self.label(at(0, 5), at(0, 30)), "12:05 – 12:30 AM")

    def test_events_crossing_midnight(self) -> None:
        self.assertEqual(self.label(at(22, day=9), at(10)), "Until 10:00 AM")
        self.assertEqual(self.label(at(20), at(2, day=11)), "From 8:00 PM")
        self.assertEqual(self.label(at(20, day=9), at(2, day=11)), "All day")


class StateTests(LocalTimeTestCase):
    """event_state: ended events are dimmed and the current one highlighted."""

    def test_states(self) -> None:
        now = at(10)
        self.assertEqual(event_state(event(start=at(8), end=at(9)), now), "past")
        self.assertEqual(event_state(event(start=at(9), end=at(10)), now), "past")  # Just ended.
        self.assertEqual(event_state(event(start=at(9, 30), end=at(10, 30)), now), "now")
        self.assertEqual(event_state(event(start=at(10), end=at(11)), now), "now")  # Just started.
        self.assertIsNone(event_state(event(start=at(11), end=at(12)), now))
        self.assertIsNone(event_state(event(all_day=True, start=at(0), end=at(0, day=11)), now))
        self.assertEqual(event_state(event(start=at(9), end=at(9)), now), "past")  # No length, passed.
        self.assertIsNone(event_state(event(start=at(10), end=at(10)), now))  # No length, this minute.


if __name__ == "__main__":
    unittest.main()
