"""Tests for serve.py: missing-tag guards, opening Things lists, and client disconnects.

Uses a mock Things database (schema from test_common.py). Things itself and
the auth token are replaced with mocks, so nothing is sent to Things.

Version: 0.1.21

Change log:
- v0.1.21 (2026-11-07): Synchronized module version metadata.
- v0.1.20 (2026-11-07): Synchronized module version metadata.
- v0.1.19 (2026-11-07): Tests for Things-style row data: deadline wording,
  start badge, all tags, notes/checklist/repeating flags.
- v0.1.18 (2026-11-07): Sequence flow tests use Pull records with the
  triggering task, including Things moving the reopened task to the bottom.
- v0.1.17 (2026-11-07): The sequence record is kept in the test's temporary
  folder; tests for undoing a started task when an earlier one is reopened.
- v0.1.16 (2026-11-07): Sequential project tests now check that the next
  undated task gets a start date of today, one at a time.
- v0.1.15 (2026-11-07): Tests for sequential projects and project order in Today.
- v0.1.14 (2026-11-07): Synchronized module version metadata.
- v0.1.13 (2026-11-07): Synchronized module version metadata.
- v0.1.12 (2026-11-07): Counts test uses `not_due`.
- v0.1.11 (2026-11-07): Test for hiding completed tasks.
- v0.1.10 (2026-11-07): Tests for sidebar counts in list responses and
  checklist progress in the task detail.
- v0.1.9 (2026-11-07): Test that a refresh gives an undated task due today a
  start date of today.
- v0.1.8 (2026-11-07): Removed the repeating-copy refusal test (no longer
  refused); the task detail returns today's date.
- v0.1.7 (2026-11-07): Tests for loading a task for editing and saving edits,
  including validation, missing tags, repeating copies and the saved order.
- v0.1.6 (2026-11-07): Tests for completing and reopening tasks, and for
  completed tasks in list responses.
- v0.1.5 (2026-11-07): Initial release.
"""

import io
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler
from unittest import mock

import serve
from priority_check import Task
from common import (
    LOCAL_TZ,
    Pull,
    START_ANYTIME,
    STATUS_COMPLETED,
    STATUS_OPEN,
    THINGS_LISTS,
    load_pulls,
    pack_things_date,
    save_pulls,
)
from test_common import SCHEMA, TODAY, write_db


class MockThingsTestCase(unittest.TestCase):
    """Base case: a mock database with one untagged Today task and only the P1 tag."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.folder.name, "main.sqlite")
        self.pulls_path = os.path.join(self.folder.name, "sequence_pulls.json")
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
            # Keep the sequence record in the temporary folder, never the project's.
            mock.patch.object(serve, "load_pulls", lambda: load_pulls(self.pulls_path)),
            mock.patch.object(serve, "save_pulls", lambda pulls: save_pulls(pulls, self.pulls_path)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.apply_change = mock.patch.object(serve, "apply_change", return_value=True).start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def add_tags(self, *names: str) -> None:
        """Create more tags in the mock database."""
        with write_db(self.db_path) as conn:
            conn.executemany("INSERT INTO TMTag VALUES (?, ?)", [(n, n) for n in names])


class MissingTagTests(MockThingsTestCase):
    """While a P tag is missing, nothing is written to Things."""

    def test_refresh_skipped_while_tags_missing(self) -> None:
        response = serve.list_response("today")
        self.assertEqual(response["missing_tags"], ["P2", "P3"])
        self.assertFalse(response["write_failed"])
        self.apply_change.assert_not_called()

    def test_refresh_runs_once_tags_exist(self) -> None:
        self.add_tags("P2", "P3")
        response = serve.list_response("today")
        self.assertEqual(response["missing_tags"], [])
        self.apply_change.assert_called_once()
        self.assertEqual(self.apply_change.call_args[0][0].tags, ["P2"])

    def test_move_to_missing_tag_refused_with_instructions(self) -> None:
        with self.assertRaises(serve.ApiError) as raised:
            serve.move_task({"id": "task1", "priority": "P3", "order": ["task1"]})
        self.assertEqual(raised.exception.status, 409)
        self.assertIn("Create the P3 tag in Things first", raised.exception.message)
        self.apply_change.assert_not_called()

    def test_move_to_existing_tag_allowed(self) -> None:
        self.assertEqual(serve.move_task({"id": "task1", "priority": "P1", "order": ["task1"]}), {"ok": True})
        self.apply_change.assert_called_once()


class StartDateRefreshTests(MockThingsTestCase):
    """A refresh gives tasks with no start date that are due today a start date of today."""

    def test_inbox_anytime_and_someday_tasks_due_today(self) -> None:
        self.add_tags("P2", "P3")
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
        self.add_tags("P2", "P3", "Sequential")
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


class CompletionTests(MockThingsTestCase):
    """Completing and reopening tasks, and how completed tasks are listed."""

    def add_completed_task(self, uuid: str) -> None:
        """Add a P1-tagged Today task completed one minute after midnight."""
        midnight = datetime.combine(TODAY, datetime.min.time(), tzinfo=LOCAL_TZ).timestamp()
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

    def test_completed_task_cannot_be_moved(self) -> None:
        self.add_completed_task("done1")
        with self.assertRaises(serve.ApiError) as raised:
            serve.move_task({"id": "done1", "priority": "P1", "order": ["done1"]})
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


class EditTests(MockThingsTestCase):
    """Loading a task for the inline editor and saving edits."""

    def setUp(self) -> None:
        super().setUp()
        self.add_tags("P2", "P3", "Home")
        with write_db(self.db_path) as conn:
            conn.execute("INSERT INTO TMArea VALUES ('area1', 'Work')")
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
        self.assertEqual((task["priority"], task["when"]), ("P2", {"kind": "today", "date": TODAY.isoformat()}))
        self.assertEqual((task["tags"], task["other_tags"]), (["P2"], []))
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
        self.save_order.assert_called_once_with({"P1": ["x", "task1"], "P2": [], "P3": []})

    def test_invalid_changes_rejected(self) -> None:
        for changes in ({"title": ""}, {"title": "two\nlines"}, {"when": "evening"}, {"deadline": "soon"},
                        {"priority": "P4"}, {"tags": ["Nope"]}, {"list_id": "nosuch"},
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

    def test_unconfirmed_edit_reported(self) -> None:
        self.apply_change.return_value = False
        self.assertEqual(self.edit(title="X"), {"ok": False, "write_failed": True})


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
        self.assertEqual(row["tags"], ["Home", "P1"])
        self.assertFalse(row["has_notes"])  # Only whitespace.
        self.assertTrue(row["has_checklist"] and row["repeating"])
        self.assertTrue(serve.task_to_json(Task(uuid="A2", title="T", notes="x"), TODAY)["has_notes"])


class ListRoutingTests(MockThingsTestCase):
    """Things' own lists open in Things; only Today and the searches are served."""

    def test_things_lists_not_served(self) -> None:
        for name in THINGS_LISTS:
            with self.assertRaises(serve.ApiError):
                serve.list_response(name)

    def test_show_list_opens_things_in_foreground(self) -> None:
        with mock.patch.object(serve, "open_things_url", return_value=True) as opener:
            self.assertEqual(serve.show_list({"name": "logbook"}), {"ok": True})
        opener.assert_called_once_with("things:///show?id=logbook", background=False)

    def test_show_list_rejects_other_names(self) -> None:
        with mock.patch.object(serve, "open_things_url") as opener:
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
