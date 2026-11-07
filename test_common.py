"""Tests for common.py: token handling, Things dates, URLs, order file and database queries.

Database tests run against a small SQLite file built with the parts of the
Things schema that Do Things reads, so no real Things data is touched.

Version: 0.1.4

Change log:
- v0.1.4 (2026-11-07): Synchronized module version metadata.
- v0.1.3 (2026-11-07): Synchronized module version metadata.
- v0.1.2 (2026-11-07): Tests that to-dos under a trashed, completed or canceled
  project or heading are left out of the lists.
- v0.1.1 (2026-11-07): Test for the `when` parameter in update URLs.
- v0.1.0 (2026-11-07): Initial release.
"""

import os
import sqlite3
import stat
import tempfile
import unittest
import urllib.parse
from datetime import date, timedelta

from common import (
    START_ANYTIME,
    START_INBOX,
    START_SOMEDAY,
    STATUS_CANCELED,
    STATUS_COMPLETED,
    STATUS_OPEN,
    build_show_url,
    build_update_url,
    is_valid_task_id,
    load_order,
    load_token,
    missing_priority_tags,
    open_things_db,
    pack_things_date,
    read_list,
    read_task,
    save_order,
    save_token,
    unpack_things_date,
    validate_token,
)
from priority_check import Change

TODAY = date(2026, 11, 7)

SCHEMA = """
CREATE TABLE TMTask (
    uuid TEXT PRIMARY KEY, title TEXT, type INTEGER, status INTEGER, trashed INTEGER,
    start INTEGER, startDate INTEGER, deadline INTEGER, deadlineSuppressionDate INTEGER,
    todayIndex INTEGER, "index" INTEGER, project TEXT, heading TEXT, area TEXT,
    stopDate REAL, rt1_recurrenceRule BLOB
);
CREATE TABLE TMArea (uuid TEXT PRIMARY KEY, title TEXT);
CREATE TABLE TMTag (uuid TEXT PRIMARY KEY, title TEXT);
CREATE TABLE TMTaskTag (tasks TEXT, tags TEXT);
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

    def test_update_leaves_deadline(self) -> None:
        params = self._params(build_update_url(Change("A1", ["P2"]), "t"))
        self.assertNotIn("deadline", params)
        self.assertNotIn("when", params)

    def test_comma_in_tag_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_update_url(Change("A1", ["a,b", "P2"]), "t")

    def test_show_url(self) -> None:
        self.assertEqual(build_show_url("A1"), "things:///show?id=A1")

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

    def test_today_membership_and_order(self) -> None:
        self.assertEqual(self._ids("today"), ["today2", "today1", "overdue"])

    def test_other_lists(self) -> None:
        self.assertEqual(self._ids("inbox"), ["inbox"])
        self.assertEqual(self._ids("upcoming"), ["future"])
        self.assertEqual(self._ids("someday"), ["someday"])
        self.assertEqual(self._ids("logbook"), ["done"])
        self.assertEqual(set(self._ids("anytime")), {"today1", "today2", "overdue", "anytime"})

    def test_custom_searches(self) -> None:
        self.assertEqual(self._ids("p1"), ["today1"])
        self.assertEqual(self._ids("p2"), ["anytime"])
        self.assertEqual(self._ids("overdue"), ["overdue"])

    def test_todos_under_closed_or_trashed_parents_hidden(self) -> None:
        # Today, P1, Anytime and Logbook are checked against the expected lists
        # in the tests above; this names the hidden to-dos explicitly.
        hidden = {
            "in_trashproj", "in_doneproj", "in_cancelproj",
            "in_trashhead", "in_donehead", "in_headintrash", "done_in_trashproj",
        }
        for name in ("today", "anytime", "p1", "logbook"):
            with self.subTest(name=name):
                self.assertFalse(hidden & set(self._ids(name)))

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
        with open_things_db(self.path) as conn, self.assertRaises(ValueError):
            read_list(conn, "nope", TODAY)


if __name__ == "__main__":
    unittest.main()
