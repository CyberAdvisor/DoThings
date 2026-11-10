"""Tests for serve.py: missing-tag guards, opening Things lists, and client disconnects.

Uses a mock Things database (schema from test_common.py). Things itself and
the auth token are replaced with mocks, so nothing is sent to Things.

Version: 2.0.1

Change log:
- v2.0.1 (2026-11-10): Project view groups have no gray note.
- v2.0.0 (2026-11-10): Tests for Today's views, the tag filter and /api/drop
  (moves between priorities and projects, refusals, filtered reorders, the
  edit preview's place per view); move tests use /api/drop.
- v1.9.2 (2026-11-10): Synchronized module version metadata.
- v1.9.1 (2026-11-10): Synchronized module version metadata.
- v1.9.0 (2026-11-10): Tests for saved searches (listing, criteria, summary,
  pills, the builder's preview, saving, deleting and the edit preview's place
  in a search); searches.json kept in the temporary folder.
- v1.8.0 (2026-11-10): Calendar reads mocked in every test (never asking);
  tests for Today's events (off by default, order, hidden and canceled
  calendars, labels and states, access states), the calendars in Settings,
  the access request, opening an event, and logging a lasting problem once.
- v1.7.1 (2026-11-10): Synchronized module version metadata.
- v1.7.0 (2026-11-10): Sequential projects come from the tags listed in the
  saved settings (use_sequence_tags): tests for a tag's priority, two listed
  tags on one project (higher priority, project never changed), no tags
  listed, records kept while a tag is unlisted, a changed priority, missing
  sequential-project tags, and saving the list; project-change tests removed.
- v1.6.0 (2026-11-10): Tests for /api/settings, names on Today's groups,
  the default priority, auto-assign P1 off, priority pills and P5; settings
  kept in the temporary folder.
- v1.5.0 (2026-11-08): Tests for moving a task to the Trash (/api/trash).
- v1.4.0 (2026-11-08): Tests for reminder times in rows, the editor and the edit preview.
- v1.3.1 (2026-11-08): Synchronized module version metadata.
- v1.3.0 (2026-11-08): Synchronized module version metadata.
- v1.2.0 (2026-11-08): Tests for Reset other tasks (detail, preview, reset, due-
  only kept task, failures, guards); Next Up start now tagged P4 by rule 3.
- v1.1.0 (2026-11-08): Tests for Next Up projects (P4 start, Next Up group and
  search, tag removal, pause, missing P4) and moves to P4; P4 tag in fixtures.
- v1.0.3 (2026-11-07): Synchronized module version metadata.
- v1.0.2 (2026-11-07): Synchronized module version metadata.
- v1.0.1 (2026-11-07): Change log trimmed to v1.0.0 and later; earlier history is in git.
- v1.0.0 (2026-11-07): Midnight comes from start_of_day.
"""

import io
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from http.server import BaseHTTPRequestHandler
from unittest import mock

import serve
from calendar_check import Calendar, CalendarRead, Event
from priority_check import Settings, Task
from search_check import Search
from common import (
    Pull,
    START_ANYTIME,
    STATUS_COMPLETED,
    STATUS_OPEN,
    THINGS_LISTS,
    load_pulls,
    load_searches,
    load_settings,
    pack_things_date,
    save_pulls,
    save_searches,
    save_settings,
    start_of_day,
)
from test_common import SCHEMA, TODAY, write_db


