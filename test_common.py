"""Tests for common.py: token handling, Things dates, URLs, order file and database queries.

Database tests run against a small SQLite file built with the parts of the
Things schema that Do Things reads, so no real Things data is touched.

Version: 2.0.1

Change log:
- v2.0.1 (2026-11-10): Synchronized module version metadata.
- v2.0.0 (2026-11-10): Tests for read_sidebar (sidebar order, no TMArea.index)
  and the view orders in task_order.json; TMArea has an index column.
- v1.9.2 (2026-11-10): Synchronized module version metadata.
- v1.9.1 (2026-11-10): Synchronized module version metadata.
- v1.9.0 (2026-11-10): Tests for the searches file and the list of every open
  task; the fixed P and Overdue search queries are gone.
- v1.8.0 (2026-11-10): Tests for the calendar scripts (run_jxa, the read
  script never asking for access, read_calendar) and the Calendar event URL;
  open_things_url is now open_url.
- v1.7.1 (2026-11-10): Synchronized module version metadata.
- v1.7.0 (2026-11-10): Tests for read_sequential_projects with the listed tags,
  task reads carrying their project's tags, and missing_tags; the project tag
  reads, update-project URL and project change tests removed.
- v1.6.0 (2026-11-10): Tests for the settings file; P5 among the missing tags.
- v1.5.0 (2026-11-08): Tests for the trash AppleScript command and move_to_trash.
- v1.4.0 (2026-11-08): Test that task reads carry the reminder time.
- v1.3.1 (2026-11-08): Tests for the reminder time format and the raw reminder read.
- v1.3.0 (2026-11-08): Synchronized module version metadata.
- v1.2.0 (2026-11-08): Test for the next_up flag.
- v1.1.0 (2026-11-08): Tests for the P4 search, Next Up project queries, the
  update-project URL and project change confirmation.
- v1.0.3 (2026-11-07): Synchronized module version metadata.
- v1.0.2 (2026-11-07): Synchronized module version metadata.
- v1.0.1 (2026-11-07): Change log trimmed to v1.0.0 and later; earlier history is in git.
- v1.0.0 (2026-11-07): Test that today and midnight follow the system time zone;
  midnight comes from start_of_day. Test that a failed `open` never logs the
  auth token.
"""

import contextlib
import logging.handlers
import os
import sqlite3
import stat
import subprocess
import tempfile
import time
import unittest
import urllib.parse
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from typing import Iterator
from unittest import mock
from zoneinfo import ZoneInfo

