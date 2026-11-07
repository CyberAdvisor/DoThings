"""Tests for common.py: token handling, Things dates, URLs, order file and database queries.

Database tests run against a small SQLite file built with the parts of the
Things schema that Do Things reads, so no real Things data is touched.

Version: 0.1.10

Change log:
- v0.1.10 (2026-11-07): Tests for count_inbox and read_checklist_progress.
- v0.1.9 (2026-11-07): Synchronized module version metadata.
- v0.1.8 (2026-11-07): Dropped the repeating-copy column and checks.
- v0.1.7 (2026-11-07): Tests for the edit fields read from the database,
  read_edit_options, and the new update URL parameters.
- v0.1.6 (2026-11-07): Tests for tasks completed today appearing in the lists
  (and earlier or canceled ones not), and for complete/reopen URLs.
- v0.1.5 (2026-11-07): Dropped tests for the lists that now open in Things;
  Things schema values not used by common.py are defined here; test for
  opening a Things list by URL.
- v0.1.4 (2026-11-07): Synchronized module version metadata.
- v0.1.3 (2026-11-07): Synchronized module version metadata.
- v0.1.2 (2026-11-07): Tests that to-dos under a trashed, completed or canceled
  project or heading are left out of the lists.
- v0.1.1 (2026-11-07): Test for the `when` parameter in update URLs.
- v0.1.0 (2026-11-07): Initial release.
"""

import contextlib
import os
import sqlite3
import stat
import tempfile
import unittest
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Iterator

from common import (
    LOCAL_TZ,
    START_ANYTIME,
    START_INBOX,
    START_SOMEDAY,
    STATUS_COMPLETED,
    STATUS_OPEN,
    THINGS_LISTS,
    build_show_url,
    build_update_url,
    count_inbox,
    is_valid_task_id,
    load_order,
    load_token,
    missing_priority_tags,
    open_things_db,
    pack_things_date,
    read_checklist_progress,
    read_edit_options,
    read_list,
    read_task,
    save_order,
    save_token,
    unpack_things_date,
    validate_token,
)
from priority_check import Change

TODAY = date(2026, 11, 7)


@contextlib.contextmanager
def write_db(path: str) -> Iterator[sqlite3.Connection]:
    """Open the mock database for writing; commit and close it afterwards."""
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        yield conn

# Things values the mock data needs that common.py's queries don't use.
STATUS_CANCELED = 2

SCHEMA = """
CREATE TABLE TMTask (
    uuid TEXT PRIMARY KEY, title TEXT, type INTEGER, status INTEGER, trashed INTEGER,
    start INTEGER, startDate INTEGER, deadline INTEGER, deadlineSuppressionDate INTEGER,
    todayIndex INTEGER, "index" INTEGER, project TEXT, heading TEXT, area TEXT,
    stopDate REAL, rt1_recurrenceRule BLOB, notes TEXT
);
CREATE TABLE TMArea (uuid TEXT PRIMARY KEY, title TEXT);
CREATE TABLE TMTag (uuid TEXT PRIMARY KEY, title TEXT);
CREATE TABLE TMTaskTag (tasks TEXT, tags TEXT);
CREATE TABLE TMChecklistItem (uuid TEXT PRIMARY KEY, title TEXT, status INTEGER, task TEXT, "index" INTEGER);
"""


class TokenTests(unittest.TestCase):
    """Token format checks and owner-only storage."""

    def test_valid_token_is_trimmed(self) -> None:
        self.assertEqual(validate_token("  abc123\n"), "abc123")

    def test_invalid_tokens_rejected(self) -> None:
        for bad in ("", "   ", "abc 123", "abc\n123", None, 42):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_token(bad)

    def test_save_and_load_with_owner_only_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "auth_token.txt")
            save_token(" secret-token ", path)
            self.assertEqual(load_token(path), "secret-token")
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_missing_token_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(load_token(os.path.join(folder, "none.txt")))


class ThingsDateTests(unittest.TestCase):
    """Things' packed date format."""

    def test_round_trip(self) -> None:
        for day in (date(2026, 1, 1), date(2026, 11, 7), date(2027, 12, 31)):
            self.assertEqual(unpack_things_date(pack_things_date(day)), day)

    def test_known_value(self) -> None:
        # 2026-11-07 -> 2026 << 16 | 11 << 12 | 7 << 7
        self.assertEqual(pack_things_date(TODAY), 132_775_936 + 45_056 + 896)

    def test_empty_and_invalid(self) -> None:
        self.assertIsNone(unpack_things_date(None))
        self.assertIsNone(unpack_things_date(0))
        self.assertIsNone(unpack_things_date((2026 << 16) | (13 << 12) | (1 << 7)))