class MockThingsTestCase(unittest.TestCase):
    """Base case: a mock database with one untagged Today task and only the P1 tag."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.folder.name, "main.sqlite")
        self.pulls_path = os.path.join(self.folder.name, "sequence_pulls.json")
        self.settings_path = os.path.join(self.folder.name, "settings.json")
        self.searches_path = os.path.join(self.folder.name, "searches.json")
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO TMTag VALUES ('t1', 'P1')")
        # Untagged and started today, so the refresh rules would tag it P2.
        conn.execute(
            "INSERT INTO TMTask (uuid, title, type, status, trashed, start, startDate, "
            "todayIndex, \"index\") VALUES ('task1', 'Task', 0, ?, 0, ?, ?, 0, 0)",
            (STATUS_OPEN, START_ANYTIME, pack_things_date(TODAY)),
        )
        conn.commit()
        conn.close()
        patches = [
            mock.patch.object(serve, "find_things_db_path", return_value=self.db_path),
            mock.patch.object(serve, "load_token", return_value="token"),
            mock.patch.object(serve, "today_local", return_value=TODAY),
            mock.patch.object(serve, "load_order", return_value={}),
            mock.patch.object(serve, "save_order"),
            mock.patch.object(serve.RefreshPause, "paused", False),
            # Keep the sequence record in the temporary folder, never the project's.
            mock.patch.object(serve, "load_pulls", lambda: load_pulls(self.pulls_path)),
            mock.patch.object(serve, "save_pulls", lambda pulls: save_pulls(pulls, self.pulls_path)),
            # Settings too: the defaults unless a test saves others.
            mock.patch.object(serve, "load_settings", lambda: load_settings(self.settings_path)),
            mock.patch.object(serve, "save_settings", lambda settings: save_settings(settings, self.settings_path)),
            # Searches too: the defaults unless a test saves others.
            mock.patch.object(serve, "load_searches", lambda: load_searches(self.searches_path)),
            mock.patch.object(serve, "save_searches", lambda searches: save_searches(searches, self.searches_path)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.apply_change = mock.patch.object(serve, "apply_change", return_value=True).start()
        # Calendar: never run osascript; macOS hasn't been asked unless a test says otherwise.
        self.read_calendar = mock.patch.object(serve, "read_calendar", return_value=CalendarRead("not_asked")).start()
        mock.patch.object(serve.CalendarLog, "last_problem", "").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def add_tags(self, *names: str) -> None:
        """Create more tags in the mock database."""
        with write_db(self.db_path) as conn:
            conn.executemany("INSERT INTO TMTag VALUES (?, ?)", [(n, n) for n in names])

    def use_searches(self, *searches: Search) -> None:
        """Save these searches in place of the defaults."""
        save_searches(searches, self.searches_path)

    def use_sequence_tags(self, *pairs: tuple) -> None:
        """Save settings that list these (project tag, priority) pairs as sequential-project tags."""
        save_settings(Settings(sequence_tags=tuple(pairs)), self.settings_path)


class MissingTagTests(MockThingsTestCase):
    """While a P tag is missing, nothing is written to Things."""

    def test_refresh_skipped_while_tags_missing(self) -> None:
        response = serve.list_response("today")
        self.assertEqual(response["missing_tags"], ["P2", "P3", "P4", "P5"])
        self.assertFalse(response["refresh_paused"])
        self.apply_change.assert_not_called()

    def test_refresh_runs_once_tags_exist(self) -> None:
        self.add_tags("P2", "P3", "P4", "P5")
        response = serve.list_response("today")
        self.assertEqual(response["missing_tags"], [])
        self.apply_change.assert_called_once()
        self.assertEqual(self.apply_change.call_args[0][0].tags, ["P2"])

    def test_move_to_missing_tag_refused_with_instructions(self) -> None:
        with self.assertRaises(serve.ApiError) as raised:
            serve.drop_task({"view": "priority", "key": "P3", "id": "task1", "order": ["task1"]})
        self.assertEqual(raised.exception.status, 409)
        self.assertIn("Create the P3 tag in Things first", raised.exception.message)
        self.apply_change.assert_not_called()

    def test_move_to_existing_tag_allowed(self) -> None:
        self.assertEqual(serve.drop_task({"view": "priority", "key": "P1", "id": "task1", "order": ["task1"]}), {"ok": True})
        self.apply_change.assert_called_once()


class RefreshPauseTests(MockThingsTestCase):
    """An unconfirmed refresh write pauses automatic updates until Retry."""

    def setUp(self) -> None:
        super().setUp()
        self.add_tags("P2", "P3", "P4", "P5")
        self.apply_change.return_value = False

    def test_failure_pauses_and_retry_resumes(self) -> None:
        self.assertTrue(serve.list_response("today")["refresh_paused"])
        self.assertEqual(self.apply_change.call_count, 1)
        self.assertTrue(serve.list_response("today")["refresh_paused"])
        self.assertEqual(self.apply_change.call_count, 1)  # Not tried again while paused.
        serve.retry_refresh({})
        self.apply_change.return_value = True
        self.assertFalse(serve.list_response("today")["refresh_paused"])
        self.assertEqual(self.apply_change.call_count, 2)

    def test_new_token_resumes(self) -> None:
        serve.list_response("today")
        with mock.patch.object(serve, "save_token"):
            serve.set_token({"token": "new"})
        self.assertFalse(serve.RefreshPause.paused)

    def test_manual_changes_still_tried_while_paused(self) -> None:
        serve.list_response("today")
        self.assertEqual(serve.complete_task({"id": "task1", "completed": True}), {"ok": False, "write_failed": True})
        self.assertEqual(self.apply_change.call_count, 2)


class OrderPruneTests(MockThingsTestCase):
    """The saved order forgets tasks no longer in Today."""

    def test_gone_ids_dropped(self) -> None:
        with mock.patch.object(serve, "load_order", return_value={"P2": ["gone", "task1"]}):
            serve.list_response("p1")
        serve.save_order.assert_called_once_with({"P1": [], "P2": ["task1"], "P3": [], "P4": [], "P5": []})

    def test_nothing_saved_when_all_present(self) -> None:
        with mock.patch.object(serve, "load_order", return_value={"P2": ["task1"]}):
            serve.list_response("today")
        serve.save_order.assert_not_called()


class StartDateRefreshTests(MockThingsTestCase):
    """A refresh gives tasks with no start date that are due today a start date of today."""

    def test_inbox_anytime_and_someday_tasks_due_today(self) -> None:
        self.add_tags("P2", "P3", "P4", "P5")
        due = pack_things_date(TODAY)
        with write_db(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, deadline, todayIndex, "
                "\"index\") VALUES (?, ?, 0, 0, 0, ?, ?, 1, 0)",
                [("inbox1", "In Inbox", 0, due), ("any1", "Anytime", 1, due), ("some1", "Someday", 2, due)],
            )
            conn.executemany("INSERT INTO TMTaskTag VALUES (?, 't1')", [("inbox1",), ("any1",), ("some1",)])
            conn.execute("INSERT INTO TMTaskTag VALUES ('task1', 'P2')")  # task1 already compliant.
        serve.list_response("today")
        sent = {call[0][0].task_id: call[0][0] for call in self.apply_change.call_args_list}
        self.assertEqual(set(sent), {"inbox1", "any1", "some1"})
        for change in sent.values():
            self.assertEqual(change.set_start_date, TODAY)
            self.assertIsNone(change.tags)


class CountsTests(MockThingsTestCase):
    """Every list response carries the sidebar counts."""

    def test_counts_on_today_and_on_a_search(self) -> None:
        with write_db(self.db_path) as conn:
            conn.execute(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, \"index\") "
                "VALUES ('in1', 'Inbox item', 0, 0, 0, 0, 0)"
            )
            conn.execute("UPDATE TMTask SET deadline = ? WHERE uuid = 'task1'", (pack_things_date(TODAY),))
        expected = {"inbox": 1, "today": {"due": 1, "not_due": 0}}
        self.assertEqual(serve.list_response("today")["counts"], expected)
        self.assertEqual(serve.list_response("overdue")["counts"], expected)


class ProjectTests(MockThingsTestCase):
    """Project order in Today, and sequential projects starting their next task."""

    def setUp(self) -> None:
        super().setUp()
        self.add_tags("P2", "P3", "P4", "P5", "Sequential")
        self.use_sequence_tags(("Sequential", "P2"))
        started = pack_things_date(TODAY)
        with write_db(self.db_path) as conn:
            conn.execute("DELETE FROM TMTask WHERE uuid = 'task1'")
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, \"index\") VALUES (?, ?, 1, 0, 0, 0)",
                [("seq", "Sequential project"), ("plain", "Plain project")],
            )
            conn.execute("INSERT INTO TMTaskTag VALUES ('seq', 'Sequential')")
            # Plain project tasks are in Today; todayIndex order is the reverse of project order.
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, startDate, project, "
                f"\"index\", todayIndex) VALUES (?, ?, 0, 0, 0, 1, {started}, 'plain', ?, ?)",
                [("p1", "p1", 1, 6), ("p2", "p2", 2, 5)],
            )
            conn.executemany("INSERT INTO TMTaskTag VALUES (?, 'P2')", [("p1",), ("p2",)])
            # Sequential project: three undated Anytime tasks.
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, project, \"index\") "
                "VALUES (?, ?, 0, 0, 0, 1, 'seq', ?)",
                [("s1", "s1", 1), ("s2", "s2", 2), ("s3", "s3", 3)],
            )

    def started(self) -> list:
        """Ids the refresh sent a start date of today for."""
        return [c[0][0].task_id for c in self.apply_change.call_args_list if c[0][0].set_start_date == TODAY]

    def test_plain_project_follows_project_order(self) -> None:
        groups = serve.list_response("today")["groups"]
        self.assertEqual([t["id"] for t in groups[1]["tasks"]][:2], ["p1", "p2"])

    def test_first_undated_task_is_started(self) -> None:
        serve.list_response("today")
        self.assertEqual(self.started(), ["s1"])

    def test_one_at_a_time_then_next(self) -> None:
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET startDate = ? WHERE uuid = 's1'", (pack_things_date(TODAY),))
        serve.list_response("today")
        self.assertEqual(self.started(), [])  # s1 is in progress.
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET status = 3, stopDate = 0 WHERE uuid = 's1'")
        serve.list_response("today")
        self.assertEqual(self.started(), ["s2"])

    def start(self, uuid: str, when=TODAY) -> None:
        """Give `uuid` a start date in the mock database, as Things would after a start."""
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET startDate = ? WHERE uuid = ?", (pack_things_date(when), uuid))

    def sent(self) -> list:
        """(task id, what) for each change the refresh sent, then forget them."""
        calls = [c[0][0] for c in self.apply_change.call_args_list]
        self.apply_change.reset_mock()
        return [(c.task_id, "start" if c.set_start_date else "undo" if c.set_when == "anytime" else "tags")
                for c in calls]

    def set_status(self, uuid: str, status: int, stop: float = 0) -> None:
        """Complete (3) or reopen (0) `uuid` in the mock database."""
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET status = ?, stopDate = ? WHERE uuid = ?",
                         (status, stop if status else None, uuid))

    def move_to_bottom(self, uuid: str) -> None:
        """Do what Things does to a reopened task: put it last in the project."""
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET \"index\" = 99 WHERE uuid = ?", (uuid,))

    def test_unchecking_returns_started_task_to_undated(self) -> None:
        serve.list_response("today")
        self.assertIn(("s1", "start"), self.sent())
        self.assertEqual(load_pulls(self.pulls_path), {"seq": Pull("s1", TODAY, None)})
        self.start("s1")
        self.set_status("s1", 3, stop=100)  # Checked off.
        serve.list_response("today")
        self.assertIn(("s2", "start"), self.sent())
        self.assertEqual(load_pulls(self.pulls_path), {"seq": Pull("s2", TODAY, "s1")})
        self.start("s2")
        self.set_status("s1", 0)  # Unchecked again; Things moves it to the bottom.
        self.move_to_bottom("s1")
        serve.list_response("today")
        sent = self.sent()
        self.assertIn(("s2", "undo"), sent)
        self.assertNotIn(("s3", "start"), sent)
        # s1 is now the task in progress, so the undone s2 isn't started again.
        self.assertEqual(load_pulls(self.pulls_path), {"seq": Pull("s1", TODAY, None)})
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET startDate = NULL WHERE uuid = 's2'")  # As Things applied the undo.
        serve.list_response("today")
        self.assertNotIn(("s2", "start"), self.sent())
        # Completing s1 again starts the first undated task in project order: s2.
        self.set_status("s1", 3, stop=200)
        serve.list_response("today")
        self.assertIn(("s2", "start"), self.sent())
        self.assertEqual(load_pulls(self.pulls_path), {"seq": Pull("s2", TODAY, "s1")})

    def test_started_task_shows_its_place(self) -> None:
        serve.list_response("today")
        self.start("s1")
        rows = {t["id"]: t for g in serve.list_response("today")["groups"] for t in g["tasks"]}
        self.assertEqual((rows["s1"]["sequence"], rows["p1"]["sequence"]), ("task 1 of 3", None))
        self.set_status("s1", 3, stop=100)
        serve.list_response("today")
        self.start("s2")
        rows = {t["id"]: t for g in serve.list_response("today")["groups"] for t in g["tasks"]}
        self.assertEqual(rows["s2"]["sequence"], "task 2 of 3")
        preview = serve.preview_edit({"id": "s2", "list": "today", "changes": {"title": "Renamed"}})
        self.assertEqual(preview["row"]["sequence"], "task 2 of 3")
        tomorrow = (TODAY + timedelta(days=1)).isoformat()
        preview = serve.preview_edit({"id": "s2", "list": "today", "changes": {"when": tomorrow}})
        self.assertIsNone(preview["row"]["sequence"])

    def test_place_is_position_in_project_order(self) -> None:
        save_pulls({"seq": Pull("s2", TODAY, None)}, self.pulls_path)  # s2 started, s1 still undated.
        self.start("s2")
        rows = {t["id"]: t for g in serve.list_response("today")["groups"] for t in g["tasks"]}
        self.assertEqual(rows["s2"]["sequence"], "task 2 of 3")

    def test_old_record_without_trigger_is_never_undone(self) -> None:
        save_pulls({"seq": Pull("s2", TODAY)}, self.pulls_path)  # As written by v0.1.17.
        self.start("s1")
        self.start("s2")
        serve.list_response("today")
        self.assertNotIn(("s2", "undo"), self.sent())

    def test_task_redated_by_user_is_left_alone(self) -> None:
        save_pulls({"seq": Pull("s2", TODAY, "s1")}, self.pulls_path)
        self.start("s1")
        self.start("s2", TODAY + timedelta(days=2))  # The user moved it.
        serve.list_response("today")
        self.assertNotIn(("s2", "undo"), self.sent())
        self.assertEqual(load_pulls(self.pulls_path), {})

    def test_dated_tasks_left_alone(self) -> None:
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET deadline = ? WHERE uuid = 's1'", (pack_things_date(TODAY),))
        serve.list_response("today")
        # s1 has a deadline, so it follows its own dates (rule 4 starts it as due today);
        # s2 is the next undated task.
        self.assertEqual(self.started(), ["s2", "s1"])


class SequenceTagTests(MockThingsTestCase):
    """Sequential projects are the ones with a tag listed in Settings, each with its own priority."""

    def setUp(self) -> None:
        super().setUp()
        self.add_tags("P2", "P3", "P4", "P5", "Sequential", "Next Up")
        self.use_sequence_tags(("Sequential", "P2"), ("Next Up", "P4"))
        with write_db(self.db_path) as conn:
            conn.execute("DELETE FROM TMTask WHERE uuid = 'task1'")
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, \"index\") VALUES (?, ?, 1, 0, 0, 0)",
                [("books", "Books"), ("both", "Both")],
            )
            conn.executemany(
                "INSERT INTO TMTaskTag VALUES (?, ?)",
                [("books", "Next Up"), ("both", "Sequential"), ("both", "Next Up")],
            )
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, project, \"index\") "
                f"VALUES (?, ?, 0, 0, 0, {START_ANYTIME}, ?, ?)",
                [("b1", "Book 1", "books", 1), ("b2", "Book 2", "books", 2), ("x1", "Both 1", "both", 1)],
            )

    def starts(self) -> dict:
        """{task id: tags sent} for each task the refresh gave a start date of today."""
        return {c[0][0].task_id: c[0][0].tags for c in self.apply_change.call_args_list
                if c[0][0].set_start_date == TODAY}

    def tagged(self) -> dict:
        """{task id: tags sent} for each change the refresh sent."""
        return {c[0][0].task_id: c[0][0].tags for c in self.apply_change.call_args_list}

    def start(self, *uuids: str) -> None:
        """Give the tasks a start date of today, as Things would after a start."""
        with write_db(self.db_path) as conn:
            conn.executemany("UPDATE TMTask SET startDate = ? WHERE uuid = ?",
                             [(pack_things_date(TODAY), u) for u in uuids])

    def test_tag_priority_given_and_shown_in_its_group(self) -> None:
        serve.list_response("today")
        self.assertEqual(self.starts(), {"b1": None, "x1": None})
        self.start("b1")
        self.apply_change.reset_mock()
        serve.list_response("today")
        self.assertEqual(self.starts(), {"x1": None})  # b1 is in progress; nothing else from Books.
        self.assertEqual(self.tagged()["b1"], ["P4"])  # Refresh rule 3: Next Up is set to P4.
        with write_db(self.db_path) as conn:
            conn.execute("INSERT INTO TMTaskTag VALUES ('b1', 'P4')")
        response = serve.list_response("today")
        self.assertEqual(response["priorities"], ["P1", "P2", "P3", "P4", "P5"])
        group = response["groups"][3]
        self.assertEqual((group["key"], group["label"], group["note"]), ("P4", "Next Up", "P4"))
        self.assertEqual([(t["id"], t["sequence"], t["tags"]) for t in group["tasks"]], [("b1", "task 1 of 2", [])])
        self.assertEqual([t["id"] for t in serve.list_response("p4")["tasks"]], ["b1"])

    def test_two_listed_tags_higher_priority_wins_and_project_unchanged(self) -> None:
        self.start("x1")
        serve.list_response("today")
        self.assertEqual(self.tagged()["x1"], ["P2"])  # Sequential (P2) beats Next Up (P4).
        # Only task changes are ever sent; the project keeps both tags.
        self.assertTrue(all(c[0][0].task_id in ("b1", "x1") for c in self.apply_change.call_args_list))

    def test_custom_tag_and_priority(self) -> None:
        self.add_tags("Reading List")
        self.use_sequence_tags(("Reading List", "P5"))
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTaskTag SET tags = 'Reading List' WHERE tasks = 'books'")
        serve.list_response("today")
        self.assertEqual(self.starts(), {"b1": None})  # "both" has no listed tag now.
        self.start("b1")
        self.apply_change.reset_mock()
        serve.list_response("today")
        self.assertEqual(self.tagged(), {"b1": ["P5"]})

    def test_no_tags_listed_nothing_started_and_records_kept(self) -> None:
        save_pulls({"books": Pull("b1", TODAY, None)}, self.pulls_path)
        self.start("b1")
        self.use_sequence_tags()
        response = serve.list_response("today")
        self.assertEqual(self.starts(), {})
        self.assertEqual(self.tagged(), {"b1": ["P2"]})  # An ordinary Today task now: the default priority.
        self.assertEqual(response["missing_sequence_tags"], [])
        self.assertIsNone(response["groups"][1]["tasks"][0]["sequence"])
        # The record is kept, not acted on, and used again once the tag is listed again.
        self.assertEqual(load_pulls(self.pulls_path), {"books": Pull("b1", TODAY, None)})
        self.use_sequence_tags(("Next Up", "P4"))
        rows = {t["id"]: t for g in serve.list_response("today")["groups"] for t in g["tasks"]}
        self.assertEqual(rows["b1"]["sequence"], "task 1 of 2")

    def test_unlisted_tag_no_longer_undone(self) -> None:
        # b2 was started after b1 was completed; b1 is then reopened while Next Up isn't listed.
        save_pulls({"books": Pull("b2", TODAY, "b1")}, self.pulls_path)
        self.start("b2")
        self.use_sequence_tags(("Sequential", "P2"))
        serve.list_response("today")
        self.assertNotIn("b2", [c[0][0].task_id for c in self.apply_change.call_args_list
                                if c[0][0].set_when == "anytime"])

    def test_changed_priority_keeps_started_task_tag(self) -> None:
        self.start("b1")
        with write_db(self.db_path) as conn:
            conn.execute("INSERT INTO TMTaskTag VALUES ('b1', 'P4')")
        self.use_sequence_tags(("Sequential", "P2"), ("Next Up", "P3"))
        serve.list_response("today")
        self.assertNotIn("b1", self.tagged())  # Already P4: kept.
        self.start("b2")  # A newly dated, untagged task gets the new priority.
        serve.list_response("today")
        self.assertEqual(self.tagged()["b2"], ["P3"])

    def test_missing_sequence_tag_reported_and_others_still_run(self) -> None:
        self.use_sequence_tags(("Next Up", "P4"), ("Reading List", "P5"))
        response = serve.list_response("today")
        self.assertEqual(response["missing_sequence_tags"], ["Reading List"])
        self.assertFalse(response["refresh_paused"])
        self.assertEqual(self.starts(), {"b1": None, "x1": None})  # Both projects carry Next Up.
        self.assertEqual(serve.settings_response()["missing_sequence_tags"], ["Reading List"])

    def test_refresh_waits_for_p4_tag(self) -> None:
        with write_db(self.db_path) as conn:
            conn.execute("DELETE FROM TMTag WHERE title = 'P4'")
        response = serve.list_response("today")
        self.assertEqual(response["missing_tags"], ["P4"])
        self.apply_change.assert_not_called()

    def test_move_to_p4(self) -> None:
        self.start("b2")
        with write_db(self.db_path) as conn:
            conn.execute("INSERT INTO TMTaskTag VALUES ('b2', 'P2')")  # Shown in P2, so the drop is a move.
        self.assertEqual(serve.drop_task({"view": "priority", "key": "P4", "id": "b2", "order": ["b2"]}), {"ok": True})
        self.assertEqual(self.apply_change.call_args[0][0].tags, ["P4"])


class SequenceResetTests(MockThingsTestCase):
    """Reset other tasks: the chosen task stays the only one of its project in Today."""

    def setUp(self) -> None:
        super().setUp()
        self.add_tags("P2", "P3", "P4", "P5", "Next Up", "Home")
        self.use_sequence_tags(("Next Up", "P4"))
        today = pack_things_date(TODAY)
        with write_db(self.db_path) as conn:
            conn.execute("INSERT INTO TMTask (uuid, title, type, status, trashed, \"index\") "
                         "VALUES ('books', 'Books', 1, 0, 0, 0)")
            conn.execute("INSERT INTO TMTaskTag VALUES ('books', 'Next Up')")
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, startDate, deadline, project, "
                f"\"index\") VALUES (?, ?, 0, 0, 0, {START_ANYTIME}, ?, ?, 'books', ?)",
                [("b1", "Book 1", today, None, 1), ("b2", "Book 2", today, None, 2),
                 ("b3", "Book 3", today, today, 3), ("b4", "Book 4", None, None, 4)],
            )
            conn.executemany("INSERT INTO TMTaskTag VALUES (?, ?)", [("b1", "P4"), ("b1", "Home"), ("b2", "P4")])
        save_pulls({"books": Pull("b1", TODAY, None)}, self.pulls_path)

    def test_detail_offers_reset_only_in_sequential_projects(self) -> None:
        self.assertEqual(serve.task_detail("b2")["task"]["sequence_project"], "Books")
        self.assertIsNone(serve.task_detail("task1")["task"]["sequence_project"])

    def test_preview_writes_nothing(self) -> None:
        preview = serve.preview_reset({"id": "b2"})
        # b3 has a deadline and b4 isn't in Today, so only b1 goes back.
        self.assertEqual(preview, {"project": "Books", "returned": [{"id": "b1", "title": "Book 1"}]})
        self.apply_change.assert_not_called()

    def test_reset_keeps_chosen_task_and_records_it(self) -> None:
        self.assertEqual(serve.reset_sequence({"id": "b2"}), {"ok": True, "returned": 1})
        change = self.apply_change.call_args[0][0]
        self.assertEqual((change.task_id, change.set_when, change.tags), ("b1", "anytime", ["Home"]))
        self.assertEqual(load_pulls(self.pulls_path), {"books": Pull("b2", TODAY, None)})

    def test_kept_task_due_only_is_started_first(self) -> None:
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET startDate = NULL WHERE uuid = 'b3'")
        serve.reset_sequence({"id": "b3"})
        sent = [(c[0][0].task_id, c[0][0].set_start_date, c[0][0].set_when) for c in self.apply_change.call_args_list]
        self.assertEqual(sent, [("b3", TODAY, None), ("b1", None, "anytime"), ("b2", None, "anytime")])
        self.assertEqual(load_pulls(self.pulls_path), {"books": Pull("b3", TODAY, None)})

    def test_unconfirmed_change_reported(self) -> None:
        self.apply_change.return_value = False
        self.assertEqual(serve.reset_sequence({"id": "b2"}), {"ok": False, "write_failed": True})

    def test_refused_requests(self) -> None:
        for body, message in (({"id": "task1"}, "isn't in a sequential project"),
                              ({"id": "nosuch"}, "Task not found")):
            with self.subTest(body=body), self.assertRaises(serve.ApiError) as raised:
                serve.reset_sequence(body)
            self.assertIn(message, raised.exception.message)
        with write_db(self.db_path) as conn:
            conn.execute("DELETE FROM TMTag WHERE title = 'P3'")
        with self.assertRaises(serve.ApiError) as raised:
            serve.reset_sequence({"id": "b2"})
        self.assertIn("Create the P3 tag", raised.exception.message)
        with mock.patch.object(serve, "load_token", return_value=None), self.assertRaises(serve.ApiError):
            serve.reset_sequence({"id": "b2"})
        self.apply_change.assert_not_called()


class CompletionTests(MockThingsTestCase):
    """Completing and reopening tasks, and how completed tasks are listed."""

    def add_completed_task(self, uuid: str) -> None:
        """Add a P1-tagged Today task completed one minute after midnight."""
        midnight = start_of_day(TODAY)
        with write_db(self.db_path) as conn:
            conn.execute(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, startDate, stopDate, "
                "todayIndex, \"index\") VALUES (?, ?, 0, ?, 0, ?, ?, ?, -1, 0)",
                (uuid, uuid, STATUS_COMPLETED, START_ANYTIME, pack_things_date(TODAY), midnight + 60),
            )
            conn.execute("INSERT INTO TMTaskTag VALUES (?, 't1')", (uuid,))

    def test_complete_works_while_tags_missing(self) -> None:
        self.assertEqual(serve.complete_task({"id": "task1", "completed": True}), {"ok": True})
        change = self.apply_change.call_args[0][0]
        self.assertTrue(change.set_completed)
        self.assertIsNone(change.tags)

    def test_reopen(self) -> None:
        self.add_completed_task("done1")
        serve.complete_task({"id": "done1", "completed": False})
        self.assertFalse(self.apply_change.call_args[0][0].set_completed)

    def test_no_write_when_already_in_state(self) -> None:
        self.assertEqual(serve.complete_task({"id": "task1", "completed": False}), {"ok": True})
        self.apply_change.assert_not_called()

    def test_unconfirmed_completion_reported(self) -> None:
        self.apply_change.return_value = False
        self.assertEqual(
            serve.complete_task({"id": "task1", "completed": True}), {"ok": False, "write_failed": True}
        )

    def test_bad_requests_rejected(self) -> None:
        for body in ({"id": "task1", "completed": "yes"}, {"id": "bad id!", "completed": True},
                     {"id": "nosuch", "completed": True}):
            with self.subTest(body=body), self.assertRaises(serve.ApiError):
                serve.complete_task(body)
        self.apply_change.assert_not_called()

    def test_hide_completed(self) -> None:
        self.add_completed_task("done1")
        with write_db(self.db_path) as conn:
            conn.execute("INSERT INTO TMTaskTag VALUES ('task1', 't1')")
        for name in ("today", "p1"):
            with self.subTest(name=name):
                shown = serve.list_response(name)
                hidden = serve.list_response(name, hide_completed=True)
                ids = lambda r: [t["id"] for t in (r["groups"][0]["tasks"] if "groups" in r else r["tasks"])]
                self.assertEqual(ids(shown), ["task1", "done1"])
                self.assertEqual(ids(hidden), ["task1"])
                self.assertEqual(hidden["counts"], shown["counts"])

    def test_priority_pill_unless_search_has_one_priority(self) -> None:
        self.add_tags("Home")
        with write_db(self.db_path) as conn:
            conn.executemany("INSERT INTO TMTaskTag VALUES ('task1', ?)", [("t1",), ("Home",)])
            conn.execute("UPDATE TMTask SET deadline = ? WHERE uuid = 'task1'",
                         (pack_things_date(TODAY - timedelta(days=1)),))
        pill = lambda row: (row["tags"], row["priority"])
        self.assertEqual(pill(serve.list_response("today")["groups"][0]["tasks"][0]), (["Home"], None))
        self.assertEqual(pill(serve.list_response("p1")["tasks"][0]), (["Home"], None))
        overdue = serve.list_response("overdue")
        self.assertEqual(pill(overdue["tasks"][0]), (["Home"], "P1"))
        self.assertEqual(overdue["priority_names"]["P1"], "Due Today")  # The page names the pill.

    def test_completed_task_cannot_be_moved(self) -> None:
        self.add_completed_task("done1")
        with self.assertRaises(serve.ApiError) as raised:
            serve.drop_task({"view": "priority", "key": "P1", "id": "done1", "order": ["done1"]})
        self.assertIn("Uncheck", raised.exception.message)

    def test_completed_tasks_listed_last_and_flagged(self) -> None:
        # done1 sorts first in Things (todayIndex -1) but must come after open tasks.
        self.add_completed_task("done1")
        with write_db(self.db_path) as conn:
            conn.execute("INSERT INTO TMTaskTag VALUES ('task1', 't1')")
        p1 = serve.list_response("p1")["tasks"]
        self.assertEqual([(t["id"], t["completed"]) for t in p1], [("task1", False), ("done1", True)])
        group = serve.list_response("today")["groups"][0]
        self.assertEqual([t["id"] for t in group["tasks"]], ["task1", "done1"])


class TrashTests(MockThingsTestCase):
    """Moving a task to Things' Trash from the editor."""

    def setUp(self) -> None:
        super().setUp()
        self.move_to_trash = mock.patch.object(serve, "move_to_trash", return_value=True).start()

    def test_open_task_trashed_without_token(self) -> None:
        with mock.patch.object(serve, "load_token", return_value=None):
            self.assertEqual(serve.trash_task({"id": "task1"}), {"ok": True})
        self.move_to_trash.assert_called_once_with("task1", self.db_path)
        self.apply_change.assert_not_called()  # No URL write and no tag change with it.

    def test_unconfirmed_trash_reported(self) -> None:
        self.move_to_trash.return_value = False
        self.assertEqual(serve.trash_task({"id": "task1"}), {"ok": False, "write_failed": True})

    def test_refused_requests(self) -> None:
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET status = ?, stopDate = ? WHERE uuid = 'task1'",
                         (STATUS_COMPLETED, start_of_day(TODAY) + 60))
        for body, status in (({"id": "task1"}, 409), ({"id": "nosuch"}, 404), ({"id": "bad id"}, 400), ({}, 400)):
            with self.subTest(body=body):
                with self.assertRaises(serve.ApiError) as raised:
                    serve.trash_task(body)
                self.assertEqual(raised.exception.status, status)
        self.move_to_trash.assert_not_called()

    def test_routed(self) -> None:
        self.assertIs(serve.POST_ROUTES["/api/trash"], serve.trash_task)