from common import (
    CALENDAR_READ_SCRIPT,
    CALENDAR_REQUEST_SCRIPT,
    build_calendar_event_url,
    read_calendar,
    run_jxa,
    LOG_MAX_BYTES,
    Pull,
    START_ANYTIME,
    START_INBOX,
    START_SOMEDAY,
    STATUS_COMPLETED,
    STATUS_OPEN,
    THINGS_LISTS,
    build_show_url,
    build_trash_command,
    build_update_url,
    count_completed,
    count_inbox,
    describe_open_failure,
    get_logger,
    is_valid_task_id,
    load_order,
    load_pulls,
    load_searches,
    load_settings,
    load_token,
    missing_priority_tags,
    missing_tags,
    move_to_trash,
    open_things_db,
    open_url,
    pack_things_date,
    read_checklist_progress,
    read_edit_options,
    read_last_completed,
    read_list,
    read_raw_reminder_times,
    read_sequential_projects,
    read_sidebar,
    read_task,
    run_trash_script,
    save_order,
    save_pulls,
    save_searches,
    save_settings,
    save_token,
    start_of_day,
    today_local,
    unpack_things_date,
    unpack_things_time,
    validate_token,
)
from priority_check import DEFAULT_SETTINGS, Change, Settings
from search_check import DEFAULT_SEARCHES, Search

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
    stopDate REAL, rt1_recurrenceRule BLOB, rt1_repeatingTemplate TEXT, notes TEXT,
    reminderTime INTEGER
);
CREATE TABLE TMArea (uuid TEXT PRIMARY KEY, title TEXT, "index" INTEGER);
CREATE TABLE TMTag (uuid TEXT PRIMARY KEY, title TEXT);
CREATE TABLE TMTaskTag (tasks TEXT, tags TEXT);
CREATE TABLE TMChecklistItem (uuid TEXT PRIMARY KEY, title TEXT, status INTEGER, task TEXT, "index" INTEGER);
"""


class LoggerTests(unittest.TestCase):
    """errors.log is size-capped."""

    def test_log_is_capped_with_one_older_copy(self) -> None:
        handler = get_logger().handlers[0]
        self.assertIsInstance(handler, logging.handlers.RotatingFileHandler)
        self.assertEqual((handler.maxBytes, handler.backupCount), (LOG_MAX_BYTES, 1))


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


class OpenFailureLoggingTests(unittest.TestCase):
    """A failed `open` is logged without the auth token."""

    URL = "things:///update?id=A1&auth-token=secret-token-123&tags=P2"

    def test_token_never_logged(self) -> None:
        failures = [
            subprocess.CalledProcessError(1, ["open", "-g", self.URL]),
            subprocess.TimeoutExpired(["open", "-g", self.URL], 10),
            FileNotFoundError(2, "No such file or directory", "open"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with mock.patch("common.subprocess.run", side_effect=failure), \
                        self.assertLogs("dothings", level="ERROR") as logs:
                    self.assertFalse(open_url(self.URL, background=True))
                logged = "\n".join(logs.output)
                self.assertNotIn("secret-token-123", logged)
                self.assertIn("things:///update", logged)

    def test_failure_descriptions(self) -> None:
        self.assertEqual(
            describe_open_failure(subprocess.CalledProcessError(1, ["open", self.URL])),
            "open exited with status 1",
        )
        self.assertEqual(
            describe_open_failure(subprocess.TimeoutExpired(["open", self.URL], 10)),
            "open timed out after 10 seconds",
        )


class TimeZoneTests(unittest.TestCase):
    """Today and midnight follow the Mac's own time zone."""

    def setUp(self) -> None:
        self.saved_tz = os.environ.get("TZ")

    def tearDown(self) -> None:
        if self.saved_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.saved_tz
        time.tzset()

    def test_today_and_midnight_follow_system_time_zone(self) -> None:
        # Zones far apart, so at least one is on a different date than Denver.
        for zone in ("Pacific/Auckland", "America/Denver", "Pacific/Pago_Pago"):
            with self.subTest(zone=zone):
                os.environ["TZ"] = zone
                time.tzset()
                expected = datetime.now(ZoneInfo(zone)).date()
                self.assertEqual(today_local(), expected)
                midnight = datetime.combine(TODAY, datetime.min.time(), tzinfo=ZoneInfo(zone))
                self.assertEqual(start_of_day(TODAY), midnight.timestamp())


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


class ThingsTimeTests(unittest.TestCase):
    """Things' packed reminder time format (hour << 26 | minute << 20)."""

    def test_known_values(self) -> None:
        self.assertEqual(unpack_things_time((14 << 26) | (30 << 20)), dt_time(14, 30))
        self.assertEqual(unpack_things_time((12 << 26) | (0 << 20)), dt_time(12, 0))
        self.assertEqual(unpack_things_time(0), dt_time(0, 0))

    def test_empty_and_invalid(self) -> None:
        self.assertIsNone(unpack_things_time(None))
        self.assertIsNone(unpack_things_time(-1))
        self.assertIsNone(unpack_things_time(25 << 26))  # Hour 25.
        self.assertIsNone(unpack_things_time((9 << 26) | (61 << 20)))  # Minute 61.