class UrlTests(unittest.TestCase):
    """Things URL building."""

    def _params(self, url: str) -> dict:
        return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)

    def test_update_sets_tags_and_deadline(self) -> None:
        url = build_update_url(Change("A1", ["Home Office", "P1"], set_deadline=TODAY), "tok")
        self.assertTrue(url.startswith("things:///update?"))
        params = self._params(url)
        self.assertEqual(params["id"], ["A1"])
        self.assertEqual(params["auth-token"], ["tok"])
        self.assertEqual(params["tags"], ["Home Office,P1"])
        self.assertEqual(params["deadline"], ["2026-11-07"])
        self.assertIn("tags=Home%20Office,P1", url)  # %20 for spaces, plain commas as Things documents.

    def test_update_clears_deadline(self) -> None:
        self.assertEqual(self._params(build_update_url(Change("A1", ["P2"], clear_deadline=True), "t"))["deadline"], [""])

    def test_update_sets_start_date(self) -> None:
        change = Change("A1", ["P2"], clear_deadline=True, set_start_date=TODAY)
        params = self._params(build_update_url(change, "t"))
        self.assertEqual(params["when"], ["2026-11-07"])
        self.assertEqual(params["deadline"], [""])

    def test_complete_and_reopen_leave_tags_alone(self) -> None:
        for completed, value in ((True, "true"), (False, "false")):
            with self.subTest(completed=completed):
                params = self._params(build_update_url(Change("A1", None, set_completed=completed), "t"))
                self.assertEqual(params["completed"], [value])
                self.assertNotIn("tags", params)

    def test_edit_fields_in_url(self) -> None:
        change = Change("A1", None, set_title="New & title", set_notes="Line 1\nLine 2",
                        set_when="someday", set_list_id="P9", set_heading_id="H9")
        params = self._params(build_update_url(change, "t"))
        self.assertEqual(params["title"], ["New & title"])
        self.assertEqual(params["notes"], ["Line 1\nLine 2"])
        self.assertEqual(params["when"], ["someday"])
        self.assertEqual(params["list-id"], ["P9"])
        self.assertEqual(params["heading-id"], ["H9"])
        self.assertNotIn("tags", params)

    def test_update_leaves_deadline(self) -> None:
        params = self._params(build_update_url(Change("A1", ["P2"]), "t"))
        self.assertNotIn("deadline", params)
        self.assertNotIn("when", params)

    def test_comma_in_tag_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_update_url(Change("A1", ["a,b", "P2"]), "t")

    def test_show_url(self) -> None:
        self.assertEqual(build_show_url("A1"), "things:///show?id=A1")
        for name in THINGS_LISTS:
            self.assertEqual(build_show_url(name), f"things:///show?id={name}")

    def test_task_id_validation(self) -> None:
        self.assertTrue(is_valid_task_id("7Xn3kQpL2mR9sT4vW8yZ1a"))
        for bad in ("", "a b", "a;rm", "x" * 65, None, 5):
            self.assertFalse(is_valid_task_id(bad))


class OrderFileTests(unittest.TestCase):
    """Saved task order."""

    def test_round_trip_and_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "task_order.json")
            self.assertEqual(load_order(path), {})
            save_order({"P1": ["A"], "P2": ["B", "C"]}, path)
            self.assertEqual(load_order(path), {"P1": ["A"], "P2": ["B", "C"]})
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            # assertLogs captures the error so tests never write to errors.log.
            with self.assertLogs("dothings", level="ERROR"):
                self.assertEqual(load_order(path), {})