class SettingsApiTests(MockThingsTestCase):
    """GET and POST /api/settings, and the rules and labels following the saved settings."""

    def save(self, **changes: object) -> dict:
        """Save the default settings with `changes` applied, as the Settings page sends them."""
        settings = dict(serve.settings_response()["settings"], **changes)
        return serve.update_settings({"settings": settings})

    def test_defaults_and_missing_tags(self) -> None:
        response = serve.settings_response()
        self.assertEqual(response["settings"]["names"]["P2"], "To Do")
        self.assertEqual((response["settings"]["auto_p1"], response["settings"]["default_priority"]), (True, "P2"))
        self.assertEqual(response["missing_tags"], ["P2", "P3", "P4", "P5"])
        self.assertEqual((response["settings"]["sequence_tags"], response["missing_sequence_tags"]), ([], []))

    def test_sequence_tags_saved_and_checked_against_things(self) -> None:
        self.add_tags("Sequential")
        tags = [{"tag": "Sequential", "priority": "P2"}, {"tag": "Reading List", "priority": "P5"}]
        response = self.save(sequence_tags=tags)
        self.assertEqual(response["settings"]["sequence_tags"], tags)
        self.assertEqual(response["missing_sequence_tags"], ["Reading List"])
        self.assertEqual(load_settings(self.settings_path).sequence_tags, (("Sequential", "P2"), ("Reading List", "P5")))

    def test_invalid_sequence_tags_refused(self) -> None:
        for tags in ([{"tag": "", "priority": "P2"}], [{"tag": "A", "priority": "P2"}, {"tag": "A", "priority": "P3"}],
                     [{"tag": "P3", "priority": "P2"}], [{"tag": "A", "priority": "P0"}]):
            with self.subTest(tags=tags):
                with self.assertRaises(serve.ApiError) as raised:
                    self.save(sequence_tags=tags)
                self.assertEqual(raised.exception.status, 400)
        self.assertFalse(os.path.exists(self.settings_path))

    def test_saved_names_label_today(self) -> None:
        names = dict(serve.settings_response()["settings"]["names"], P2="Doing", P5="Later")
        self.assertEqual(self.save(names=names)["settings"]["names"]["P2"], "Doing")
        groups = serve.list_response("today")["groups"]
        self.assertEqual([g["label"] for g in groups], ["Due Today", "Doing", "Follow Up", "Next Up", "Later"])

    def test_invalid_settings_refused_and_not_saved(self) -> None:
        with self.assertRaises(serve.ApiError) as raised:
            self.save(default_priority="P9")
        self.assertEqual(raised.exception.status, 400)
        self.assertFalse(os.path.exists(self.settings_path))

    def test_default_priority_for_new_today_tasks(self) -> None:
        self.add_tags("P2", "P3", "P4", "P5")
        self.save(default_priority="P3")
        serve.list_response("today")
        self.assertEqual(self.apply_change.call_args[0][0].tags, ["P3"])  # Untagged task1 gets P3.

    def test_auto_p1_off(self) -> None:
        self.add_tags("P2", "P3", "P4", "P5")
        self.save(auto_p1=False)
        with write_db(self.db_path) as conn:
            conn.execute("INSERT INTO TMTaskTag VALUES ('task1', 'P3')")
            conn.execute("UPDATE TMTask SET deadline = ? WHERE uuid = 'task1'", (pack_things_date(TODAY),))
        response = serve.list_response("today")
        self.apply_change.assert_not_called()  # Due today, but it keeps P3.
        self.assertEqual([t["id"] for t in response["groups"][2]["tasks"]], ["task1"])
        serve.drop_task({"view": "priority", "key": "P1", "id": "task1", "order": ["task1"]})
        sent = self.apply_change.call_args[0][0]
        self.assertEqual((sent.tags, sent.set_deadline, sent.clear_deadline), (["P1"], None, False))


