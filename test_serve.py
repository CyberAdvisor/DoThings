"""Tests for serve.py: missing-tag guards, opening Things lists, and client disconnects.

Uses a mock Things database (schema from test_common.py). Things itself and
the auth token are replaced with mocks, so nothing is sent to Things.

Version: 0.1.6

Change log:
- v0.1.6 (2026-11-07): Tests for completing and reopening tasks, and for
  completed tasks in list responses.
- v0.1.5 (2026-11-07): Initial release.
"""

import io
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from unittest import mock

import serve
from common import (
    LOCAL_TZ,
    START_ANYTIME,
    STATUS_COMPLETED,
    STATUS_OPEN,
    THINGS_LISTS,
    pack_things_date,
)
from test_common import SCHEMA, TODAY


class MockThingsTestCase(unittest.TestCase):
    """Base case: a mock database with one untagged Today task and only the P1 tag."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.folder.name, "main.sqlite")
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
        with sqlite3.connect(self.db_path) as conn:
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


class CompletionTests(MockThingsTestCase):
    """Completing and reopening tasks, and how completed tasks are listed."""

    def add_completed_task(self, uuid: str) -> None:
        """Add a P1-tagged Today task completed one minute after midnight."""
        midnight = datetime.combine(TODAY, datetime.min.time(), tzinfo=LOCAL_TZ).timestamp()
        with sqlite3.connect(self.db_path) as conn:
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

    def test_completed_task_cannot_be_moved(self) -> None:
        self.add_completed_task("done1")
        with self.assertRaises(serve.ApiError) as raised:
            serve.move_task({"id": "done1", "priority": "P1", "order": ["done1"]})
        self.assertIn("Uncheck", raised.exception.message)

    def test_completed_tasks_listed_last_and_flagged(self) -> None:
        # done1 sorts first in Things (todayIndex -1) but must come after open tasks.
        self.add_completed_task("done1")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO TMTaskTag VALUES ('task1', 't1')")
        p1 = serve.list_response("p1")["tasks"]
        self.assertEqual([(t["id"], t["completed"]) for t in p1], [("task1", False), ("done1", True)])
        group = serve.list_response("today")["groups"][0]
        self.assertEqual([t["id"] for t in group["tasks"]], ["task1", "done1"])


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