class TrashScriptTests(unittest.TestCase):
    """The AppleScript command that moves a to-do to Things' Trash."""

    def test_id_is_an_argument_not_part_of_the_script(self) -> None:
        command = build_trash_command("Abc-123")
        self.assertEqual(command[0], "osascript")
        self.assertEqual(command[-1], "Abc-123")
        script = [part for flag, part in zip(command[1:-1:2], command[2:-1:2]) if flag == "-e"]
        self.assertEqual(len(script) * 2, len(command) - 2)  # Only -e pairs between osascript and the id.
        self.assertNotIn("Abc-123", "\n".join(script))
        self.assertIn('delete to do id (item 1 of argv)', "\n".join(script))

    def test_invalid_id_refused(self) -> None:
        for task_id in ("", "a b", 'x" & quit', "a" * 65):
            with self.subTest(task_id=task_id), self.assertRaises(ValueError):
                build_trash_command(task_id)

    def test_failure_logged_with_osascript_error(self) -> None:
        denied = subprocess.CalledProcessError(1, ["osascript"], stderr="Not authorized to send Apple events to Things3. (-1743)\n")
        for failure, logged in ((denied, "Not authorized"), (subprocess.TimeoutExpired(["osascript"], 10), "timed out")):
            with self.subTest(logged=logged):
                with mock.patch("common.subprocess.run", side_effect=failure), \
                        self.assertLogs("dothings", level="ERROR") as logs:
                    self.assertFalse(run_trash_script("A1"))
                self.assertIn(logged, "\n".join(logs.output))


class CalendarScriptTests(unittest.TestCase):
    """Running the calendar scripts (osascript mocked) and failing safe."""

    def test_read_script_never_asks_for_access(self) -> None:
        # Only the request script may show macOS's prompt; refreshes use the read script.
        for request in ("requestFullAccessToEventsWithCompletion", "requestAccessToEntityTypeCompletion"):
            self.assertNotIn(request, CALENDAR_READ_SCRIPT)
            self.assertIn(request, CALENDAR_REQUEST_SCRIPT)
        for script in (CALENDAR_READ_SCRIPT, CALENDAR_REQUEST_SCRIPT):
            self.assertNotIn("saveEvent", script)  # Read only.
            self.assertNotIn("removeEvent", script)

    def test_run_jxa_passes_script_on_stdin(self) -> None:
        done = subprocess.CompletedProcess([], 0, stdout='{"status": 3}\n', stderr="")
        with mock.patch("common.subprocess.run", return_value=done) as ran:
            self.assertEqual(run_jxa("script", 5), ({"status": 3}, ""))
        self.assertEqual(ran.call_args[0][0], ["osascript", "-l", "JavaScript", "-"])
        self.assertEqual((ran.call_args[1]["input"], ran.call_args[1]["timeout"]), ("script", 5))

    def test_run_jxa_failures(self) -> None:
        cases = (
            (FileNotFoundError(), "need macOS"),
            (subprocess.TimeoutExpired("osascript", 5), "No answer within 5 seconds"),
            (subprocess.CompletedProcess([], 1, stdout="", stderr="execution error: -1743\n"),
             "osascript failed: execution error: -1743"),
            (subprocess.CompletedProcess([], 0, stdout="not json", stderr=""), "Unexpected output"),
            (subprocess.CompletedProcess([], 0, stdout="[1]", stderr=""), "not a JSON object"),
        )
        for outcome, message in cases:
            with self.subTest(message=message):
                kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with mock.patch("common.subprocess.run", **kwargs):
                    result, problem = run_jxa("script", 5)
                self.assertIsNone(result)
                self.assertIn(message, problem)

    def test_read_calendar(self) -> None:
        raw = {"status": 3, "calendars": [{"id": "c1", "title": "Home", "source": "iCloud", "color": "#0088ff"}],
               "events": [{"id": "E1", "title": "Dentist", "start": 1, "end": 2, "calendar_id": "c1"}]}
        with mock.patch("common.run_jxa", return_value=(raw, "")) as ran:
            read = read_calendar()
        self.assertEqual(ran.call_args[0][0], CALENDAR_READ_SCRIPT)
        self.assertEqual((read.access, [e.title for e in read.events]), ("allowed", ["Dentist"]))
        with mock.patch("common.run_jxa", return_value=({"status": 0}, "")) as ran:
            self.assertEqual(read_calendar(request_access=True).access, "not_asked")
        self.assertEqual(ran.call_args[0][0], CALENDAR_REQUEST_SCRIPT)
        with mock.patch("common.run_jxa", return_value=(None, "osascript not found")):
            read = read_calendar()
        self.assertEqual((read.access, read.problem, read.events), ("unavailable", "osascript not found", []))


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

    def test_calendar_event_url(self) -> None:
        self.assertEqual(build_calendar_event_url("AB12:CD@3"), "ical://ekevent/AB12:CD@3?method=show&options=more")

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

    def test_view_orders_kept_and_unknown_keys_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "task_order.json")
            saved = {"P1": ["A"], "all": ["B", "A"], "project:x1": ["C"], "junk": ["D"], "P2": "not a list"}
            save_order(saved, path)
            self.assertEqual(load_order(path), {"P1": ["A"], "all": ["B", "A"], "project:x1": ["C"]})