class CalendarTests(MockThingsTestCase):
    """Today's calendar events (read only), Settings › Calendar events and opening an event."""

    def setUp(self) -> None:
        super().setUp()
        self.zone = os.environ.get("TZ")
        os.environ["TZ"] = "America/Denver"
        time.tzset()
        self.addCleanup(self.restore_zone)
        at = lambda hour, minute=0: datetime(TODAY.year, TODAY.month, TODAY.day, hour, minute).timestamp()
        self.events = [
            Event("E-lunch", "Lunch", False, at(12), at(13), "c1", "Home", "#0088ff"),
            Event("E-holiday", "Holiday", True, at(0), at(0) + 86400, "c2", "US Holidays", "#cb30e0"),
            Event("E-gone", "Canceled", False, at(9), at(10), "c1", "Home", "#0088ff", status=3),
            Event("E-gym", "Gym", False, at(8), at(8, 30), "c1", "Home", "#0088ff"),
        ]
        self.read_calendar.return_value = CalendarRead("allowed", [], self.events)
        mock.patch.object(serve.time, "time", return_value=at(12, 15)).start()

    def restore_zone(self) -> None:
        """Put the test runner's time zone back."""
        if self.zone is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = self.zone
        time.tzset()

    def turn_on(self, hidden: tuple = ()) -> None:
        """Save settings with calendar events on and `hidden` calendars unchecked."""
        save_settings(Settings(calendar_events=True, hidden_calendars=hidden), self.settings_path)

    def test_off_by_default_and_calendar_not_read(self) -> None:
        self.assertIsNone(serve.list_response("today")["calendar"])
        self.read_calendar.assert_not_called()

    def test_events_in_todays_order_with_labels_and_states(self) -> None:
        self.turn_on()
        calendar = serve.list_response("today")["calendar"]
        self.assertEqual(calendar["access"], "allowed")
        rows = [(e["title"], e["label"], e["state"], e["calendar"]) for e in calendar["events"]]
        self.assertEqual(rows, [("Holiday", "All day", None, "US Holidays"),
                                ("Gym", "8:00 – 8:30 AM", "past", "Home"),
                                ("Lunch", "12:00 – 1:00 PM", "now", "Home")])  # Canceled left out.
        self.assertEqual(calendar["events"][0]["color"], "#cb30e0")
        self.read_calendar.assert_called_once_with(False)  # A refresh never asks for access.

    def test_unchecked_calendar_hidden(self) -> None:
        self.turn_on(hidden=("c2",))
        titles = [e["title"] for e in serve.list_response("today")["calendar"]["events"]]
        self.assertEqual(titles, ["Gym", "Lunch"])

    def test_no_access_and_searches(self) -> None:
        self.turn_on()
        self.read_calendar.return_value = CalendarRead("denied")
        self.assertEqual(serve.list_response("today")["calendar"], {"access": "denied", "events": []})
        self.assertNotIn("calendar", serve.list_response("p2"))  # Today only.

    def test_lasting_problem_logged_once(self) -> None:
        self.turn_on()
        self.read_calendar.return_value = CalendarRead("unavailable", problem="osascript failed: boom")
        with mock.patch.object(serve, "get_logger") as logger:
            serve.list_response("today")
            serve.list_response("today")
            self.assertEqual(logger.return_value.error.call_count, 1)
            self.read_calendar.return_value = CalendarRead("allowed", [], [])
            serve.list_response("today")  # Works again: the next problem is logged again.
            self.read_calendar.return_value = CalendarRead("unavailable", problem="osascript failed: boom")
            serve.list_response("today")
            self.assertEqual(logger.return_value.error.call_count, 2)

    def test_settings_lists_calendars_without_asking(self) -> None:
        self.read_calendar.return_value = CalendarRead("allowed", [Calendar("c1", "Home", "iCloud", "#0088ff")])
        response = serve.settings_response()
        self.assertEqual(response["calendar"], {"access": "allowed", "calendars": [
            {"id": "c1", "title": "Home", "source": "iCloud", "color": "#0088ff"}]})
        self.read_calendar.assert_called_once_with(False)
        self.assertEqual((response["settings"]["calendar_events"], response["settings"]["hidden_calendars"]), (False, []))

    def test_access_request_and_saving(self) -> None:
        self.read_calendar.return_value = CalendarRead("allowed")
        self.assertEqual(serve.request_calendar_access({})["access"], "allowed")
        self.read_calendar.assert_called_once_with(True)
        self.assertIs(serve.POST_ROUTES["/api/calendar/access"], serve.request_calendar_access)
        settings = dict(serve.settings_response()["settings"], calendar_events=True, hidden_calendars=["c2"])
        saved = serve.update_settings({"settings": settings})["settings"]
        self.assertEqual((saved["calendar_events"], saved["hidden_calendars"]), (True, ["c2"]))

    def test_open_event_in_calendar(self) -> None:
        with mock.patch.object(serve, "open_url", return_value=True) as opened:
            self.assertEqual(serve.open_event({"id": "E-lunch"}), {"ok": True})
            opened.assert_called_once_with("ical://ekevent/E-lunch?method=show&options=more", background=False)
            for body, status in (({"id": "E-other"}, 404), ({"id": "bad id"}, 400), ({}, 400)):
                with self.subTest(body=body):
                    with self.assertRaises(serve.ApiError) as raised:
                        serve.open_event(body)
                    self.assertEqual(raised.exception.status, status)
            self.assertEqual(opened.call_count, 1)
        self.assertIs(serve.POST_ROUTES["/api/calendar/open"], serve.open_event)