class DatabaseTests(unittest.TestCase):
    """List queries against a mock Things database."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.folder.name, "main.sqlite")
        conn = sqlite3.connect(self.path)
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO TMTag VALUES (?, ?)", [("t1", "P1"), ("t2", "P2"), ("t3", "Home, Office")])
        conn.execute("INSERT INTO TMArea VALUES ('area1', 'Work')")
        today = pack_things_date(TODAY)
        past = pack_things_date(TODAY - timedelta(days=3))
        future = pack_things_date(TODAY + timedelta(days=3))
        tasks = [
            # uuid, title, type, status, trashed, start, startDate, deadline, todayIndex, project, area
            ("today1", "Started today", 0, STATUS_OPEN, 0, START_ANYTIME, today, None, 2, "proj1", None),
            ("today2", "Started earlier", 0, STATUS_OPEN, 0, START_ANYTIME, past, None, 1, None, "area1"),
            ("overdue", "Overdue anytime", 0, STATUS_OPEN, 0, START_ANYTIME, None, past, 3, None, None),
            ("future", "Upcoming", 0, STATUS_OPEN, 0, START_SOMEDAY, future, None, 0, None, None),
            ("someday", "Someday", 0, STATUS_OPEN, 0, START_SOMEDAY, None, None, 0, None, None),
            ("inbox", "Inbox", 0, STATUS_OPEN, 0, START_INBOX, None, None, 0, None, None),
            ("anytime", "Anytime", 0, STATUS_OPEN, 0, START_ANYTIME, None, None, 0, None, None),
            ("done", "Done", 0, STATUS_COMPLETED, 0, START_ANYTIME, today, None, 0, None, None),
            ("trashed", "Trashed", 0, STATUS_OPEN, 1, START_ANYTIME, today, None, 0, None, None),
            ("proj1", "Project", 1, STATUS_OPEN, 0, START_ANYTIME, today, None, 0, None, None),
        ]
        conn.executemany(
            "INSERT INTO TMTask (uuid, title, type, status, trashed, start, startDate, deadline, "
            "todayIndex, project, area, \"index\") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            tasks,
        )
        # Parents that hide their to-dos, and open to-dos inside them. Each child
        # would be in Today and tagged P1 if only its own row were checked.
        parents = [
            # uuid, title, type, status, trashed, project
            ("trashproj", "Trashed project", 1, STATUS_OPEN, 1, None),
            ("doneproj", "Completed project", 1, STATUS_COMPLETED, 0, None),
            ("cancelproj", "Canceled project", 1, STATUS_CANCELED, 0, None),
            ("trashhead", "Trashed heading", 2, STATUS_OPEN, 1, "proj1"),
            ("donehead", "Archived heading", 2, STATUS_COMPLETED, 0, "proj1"),
            ("headintrash", "Heading in trashed project", 2, STATUS_OPEN, 0, "trashproj"),
        ]
        conn.executemany(
            "INSERT INTO TMTask (uuid, title, type, status, trashed, project, start, \"index\") "
            f"VALUES (?, ?, ?, ?, ?, ?, {START_ANYTIME}, 0)",
            parents,
        )
        children = [
            # uuid, status, project, heading
            ("in_trashproj", STATUS_OPEN, "trashproj", None),
            ("in_doneproj", STATUS_OPEN, "doneproj", None),
            ("in_cancelproj", STATUS_OPEN, "cancelproj", None),
            ("in_trashhead", STATUS_OPEN, None, "trashhead"),
            ("in_donehead", STATUS_OPEN, None, "donehead"),
            ("in_headintrash", STATUS_OPEN, None, "headintrash"),
            ("done_in_trashproj", STATUS_COMPLETED, "trashproj", None),
        ]
        conn.executemany(
            "INSERT INTO TMTask (uuid, title, type, status, trashed, start, startDate, todayIndex, "
            f"project, heading, \"index\") VALUES (?, ?, 0, ?, 0, {START_ANYTIME}, {today}, 0, ?, ?, 0)",
            [(uuid, uuid, status, project, heading) for uuid, status, project, heading in children],
        )
        conn.executemany(
            "INSERT INTO TMTaskTag VALUES (?, ?)",
            [("today1", "t1"), ("today1", "t3"), ("anytime", "t2")]
            + [(uuid, "t1") for uuid, _, _, _ in children],
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.folder.cleanup()

    def _ids(self, name: str) -> list:
        with open_things_db(self.path) as conn:
            return [t.uuid for t in read_list(conn, name, TODAY)]

    def test_completed_today_listed_earlier_and_canceled_not(self) -> None:
        midnight = datetime.combine(TODAY, datetime.min.time(), tzinfo=LOCAL_TZ).timestamp()
        started = pack_things_date(TODAY)
        rows = [
            # uuid, status, stopDate
            ("done_today", STATUS_COMPLETED, midnight + 60),
            ("done_yesterday", STATUS_COMPLETED, midnight - 60),
            ("canceled_today", STATUS_CANCELED, midnight + 60),
        ]
        with write_db(self.path) as conn:
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, startDate, deadline, "
                f"stopDate, todayIndex, \"index\") VALUES (?, ?, 0, ?, 0, {START_ANYTIME}, ?, ?, ?, 9, 0)",
                [(uuid, uuid, status, started, started, stop) for uuid, status, stop in rows],
            )
            conn.executemany("INSERT INTO TMTaskTag VALUES (?, 't1')", [(r[0],) for r in rows])
        for name in ("today", "p1"):
            with self.subTest(name=name):
                ids = self._ids(name)
                self.assertIn("done_today", ids)
                self.assertNotIn("done_yesterday", ids)
                self.assertNotIn("canceled_today", ids)
        with open_things_db(self.path) as conn:
            self.assertEqual(read_task(conn, "done_today").completed_at, midnight + 60)
            self.assertIsNone(read_task(conn, "today1").completed_at)

    def test_today_membership_and_order(self) -> None:
        self.assertEqual(self._ids("today"), ["today2", "today1", "overdue"])

    def test_custom_searches(self) -> None:
        self.assertEqual(self._ids("p1"), ["today1"])
        self.assertEqual(self._ids("p2"), ["anytime"])
        self.assertEqual(self._ids("overdue"), ["overdue"])

    def test_todos_under_closed_or_trashed_parents_hidden(self) -> None:
        # Today and P1 are checked against the expected lists in the tests
        # above; this names the hidden to-dos explicitly.
        hidden = {
            "in_trashproj", "in_doneproj", "in_cancelproj",
            "in_trashhead", "in_donehead", "in_headintrash", "done_in_trashproj",
        }
        for name in ("today", "p1", "overdue"):
            with self.subTest(name=name):
                self.assertFalse(hidden & set(self._ids(name)))

    def test_edit_fields_read(self) -> None:
        with write_db(self.path) as conn:
            conn.execute(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, project, \"index\") "
                f"VALUES ('head1', 'Heading', 2, {STATUS_OPEN}, 0, 'proj1', 0)"
            )
            conn.execute(
                "INSERT INTO TMTask (uuid, title, notes, type, status, trashed, start, heading, "
                f"\"index\") VALUES ('undr', 'Under heading', 'Some notes', 0, "
                f"{STATUS_OPEN}, 0, {START_SOMEDAY}, 'head1', 0)"
            )
        with open_things_db(self.path) as conn:
            task = read_task(conn, "undr")
            self.assertEqual((task.notes, task.list_id, task.heading_id), ("Some notes", "proj1", "head1"))
            self.assertTrue(task.someday)
            plain = read_task(conn, "today2")
            self.assertEqual((plain.notes, plain.list_id, plain.heading_id), ("", "area1", None))
            self.assertFalse(plain.someday)
            options = read_edit_options(conn)
        self.assertEqual(options["tags"], ["Home, Office"])
        self.assertEqual(options["areas"], [{"id": "area1", "title": "Work"}])
        # Completed, canceled and trashed projects, and closed or trashed headings, are left out.
        self.assertEqual([p["id"] for p in options["projects"]], ["proj1"])
        self.assertIn({"id": "head1", "title": "Heading", "project": "proj1"}, options["headings"])
        self.assertNotIn("trashhead", [h["id"] for h in options["headings"]])
        self.assertNotIn("donehead", [h["id"] for h in options["headings"]])

    def test_count_inbox(self) -> None:
        with open_things_db(self.path) as conn:
            self.assertEqual(count_inbox(conn), 1)  # The open, untrashed "inbox" task.
        with write_db(self.path) as conn:
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, \"index\") "
                f"VALUES (?, ?, 0, ?, ?, {START_INBOX}, 0)",
                [("in2", "Open", STATUS_OPEN, 0), ("in3", "Done", STATUS_COMPLETED, 0),
                 ("in4", "Trashed", STATUS_OPEN, 1)],
            )
        with open_things_db(self.path) as conn:
            self.assertEqual(count_inbox(conn), 2)

    def test_checklist_progress(self) -> None:
        with write_db(self.path) as conn:
            conn.executemany(
                "INSERT INTO TMChecklistItem VALUES (?, ?, ?, 'today1', 0)",
                [("c1", "One", STATUS_OPEN), ("c2", "Two", STATUS_COMPLETED), ("c3", "Three", STATUS_CANCELED)],
            )
        with open_things_db(self.path) as conn:
            self.assertEqual(read_checklist_progress(conn, "today1"), {"done": 2, "total": 3})
            self.assertEqual(read_checklist_progress(conn, "today2"), {"done": 0, "total": 0})

    def test_task_fields(self) -> None:
        with open_things_db(self.path) as conn:
            task = read_task(conn, "today1")
            self.assertEqual(sorted(task.tags), ["Home, Office", "P1"])
            self.assertEqual(task.start_date, TODAY)
            self.assertEqual(task.context, "Project")
            self.assertEqual(read_task(conn, "today2").context, "Work")
            self.assertIsNone(read_task(conn, "missing"))
            self.assertEqual(missing_priority_tags(conn), ["P3"])

    def test_database_is_read_only(self) -> None:
        with open_things_db(self.path) as conn, self.assertRaises(sqlite3.OperationalError):
            conn.execute("DELETE FROM TMTask")

    def test_unknown_list_rejected(self) -> None:
        with open_things_db(self.path) as conn:
            for name in ("nope",) + THINGS_LISTS:
                with self.assertRaises(ValueError):
                    read_list(conn, name, TODAY)


if __name__ == "__main__":
    unittest.main()