class SidebarTests(unittest.TestCase):
    """Projects and areas in Things' sidebar order (Today's Project view)."""

    def make_db(self, folder: str, area_index: bool = True) -> str:
        """Build a database with two areas and four projects, one closed; optionally no TMArea.index."""
        path = os.path.join(folder, "main.sqlite")
        schema = SCHEMA if area_index else SCHEMA.replace(', "index" INTEGER);\nCREATE TABLE TMTag', ');\nCREATE TABLE TMTag')
        with write_db(path) as conn:
            conn.executescript(schema)
            if area_index:
                conn.executemany('INSERT INTO TMArea (uuid, title, "index") VALUES (?, ?, ?)',
                                 [("work", "Work", 2), ("home", "Home", 1)])
            else:
                conn.executemany("INSERT INTO TMArea (uuid, title) VALUES (?, ?)", [("work", "Work"), ("home", "Home")])
            projects = [
                # uuid, title, status, area, index
                ("solo", "Solo", STATUS_OPEN, None, 5),
                ("first", "First", STATUS_OPEN, None, 1),
                ("garden", "Garden", STATUS_OPEN, "home", 0),
                ("report", "Report", STATUS_OPEN, "work", 0),
                ("old", "Old", STATUS_COMPLETED, "work", 1),
                ("lost", "Lost area", STATUS_OPEN, "gone", 9),
            ]
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, area, \"index\") VALUES (?, ?, 1, ?, 0, ?, ?)",
                projects,
            )
        return path

    def test_projects_outside_areas_then_each_area_with_its_projects(self) -> None:
        with tempfile.TemporaryDirectory() as folder, open_things_db(self.make_db(folder)) as conn:
            entries = read_sidebar(conn)
        self.assertEqual(
            [(e.id, e.kind, e.area) for e in entries],
            [
                ("first", "project", None), ("solo", "project", None), ("lost", "project", None),
                ("home", "area", None), ("garden", "project", "Home"),
                ("work", "area", None), ("report", "project", "Work"),
            ],
        )

    def test_areas_by_title_without_index_column(self) -> None:
        with tempfile.TemporaryDirectory() as folder, open_things_db(self.make_db(folder, False)) as conn:
            columns = [row["name"] for row in conn.execute("PRAGMA table_info(TMArea)")]
            entries = read_sidebar(conn)
        self.assertNotIn("index", columns)
        self.assertEqual([e.id for e in entries if e.kind == "area"], ["home", "work"])


class SettingsFileTests(unittest.TestCase):
    """The user's settings file."""

    def test_round_trip_and_bad_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            self.assertEqual(load_settings(path), DEFAULT_SETTINGS)  # No file yet.
            settings = Settings(names=dict(DEFAULT_SETTINGS.names, P5="Later"), auto_p1=False, default_priority="P3")
            save_settings(settings, path)
            self.assertEqual(load_settings(path), settings)
            for content in ("{not json", '{"default_priority": "P9"}'):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(content)
                # Logged and ignored: the defaults keep the rules working.
                with self.subTest(content=content), self.assertLogs("dothings", level="ERROR"):
                    self.assertEqual(load_settings(path), DEFAULT_SETTINGS)