class EditTests(MockThingsTestCase):
    """Loading a task for the inline editor and saving edits."""

    def setUp(self) -> None:
        super().setUp()
        self.add_tags("P2", "P3", "P4", "P5", "Home")
        with write_db(self.db_path) as conn:
            conn.execute("INSERT INTO TMArea (uuid, title) VALUES ('area1', 'Work')")
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, project, \"index\") "
                "VALUES (?, ?, ?, 0, 0, ?, 0)",
                [("proj1", "Project", 1, None), ("head1", "Heading", 2, "proj1")],
            )
            conn.execute("INSERT INTO TMTaskTag VALUES ('task1', 'P2')")
        self.save_order = serve.save_order

    def edit(self, **changes: object) -> dict:
        """Save `changes` to task1."""
        return serve.edit_task({"id": "task1", "changes": changes})

    def sent(self):
        """The Change passed to apply_change."""
        return self.apply_change.call_args[0][0]

    def test_detail(self) -> None:
        detail = serve.task_detail("task1")
        task = detail["task"]
        self.assertEqual((task["priority"], task["when"]), ("P2", {"kind": "today", "date": TODAY.isoformat(), "reminder": None}))
        self.assertEqual((task["tags"], task["other_tags"]), ([], []))
        self.assertEqual(detail["today"], TODAY.isoformat())
        self.assertEqual(detail["options"]["tags"], ["Home"])
        self.assertEqual([p["id"] for p in detail["options"]["projects"]], ["proj1"])
        with self.assertRaises(serve.ApiError):
            serve.task_detail("nosuch")

    def test_detail_checklist(self) -> None:
        self.assertEqual(serve.task_detail("task1")["task"]["checklist"], {"done": 0, "total": 0})
        with write_db(self.db_path) as conn:
            conn.executemany("INSERT INTO TMChecklistItem VALUES (?, 'x', ?, 'task1', 0)", [("c1", 0), ("c2", 3)])
        self.assertEqual(serve.task_detail("task1")["task"]["checklist"], {"done": 1, "total": 2})

    def test_saves_fields_as_one_change(self) -> None:
        self.assertEqual(
            self.edit(title=" New title ", notes="N", tags=["Home"], when="someday", deadline="2026-11-20",
                      list_id="proj1", heading_id="head1"),
            {"ok": True},
        )
        self.apply_change.assert_called_once()
        change = self.sent()
        self.assertEqual((change.set_title, change.set_notes, change.set_when), ("New title", "N", "someday"))
        self.assertEqual(change.tags, ["Home", "P2"])
        self.assertEqual(change.set_deadline.isoformat(), "2026-11-20")
        self.assertEqual((change.set_list_id, change.set_heading_id), ("proj1", "head1"))

    def test_when_today_and_clear_deadline(self) -> None:
        self.edit(when="today", deadline="")
        self.assertEqual(self.sent().set_start_date, TODAY)
        self.assertTrue(self.sent().clear_deadline)

    def test_priority_change_moves_task_to_end_of_group(self) -> None:
        with mock.patch.object(serve, "load_order", return_value={"P1": ["x"], "P2": ["task1"]}):
            self.edit(priority="P1")
        self.assertEqual(self.sent().set_deadline, TODAY)
        self.save_order.assert_called_once_with({"P1": ["x", "task1"], "P2": [], "P3": [], "P4": [], "P5": []})

    def test_invalid_changes_rejected(self) -> None:
        for changes in ({"title": ""}, {"title": "two\nlines"}, {"when": "evening"}, {"deadline": "soon"},
                        {"priority": "P6"}, {"tags": ["Nope"]}, {"list_id": "nosuch"},
                        {"heading_id": "head1"},  # task1 isn't in proj1
                        {"color": "red"}):
            with self.subTest(changes=changes), self.assertRaises(serve.ApiError):
                self.edit(**changes)
        self.apply_change.assert_not_called()

    def test_nothing_changed_sends_nothing(self) -> None:
        self.assertEqual(self.edit(priority="P2"), {"ok": True})
        self.apply_change.assert_not_called()

    def test_missing_priority_tag_refused(self) -> None:
        with write_db(self.db_path) as conn:
            conn.execute("DELETE FROM TMTag WHERE title = 'P3'")
        with self.assertRaises(serve.ApiError) as raised:
            self.edit(priority="P3")
        self.assertIn("Create the P3 tag", raised.exception.message)
        self.edit(title="Fine without tags")  # No tags sent, so allowed.
        self.apply_change.assert_called_once()

    def preview(self, list_name: str = "today", **changes: object) -> dict:
        """Preview `changes` to task1 as seen from `list_name`."""
        return serve.preview_edit({"id": "task1", "list": list_name, "changes": changes})

    def test_preview_unchanged_matches_list_row(self) -> None:
        preview = self.preview()
        self.assertEqual(preview["place"], "P2")
        self.assertEqual(preview["row"], serve.list_response("today")["groups"][1]["tasks"][0])
        self.assertEqual((preview["priority"], preview["deadline"]), ("P2", None))

    def test_preview_defer_moves_deadline_and_leaves_today(self) -> None:
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET deadline = ? WHERE uuid = 'task1'", (pack_things_date(TODAY),))
        tomorrow = (TODAY + timedelta(days=1)).isoformat()
        preview = self.preview(when=tomorrow)
        self.assertEqual(preview["deadline"], tomorrow)
        self.assertEqual(preview["when"], {"kind": "date", "date": tomorrow, "reminder": None})
        self.assertIsNone(preview["place"])
        self.assertIsNotNone(preview["row"]["start_label"])

    def test_preview_deadline_today_becomes_p1(self) -> None:
        preview = self.preview(deadline=TODAY.isoformat())
        self.assertEqual((preview["priority"], preview["place"]), ("P1", "P1"))
        self.assertIsNone(self.preview("p2", deadline=TODAY.isoformat())["place"])
        self.assertEqual(self.preview("p2")["place"], "list")

    def test_preview_someday_clears_deadline_and_list_change_sets_context(self) -> None:
        preview = self.preview(when="someday", list_id="proj1")
        self.assertEqual((preview["when"]["kind"], preview["deadline"]), ("someday", None))
        self.assertIsNone(preview["place"])
        self.assertEqual(preview["row"]["context"], "Project")

    def test_preview_writes_nothing_and_needs_no_token(self) -> None:
        with mock.patch.object(serve, "load_token", return_value=None):
            self.preview(priority="P1")
        self.apply_change.assert_not_called()
        with self.assertRaises(serve.ApiError):
            self.preview("inbox")

    def set_reminder(self, hour: int, minute: int) -> None:
        """Give task1 a reminder time, packed as Things stores it."""
        with write_db(self.db_path) as conn:
            conn.execute("UPDATE TMTask SET reminderTime = ? WHERE uuid = 'task1'", ((hour << 26) | (minute << 20),))

    def test_reminder_in_row_and_detail(self) -> None:
        self.set_reminder(14, 30)
        row = serve.list_response("today")["groups"][1]["tasks"][0]
        self.assertEqual(row["reminder_label"], "2:30 PM")
        self.assertEqual(serve.task_detail("task1")["task"]["when"]["reminder"], "2:30 PM")

    def test_preview_keeps_reminder_unless_when_changes(self) -> None:
        self.set_reminder(9, 15)
        for changes in ({}, {"title": "Renamed"}, {"priority": "P3"}, {"when": "today"}):
            with self.subTest(changes=changes):
                preview = self.preview(**changes)
                self.assertEqual((preview["when"]["reminder"], preview["row"]["reminder_label"]), ("9:15 AM", "9:15 AM"))
        # Whether Things keeps the reminder when When changes is unconfirmed, so it is left out.
        for when in ((TODAY + timedelta(days=1)).isoformat(), "someday", "anytime"):
            with self.subTest(when=when):
                preview = self.preview(when=when)
                self.assertEqual((preview["when"]["reminder"], preview["row"]["reminder_label"]), (None, None))

    def test_unconfirmed_edit_reported(self) -> None:
        self.apply_change.return_value = False
        self.assertEqual(self.edit(title="X"), {"ok": False, "write_failed": True})