class SearchesFileTests(unittest.TestCase):
    """The saved-searches file."""

    def test_round_trip_and_bad_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "searches.json")
            self.assertEqual(load_searches(path), DEFAULT_SEARCHES)  # No file yet.
            searches = (Search("s1", "Calls", tags=("Calls",)),)
            save_searches(searches, path)
            self.assertEqual(load_searches(path), searches)
            save_searches((), path)
            self.assertEqual(load_searches(path), ())  # Deleting every search is kept.
            for content in ("{not json", '{"searches": [{"id": "s1"}]}'):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(content)
                # Logged and ignored: the sidebar falls back to the defaults.
                with self.subTest(content=content), self.assertLogs("dothings", level="ERROR"):
                    self.assertEqual(load_searches(path), DEFAULT_SEARCHES)


class PullsFileTests(unittest.TestCase):
    """The record of tasks Do Things started in sequential projects."""

    def test_round_trip_and_malformed_entries(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "pulls.json")
            self.assertEqual(load_pulls(path), {})
            save_pulls({"P1": Pull("t1", TODAY, "t0"), "P2": Pull("t2", TODAY)}, path)
            self.assertEqual(load_pulls(path), {"P1": Pull("t1", TODAY, "t0"), "P2": Pull("t2", TODAY, None)})
            with open(path, "w", encoding="utf-8") as handle:
                # A v0.1.17 entry (no "after"), then malformed ones.
                handle.write('{"P1": {"task": "t1", "date": "2026-11-07"}, "P2": {"task": "t2"}, "P3": "x", '
                             '"P4": {"task": 5, "date": "2026-11-07"}, "P5": {"task": "t", "date": "2026-11-07", "after": 3}}')
            self.assertEqual(load_pulls(path), {"P1": Pull("t1", TODAY, None)})
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not json")
            self.assertEqual(load_pulls(path), {})