class SearchTests(MockThingsTestCase):
    """Saved searches: listing, the builder's preview, saving and deleting."""

    def setUp(self) -> None:
        super().setUp()
        self.add_tags("P2", "P3", "Calls")
        later = pack_things_date(TODAY + timedelta(days=3))
        past = pack_things_date(TODAY - timedelta(days=2))
        with write_db(self.db_path) as conn:
            conn.execute("INSERT INTO TMArea (uuid, title) VALUES ('area1', 'Work')")
            conn.execute(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, project, \"index\") "
                "VALUES ('proj1', 'Vacation', 1, 0, 0, NULL, 0)"
            )
            rows = [
                # uuid, title, notes, startDate, deadline, project, area
                ("call", "Call insurance", "", pack_things_date(TODAY), None, None, "area1"),
                ("hotel", "Book hotel", "Lisbon trip", pack_things_date(TODAY), later, "proj1", None),
                ("late", "Late", "", pack_things_date(TODAY), past, None, None),
                ("anytime", "Call someday", "", None, None, None, None),  # Not in Today.
            ]
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, notes, type, status, trashed, start, startDate, deadline, "
                f"project, area, todayIndex, \"index\") VALUES (?, ?, ?, 0, {STATUS_OPEN}, 0, {START_ANYTIME}, "
                "?, ?, ?, ?, 1, 0)",
                rows,
            )
            conn.executemany(
                "INSERT INTO TMTaskTag VALUES (?, ?)",
                [("task1", "P3"), ("call", "P2"), ("call", "Calls"), ("hotel", "P2"), ("hotel", "Calls"),
                 ("anytime", "Calls")],
            )

    def ids(self, response: dict) -> list:
        """The task ids of a search response."""
        return [t["id"] for t in response["tasks"]]

    def test_defaults_in_sidebar(self) -> None:
        response = serve.list_response("today")
        self.assertEqual(
            [s["name"] for s in response["searches"]],
            ["P1 · Due Today", "P2 · To Do", "P3 · Follow Up", "P4 · Next Up", "Overdue"],
        )
        self.assertNotIn("search", response)

    def test_overdue_default_covers_every_open_task(self) -> None:
        self.assertEqual(self.ids(serve.list_response("overdue")), ["late"])

    def test_custom_search_lists_matches_with_summary_and_pills(self) -> None:
        self.use_searches(Search("s1", "Calls", tags=("Calls",)))
        response = serve.list_response("s1")
        # "anytime" isn't in Today.
        self.assertEqual(self.ids(response), ["hotel", "call"])  # Deadline first.
        self.assertEqual(response["summary"], "Today tasks · tag Calls")
        self.assertEqual(response["search"]["tags"], ["Calls"])
        self.assertEqual([t["priority"] for t in response["tasks"]], ["P2", "P2"])
        self.assertEqual([s["id"] for s in response["searches"]], ["s1"])

    def test_criteria_combine(self) -> None:
        self.use_searches(
            Search("a", "Text", text="lisbon"),
            Search("b", "Work", lists=("area1",)),
            Search("c", "All calls", tags=("Calls",), scope="all"),
            Search("d", "P2 calls", priorities=("P2",), tags=("Calls",)),
        )
        self.assertEqual(self.ids(serve.list_response("a")), ["hotel"])
        self.assertEqual(self.ids(serve.list_response("b")), ["call"])
        found = serve.list_response("c")
        self.assertEqual(self.ids(found), ["hotel", "call", "anytime"])
        self.assertEqual([t["priority"] for t in found["tasks"]], ["P2", "P2", None])  # Not in Today: no P tag.
        one = serve.list_response("d")
        self.assertEqual(self.ids(one), ["hotel", "call"])
        self.assertEqual([t["priority"] for t in one["tasks"]], [None, None])  # One priority: no pills.

    def test_unknown_search(self) -> None:
        with self.assertRaises(serve.ApiError) as raised:
            serve.list_response("s9")
        self.assertEqual(raised.exception.status, 404)

    def test_preview_reads_only_and_gives_choices(self) -> None:
        with mock.patch.object(serve, "apply_refresh_rules") as refresh, \
                mock.patch.object(serve, "save_searches") as save:
            preview = serve.preview_search({"search": {"name": "", "tags": ["Calls"], "scope": "all"}})
        refresh.assert_not_called()
        save.assert_not_called()
        self.apply_change.assert_not_called()
        self.assertEqual(set(self.ids(preview)), {"anytime", "call", "hotel"})
        self.assertEqual(preview["summary"], "All open tasks · tag Calls")
        self.assertEqual(preview["choices"]["tags"], ["Calls"])
        self.assertEqual(
            preview["choices"]["lists"],
            [{"id": "area1", "title": "Work", "kind": "area"}, {"id": "proj1", "title": "Vacation", "kind": "project"}],
        )
        with self.assertRaises(serve.ApiError):
            serve.preview_search({"search": {"name": "X", "priorities": ["P9"]}})

    def test_save_new_and_update(self) -> None:
        saved = serve.save_search({"search": {"name": " Calls ", "tags": ["Calls"]}})
        self.assertEqual((saved["search"]["id"], saved["search"]["name"]), ("s1", "Calls"))
        self.assertEqual(saved["searches"][-1], {"id": "s1", "name": "Calls"})
        serve.save_search({"search": {"id": "p2", "name": "To do now", "priorities": ["P2"]}})
        names = [s["name"] for s in serve.list_response("today")["searches"]]
        self.assertEqual(names, ["P1 · Due Today", "To do now", "P3 · Follow Up", "P4 · Next Up", "Overdue", "Calls"])

    def test_save_refusals(self) -> None:
        for body, status in (
            ({"search": {"name": ""}}, 400),
            ({"search": {"name": "overdue"}}, 400),  # Taken, ignoring case.
            ({"search": {"name": "X", "tags": ["P1"]}}, 400),
            ({"search": {"id": "s7", "name": "X"}}, 404),
        ):
            with self.subTest(body=body), self.assertRaises(serve.ApiError) as raised:
                serve.save_search(body)
            self.assertEqual(raised.exception.status, status)
        self.assertFalse(os.path.exists(self.searches_path))

    def test_delete(self) -> None:
        self.assertEqual([s["id"] for s in serve.delete_search({"id": "p3"})["searches"]], ["p1", "p2", "p4", "overdue"])
        with self.assertRaises(serve.ApiError):
            serve.delete_search({"id": "p3"})
        for search in ("p1", "p2", "p4", "overdue"):
            serve.delete_search({"id": search})
        self.assertEqual(serve.list_response("today")["searches"], [])  # Stays empty.
        self.apply_change.assert_not_called()

    def test_edit_preview_places_row_in_search(self) -> None:
        self.use_searches(Search("s1", "Calls", tags=("Calls",)), Search("s2", "P2", priorities=("P2",)))
        preview = lambda name, **changes: serve.preview_edit({"id": "call", "list": name, "changes": changes})
        self.assertEqual(preview("s1")["place"], "list")
        self.assertEqual(preview("s1")["row"]["priority"], "P2")  # Pills in a search of any priority.
        self.assertIsNone(preview("s2")["row"]["priority"])
        self.assertIsNone(preview("s1", tags=[])["place"])  # Removing the tag leaves the search.
        self.assertIsNone(preview("s2", priority="P3")["place"])
        with self.assertRaises(serve.ApiError):
            preview("p1")  # No longer a search.


class RowDisplayTests(unittest.TestCase):
    """Rows are described the way Things shows them."""

    def test_deadline_wording(self) -> None:
        cases = {-3: "3 days ago", -1: "1 day ago", 0: "today", 1: "1 day left", 9: "9 days left"}
        for offset, label in cases.items():
            with self.subTest(offset=offset):
                self.assertEqual(serve.deadline_label(TODAY + timedelta(days=offset), TODAY), label)
        self.assertIsNone(serve.deadline_label(None, TODAY))

    def test_start_badge(self) -> None:
        self.assertIsNone(serve.start_label(None, TODAY))
        self.assertIsNone(serve.start_label(TODAY, TODAY))
        self.assertIsNone(serve.start_label(TODAY - timedelta(days=2), TODAY))
        self.assertEqual(serve.start_label(TODAY + timedelta(days=2), TODAY), "Mon")  # 2026-11-09.
        self.assertEqual(serve.start_label(TODAY + timedelta(days=7), TODAY), "Nov 14")
        self.assertEqual(serve.start_label(date(2027, 1, 5), TODAY), "Jan 5, 2027")

    def test_row_fields(self) -> None:
        task = Task(uuid="A1", title="T", tags=["Home", "P1"], notes="  ", repeating=True, has_checklist=True)
        row = serve.task_to_json(task, TODAY)
        self.assertEqual((row["tags"], row["priority"]), (["Home"], None))  # P tags are never among the tags.
        self.assertEqual(serve.task_to_json(task, TODAY, priority_pill=True)["priority"], "P1")
        self.assertFalse(row["has_notes"])  # Only whitespace.
        self.assertTrue(row["has_checklist"] and row["repeating"])
        self.assertTrue(serve.task_to_json(Task(uuid="A2", title="T", notes="x"), TODAY)["has_notes"])


    def test_reminder_wording(self) -> None:
        cases = {(9, 15): "9:15 AM", (15, 0): "3:00 PM", (0, 5): "12:05 AM", (12, 0): "12:00 PM", (23, 59): "11:59 PM"}
        for (hour, minute), label in cases.items():
            with self.subTest(label=label):
                self.assertEqual(serve.reminder_label(dt_time(hour, minute)), label)
        self.assertIsNone(serve.reminder_label(None))
        self.assertIsNone(serve.task_to_json(Task(uuid="A1", title="T"), TODAY)["reminder_label"])