class DatabaseTests(unittest.TestCase):
    """List queries against a mock Things database."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.folder.name, "main.sqlite")
        conn = sqlite3.connect(self.path)
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO TMTag VALUES (?, ?)", [("t1", "P1"), ("t2", "P2"), ("t3", "Home, Office")])
        conn.execute("INSERT INTO TMArea (uuid, title) VALUES ('area1', 'Work')")
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
        midnight = start_of_day(TODAY)
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
        for name in ("today", "open"):
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

    def test_due_task_removed_from_things_today_still_listed(self) -> None:
        # Things keeps a due task out of its Today once the user removes it
        # (deadlineSuppressionDate); Do Things always shows what is due.
        with write_db(self.path) as conn:
            conn.execute("UPDATE TMTask SET deadlineSuppressionDate = 1 WHERE uuid = 'overdue'")
        self.assertIn("overdue", self._ids("today"))

    def test_open_list_reads_every_open_todo(self) -> None:
        # Searches covering all open tasks filter this list; Today's searches filter Today.
        self.assertEqual(
            set(self._ids("open")), {"today1", "today2", "overdue", "future", "someday", "inbox", "anytime"}
        )

    def test_todos_under_closed_or_trashed_parents_hidden(self) -> None:
        # Today and the open list are checked against the expected lists in the tests
        # above; this names the hidden to-dos explicitly.
        hidden = {
            "in_trashproj", "in_doneproj", "in_cancelproj",
            "in_trashhead", "in_donehead", "in_headintrash", "done_in_trashproj",
        }
        for name in ("today", "open"):
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

    def test_repeating_and_checklist_flags(self) -> None:
        with write_db(self.path) as conn:
            conn.execute("UPDATE TMTask SET rt1_repeatingTemplate = 'tmpl' WHERE uuid = 'today1'")
            conn.execute("INSERT INTO TMChecklistItem VALUES ('c1', 'One', 0, 'today2', 0)")
        with open_things_db(self.path) as conn:
            one, two = read_task(conn, "today1"), read_task(conn, "today2")
        self.assertEqual((one.repeating, one.has_checklist), (True, False))
        self.assertEqual((two.repeating, two.has_checklist), (False, True))

    def test_raw_reminder_times(self) -> None:
        packed = (9 << 26) | (15 << 20)
        with write_db(self.path) as conn:
            conn.execute("UPDATE TMTask SET reminderTime = ? WHERE uuid = 'today1'", [packed])
        with open_things_db(self.path) as conn:
            # Only tasks that have a reminder are returned; unknown ids are ignored.
            self.assertEqual(read_raw_reminder_times(conn, ["today1", "today2", "nope"]), {"today1": packed})
            self.assertEqual(read_raw_reminder_times(conn, []), {})
            self.assertEqual(read_task(conn, "today1").reminder, dt_time(9, 15))
            self.assertIsNone(read_task(conn, "today2").reminder)

    def test_checklist_progress(self) -> None:
        with write_db(self.path) as conn:
            conn.executemany(
                "INSERT INTO TMChecklistItem VALUES (?, ?, ?, 'today1', 0)",
                [("c1", "One", STATUS_OPEN), ("c2", "Two", STATUS_COMPLETED), ("c3", "Three", STATUS_CANCELED)],
            )
        with open_things_db(self.path) as conn:
            self.assertEqual(read_checklist_progress(conn, "today1"), {"done": 2, "total": 3})
            self.assertEqual(read_checklist_progress(conn, "today2"), {"done": 0, "total": 0})

    def test_project_fields_and_sequential_projects(self) -> None:
        with write_db(self.path) as conn:
            conn.execute("INSERT INTO TMTag VALUES ('tseq', 'Sequential')")
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, \"index\") VALUES (?, ?, 1, ?, 0, 0)",
                [("seq", "Seq", STATUS_OPEN), ("closed", "Closed", STATUS_COMPLETED)],
            )
            conn.executemany("INSERT INTO TMTaskTag VALUES (?, 'tseq')", [("seq",), ("closed",)])
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, project, heading, \"index\") "
                "VALUES (?, ?, ?, ?, 0, ?, ?, ?)",
                [
                    ("hB", "Heading B", 2, STATUS_OPEN, "seq", None, 1),
                    ("s_done", "Done", 0, STATUS_COMPLETED, "seq", None, 0),
                    ("s_top", "Top", 0, STATUS_OPEN, "seq", None, 5),
                    ("s_b", "Under B", 0, STATUS_OPEN, None, "hB", 0),
                    ("c_task", "In closed project", 0, STATUS_OPEN, "closed", None, 0),
                ],
            )
        with open_things_db(self.path) as conn:
            top, under_b = read_task(conn, "s_top"), read_task(conn, "s_b")
            self.assertEqual((top.project_id, top.project_rank), ("seq", (0, 0, 5)))
            self.assertEqual((under_b.project_id, under_b.project_rank), ("seq", (1, 1, 0)))
            self.assertEqual(read_task(conn, "today1").project_id, "proj1")
            self.assertIsNone(read_task(conn, "today2").project_id)  # In an area only.
            projects = read_sequential_projects(conn, ["Sequential"])
            self.assertEqual(read_sequential_projects(conn, []), {})  # No tags listed: no projects.
        # Only the open, tagged project; only its open to-dos (headings themselves aren't to-dos).
        self.assertEqual(set(projects), {"seq"})
        self.assertEqual(sorted(t.uuid for t in projects["seq"]), ["s_b", "s_top"])
        with write_db(self.path) as conn:
            conn.execute("UPDATE TMTask SET stopDate = 100 WHERE uuid = 's_done'")
            conn.execute("UPDATE TMTask SET status = 3, stopDate = 200 WHERE uuid = 's_b'")
        with open_things_db(self.path) as conn:
            # The most recent completion, including under a heading.
            self.assertEqual(read_last_completed(conn, ["seq"]), {"seq": "s_b"})
            self.assertEqual(read_last_completed(conn, []), {})
            self.assertEqual(count_completed(conn, ["seq"]), {"seq": 2})
            self.assertEqual(count_completed(conn, ["proj1"]), {})

    def add_tagged_projects(self) -> None:
        """Add a Next Up project with a task, an empty project tagged Sequential and Next Up, and an untagged project."""
        with write_db(self.path) as conn:
            conn.executemany(
                "INSERT INTO TMTag VALUES (?, ?)", [("tseq", "Sequential"), ("tnext", "Next Up"), ("thome", "Home")]
            )
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, \"index\") VALUES (?, ?, 1, 0, 0, 0)",
                [("books", "Books"), ("both", "Both"), ("plain", "Plain")],
            )
            conn.execute(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, project, \"index\") "
                f"VALUES ('b1', 'Book 1', 0, 0, 0, {START_ANYTIME}, 'books', 0)"
            )
            conn.executemany(
                "INSERT INTO TMTaskTag VALUES (?, ?)",
                [("books", "tnext"), ("books", "thome"), ("both", "tseq"), ("both", "tnext"), ("plain", "thome")],
            )

    def test_sequential_projects_by_listed_tag(self) -> None:
        self.add_tagged_projects()
        with open_things_db(self.path) as conn:
            ids = lambda tags: {p: [t.uuid for t in ts] for p, ts in read_sequential_projects(conn, tags).items()}
            # Projects with open to-dos only; "both" has none.
            self.assertEqual(ids(["Next Up"]), {"books": ["b1"]})
            self.assertEqual(ids(["Sequential", "Next Up"]), {"books": ["b1"]})
            self.assertEqual(ids(["Sequential"]), {})
            self.assertEqual(ids(["next up"]), {})  # Matched exactly.

    def test_task_carries_project_tags(self) -> None:
        self.add_tagged_projects()
        with write_db(self.path) as conn:
            # Under a heading of the Books project, and in the project tagged both.
            conn.execute("INSERT INTO TMTask (uuid, title, type, status, trashed, project, \"index\") "
                         "VALUES ('bh', 'Heading', 2, 0, 0, 'books', 1)")
            conn.executemany(
                "INSERT INTO TMTask (uuid, title, type, status, trashed, start, project, heading, \"index\") "
                f"VALUES (?, ?, 0, 0, 0, {START_ANYTIME}, ?, ?, 0)",
                [("b2", "Book 2", None, "bh"), ("x1", "Both 1", "both", None)],
            )
        with open_things_db(self.path) as conn:
            tags = {i: sorted(read_task(conn, i).project_tags) for i in ("b1", "b2", "x1", "today1", "today2")}
        self.assertEqual(tags, {"b1": ["Home", "Next Up"], "b2": ["Home", "Next Up"],
                                "x1": ["Next Up", "Sequential"], "today1": [], "today2": []})

    def test_move_to_trash_confirmed_by_database(self) -> None:
        def things_trashes(command: list, **kwargs: object) -> subprocess.CompletedProcess:
            with write_db(self.path) as conn:
                conn.execute("UPDATE TMTask SET trashed = 1 WHERE uuid = 'today1'")
            return subprocess.CompletedProcess(command, 0)

        with mock.patch("common.CONFIRM_POLL_SECONDS", 0.01), mock.patch("common.CONFIRM_TIMEOUT_SECONDS", 0.2), \
                mock.patch("common.get_logger"):
            with mock.patch("common.subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
                self.assertFalse(move_to_trash("today1", self.path))  # Things didn't trash it.
            with mock.patch("common.subprocess.run", side_effect=things_trashes) as ran:
                self.assertTrue(move_to_trash("today1", self.path))
            self.assertEqual(ran.call_args[0][0], build_trash_command("today1"))
            with mock.patch("common.subprocess.run") as never:
                self.assertFalse(move_to_trash("bad id!", self.path))  # Refused before osascript runs.
            never.assert_not_called()

    def test_task_fields(self) -> None:
        with open_things_db(self.path) as conn:
            task = read_task(conn, "today1")
            self.assertEqual(sorted(task.tags), ["Home, Office", "P1"])
            self.assertEqual(task.start_date, TODAY)
            self.assertEqual(task.context, "Project")
            self.assertEqual(read_task(conn, "today2").context, "Work")
            self.assertIsNone(read_task(conn, "missing"))
            self.assertEqual(missing_priority_tags(conn), ["P3", "P4", "P5"])
            self.assertEqual(missing_tags(conn, ["P5", "P1", "Sequential"]), ["P5", "Sequential"])
            self.assertEqual(missing_tags(conn, []), [])

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