class TodayViewTests(MockThingsTestCase):
    """Today by priority, by project or all in one list, the tag bar, and drops in each view."""

    def setUp(self) -> None:
        super().setUp()
        self.add_tags("P2", "P3", "P4", "P5", "Calls")
        with write_db(self.db_path) as conn:
            conn.execute('INSERT INTO TMArea (uuid, title, "index") VALUES (\'home\', \'Home Chores\', 1)')
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, area, \"index\") "
                "VALUES (?, ?, 1, 0, 0, 1, ?, ?)",
                [("vac", "Vacation", None, 0), ("books", "Books to read", "home", 0)],
            )
            tasks = [
                # uuid, todayIndex, project, area, tags
                ("hotel", 1, "vac", None, ["P2", "Calls"]),
                ("chore", 2, None, "home", ["P3"]),
                ("book", 3, "books", None, ["P4"]),
                ("call", 4, None, "home", ["P2", "Calls"]),
            ]
            for uuid, index, project, area, tags in tasks:
                conn.execute(
                    "INSERT INTO TMTask (uuid, title, type, status, trashed, start, startDate, todayIndex, "
                    "project, area, \"index\") VALUES (?, ?, 0, 0, 0, 1, ?, ?, ?, ?, 0)",
                    (uuid, uuid, pack_things_date(TODAY), index, project, area),
                )
                conn.executemany("INSERT INTO TMTaskTag VALUES (?, ?)", [(uuid, t) for t in tags])

    def keys(self, response: dict) -> list:
        """(group key, task ids) per group."""
        return [(g["key"], [t["id"] for t in g["tasks"]]) for g in response["groups"]]

    def test_priority_view_unchanged(self) -> None:
        response = serve.list_response("today")
        self.assertEqual((response["view"], response["tag"], response["tags"]), ("priority", None, ["Calls"]))
        self.assertEqual(self.keys(response)[:3], [("P1", []), ("P2", ["task1", "hotel", "call"]), ("P3", ["chore"])])
        row = response["groups"][1]["tasks"][1]
        self.assertEqual((row["context"], row["priority"]), ("Vacation", None))

    def test_project_view(self) -> None:
        response = serve.list_response("today", view="project")
        self.assertEqual(
            self.keys(response),
            [("project:vac", ["hotel"]), ("project:home", ["chore", "call"]),
             ("project:books", ["book"]), ("project:none", ["task1"])],
        )
        self.assertEqual(
            [(g["label"], g["note"], g["list_id"], g["takes_moves"]) for g in response["groups"]],
            [("Vacation", "", "vac", True), ("Home Chores", "", "home", True),
             ("Books to read", "", "books", True), ("No project", "", None, False)],
        )
        row = response["groups"][0]["tasks"][0]
        self.assertEqual((row["context"], row["priority"], row["tags"]), ("", "P2", ["Calls"]))

    def test_all_view(self) -> None:
        response = serve.list_response("today", view="all")
        self.assertEqual(self.keys(response), [("all", ["task1", "hotel", "call", "chore", "book"])])
        row = response["groups"][0]["tasks"][3]
        self.assertEqual((row["context"], row["priority"]), ("Home Chores", "P3"))

    def test_tag_filter(self) -> None:
        response = serve.list_response("today", tag="Calls")
        self.assertEqual(response["tag"], "Calls")
        self.assertEqual(self.keys(response)[1], ("P2", ["hotel", "call"]))
        self.assertEqual(self.keys(serve.list_response("today", view="project", tag="Calls")),
                         [("project:vac", ["hotel"]), ("project:home", ["call"])])
        self.assertEqual(serve.list_response("today", tag="Calls")["counts"], serve.list_response("today")["counts"])

    def test_bad_view_or_tag(self) -> None:
        for kwargs in ({"view": "grid"}, {"tag": ""}, {"tag": "x" * 201}):
            with self.assertRaises(serve.ApiError) as raised:
                serve.list_response("today", **kwargs)
            self.assertEqual(raised.exception.status, 400)

    def test_saved_view_orders_pruned_with_today(self) -> None:
        saved = {"all": ["hotel", "gone"], "project:vac": ["gone"], "P2": ["call"]}
        with mock.patch.object(serve, "load_order", return_value=saved):
            response = serve.list_response("today", view="all")
        self.assertEqual(self.keys(response)[0][1][:3], ["hotel", "call", "task1"])  # All order, then by P2 order.
        kept = serve.save_order.call_args[0][0]
        self.assertEqual((kept["all"], kept["P2"]), (["hotel"], ["call"]))
        self.assertNotIn("project:vac", kept)

    def drop(self, view: str, key: str, task_id: str, order: list) -> dict:
        """Drop `task_id` into group `key` of `view`, the page showing `order`."""
        self.apply_change.reset_mock()
        serve.save_order.reset_mock()
        return serve.drop_task({"view": view, "key": key, "id": task_id, "order": order})

    def test_reorder_through_the_tag_filter_keeps_hidden_tasks(self) -> None:
        # The page shows only Calls tasks: call dropped above hotel; task1 is hidden.
        self.assertEqual(self.drop("priority", "P2", "call", ["call", "hotel"]), {"ok": True})
        self.apply_change.assert_not_called()
        self.assertEqual(serve.save_order.call_args[0][0]["P2"], ["task1", "call", "hotel"])

    def test_priority_move(self) -> None:
        self.assertEqual(self.drop("priority", "P3", "hotel", ["chore", "hotel"]), {"ok": True})
        self.assertEqual(self.apply_change.call_args[0][0].tags, ["Calls", "P3"])
        self.assertEqual(serve.save_order.call_args[0][0]["P3"], ["chore", "hotel"])

    def test_project_move(self) -> None:
        self.assertEqual(self.drop("project", "project:vac", "chore", ["hotel", "chore"]), {"ok": True})
        change = self.apply_change.call_args[0][0]
        self.assertEqual((change.set_list_id, change.tags), ("vac", None))  # Priority kept.
        order = serve.save_order.call_args[0][0]
        self.assertEqual(order["project:vac"], ["hotel", "chore"])

    def test_project_move_to_area_and_reorder_in_a_group(self) -> None:
        self.assertEqual(self.drop("project", "project:home", "book", ["book", "chore", "call"]), {"ok": True})
        self.assertEqual(self.apply_change.call_args[0][0].set_list_id, "home")
        self.assertEqual(self.drop("project", "project:home", "call", ["call", "chore"]), {"ok": True})
        self.apply_change.assert_not_called()
        self.assertEqual(serve.save_order.call_args[0][0]["project:home"], ["call", "chore"])

    def test_unconfirmed_move_saves_no_order(self) -> None:
        self.apply_change.return_value = False
        self.assertEqual(self.drop("project", "project:vac", "chore", ["chore", "hotel"]),
                         {"ok": False, "write_failed": True})
        serve.save_order.assert_not_called()

    def test_all_view_only_reorders(self) -> None:
        self.assertEqual(self.drop("all", "all", "book", ["book", "task1"]), {"ok": True})
        self.apply_change.assert_not_called()
        self.assertEqual(serve.save_order.call_args[0][0]["all"], ["book", "task1", "hotel", "call", "chore"])

    def test_refused_drops(self) -> None:
        cases = [
            (("project", "project:none", "hotel", ["task1", "hotel"]), 409, "out of a project"),
            (("project", "project:zzz", "hotel", ["hotel"]), 400, "Unknown project"),
            (("all", "P1", "hotel", ["hotel"]), 400, "can't be moved"),
            (("priority", "all", "hotel", ["hotel"]), 400, "can't be moved"),
            (("priority", "P2", "nothere", ["nothere"]), 404, "no longer in Today"),
            (("priority", "P2", "hotel", ["call"]), 400, "Invalid task order"),
            (("grid", "P2", "hotel", ["hotel"]), 400, "Unknown view"),
            (("priority", "P9", "hotel", ["hotel"]), 400, "Unknown group"),
        ]
        for args, status, text in cases:
            with self.subTest(args=args), self.assertRaises(serve.ApiError) as raised:
                self.drop(*args)
            self.assertEqual(raised.exception.status, status)
            self.assertIn(text, raised.exception.message)
        self.apply_change.assert_not_called()
        serve.save_order.assert_not_called()

    def test_preview_place_in_each_view(self) -> None:
        preview = lambda **body: serve.preview_edit({"id": "hotel", "list": "today", **body})
        moved = preview(view="project", changes={"list_id": "books"})
        self.assertEqual(moved["place"], "project:books")
        self.assertEqual((moved["row"]["context"], moved["row"]["priority"]), ("", "P2"))
        self.assertEqual(preview(view="all", changes={"title": "Hotel"})["place"], "all")
        self.assertEqual(preview(view="all", changes={})["row"]["context"], "Vacation")
        self.assertEqual(preview(changes={"priority": "P3"})["place"], "P3")
        self.assertIsNone(preview(view="all", tag="Calls", changes={"tags": []})["place"])  # Loses the chosen tag.
        with self.assertRaises(serve.ApiError):
            preview(view="grid", changes={})


class ListRoutingTests(MockThingsTestCase):
    """Things' own lists open in Things; only Today and the searches are served."""

    def test_things_lists_not_served(self) -> None:
        for name in THINGS_LISTS:
            with self.assertRaises(serve.ApiError):
                serve.list_response(name)

    def test_show_list_opens_things_in_foreground(self) -> None:
        with mock.patch.object(serve, "open_url", return_value=True) as opener:
            self.assertEqual(serve.show_list({"name": "logbook"}), {"ok": True})
        opener.assert_called_once_with("things:///show?id=logbook", background=False)

    def test_show_list_rejects_other_names(self) -> None:
        with mock.patch.object(serve, "open_url") as opener:
            for name in ("today", "p1", "nope", None):
                with self.assertRaises(serve.ApiError):
                    serve.show_list({"name": name})
        opener.assert_not_called()


class DisconnectedWriter(io.RawIOBase):
    """A response stream whose browser has gone away."""

    def write(self, data: bytes) -> int:
        """Fail like a socket whose peer has closed."""
        raise BrokenPipeError(32, "Broken pipe")


class DisconnectTests(unittest.TestCase):
    """A browser that disconnects early is ignored, not logged as a Things error."""

    def make_handler(self) -> serve.Handler:
        """Build a handler without a real socket."""
        handler = serve.Handler.__new__(serve.Handler)
        handler.wfile = DisconnectedWriter()
        handler.request_version = "HTTP/1.1"
        handler.command, handler.path = "GET", "/api/list?name=today"
        handler.requestline = "GET /api/list?name=today HTTP/1.1"
        return handler

    def test_send_failure_not_logged_as_read_error(self) -> None:
        handler = self.make_handler()
        with mock.patch.object(serve, "get_logger") as logger, self.assertRaises(ConnectionError):
            handler._run(lambda: {"ok": True})
        logger.assert_not_called()

    def test_handle_ignores_disconnect(self) -> None:
        handler = self.make_handler()
        with mock.patch.object(BaseHTTPRequestHandler, "handle", side_effect=BrokenPipeError()):
            handler.handle()  # Must not raise.

    def test_handle_still_raises_other_errors(self) -> None:
        handler = self.make_handler()
        with mock.patch.object(BaseHTTPRequestHandler, "handle", side_effect=ValueError()):
            with self.assertRaises(ValueError):
                handler.handle()


if __name__ == "__main__":
    unittest.main()
