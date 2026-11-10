"""Shared logic for Do Things.

Holds file paths, version loading, logging, read-only access to the Things
database, Things URL commands, the AppleScript that moves a to-do to the Trash,
the read-only calendar script (today's events from macOS Calendar), the local
task-order file, the user's settings and saved-search files and the auth
token.

Version: 2.0.2

Change log:
- v2.0.2 (2026-11-10): Synchronized module version metadata.
- v2.0.1 (2026-11-10): Synchronized module version metadata.
- v2.0.0 (2026-11-10): read_sidebar reads Things' open projects and its areas in
  sidebar order (Today's Project view); load_order keeps the All and Project
  view orders.
- v1.9.2 (2026-11-10): Synchronized module version metadata.
- v1.9.1 (2026-11-10): Synchronized module version metadata.
- v1.9.0 (2026-11-10): Saved searches in searches.json (SEARCHES_PATH,
  load_searches, save_searches). read_list reads Today or every open task
  (OPEN_LISTS); the fixed P and Overdue queries and APP_LISTS are removed.
- v1.8.0 (2026-11-10): Calendar reading: the EventKit script (moved from
  debug_calendar.py and split into reading and an access request that checks
  the access status instead of waiting for macOS's reply), run_jxa,
  run_calendar_script and read_calendar. open_things_url is now open_url (it
  also opens Calendar's event links).
- v1.7.1 (2026-11-10): Synchronized module version metadata.
- v1.7.0 (2026-11-10): Every task read carries its project's tags
  (Task.project_tags); read_sequential_projects takes the tags listed in
  Settings; missing_tags checks any tag names; the project reads and the
  things:///update-project write are removed (Do Things never changes projects).
- v1.6.0 (2026-11-10): settings.json (SETTINGS_PATH) with load_settings and
  save_settings; P5 search derived from PRIORITIES.
- v1.5.0 (2026-11-08): move_to_trash moves a to-do to Things' Trash with
  AppleScript (task id passed as an argument) and confirms trashed = 1; the
  send-and-confirm loop takes a send step, shared by URL and AppleScript writes.
- v1.4.0 (2026-11-08): Every task read carries its reminder time.
- v1.3.1 (2026-11-08): Reads Things' reminder times for the diagnostic
  (read_raw_reminder_times) and decodes them (unpack_things_time).
- v1.3.0 (2026-11-08): Synchronized module version metadata.
- v1.2.0 (2026-11-08): Every task read carries next_up (project tagged Next Up
  and not Sequential).
- v1.1.0 (2026-11-08): Reads Next Up projects with the Sequential ones, and
  project tags (read_sequence_project_tags, read_project_tags);
  things:///update-project URL and confirmed project tag change
  (apply_project_change), sharing the send-and-confirm loop with apply_change;
  P4 search; APP_LISTS derived from PRIORITIES.
- v1.0.3 (2026-11-07): Synchronized module version metadata.
- v1.0.2 (2026-11-07): Synchronized module version metadata.
- v1.0.1 (2026-11-07): Change log trimmed to v1.0.0 and later; earlier history is in git.
- v1.0.0 (2026-11-07): today_local and start_of_day use the Mac's time zone instead of
  Mountain Time (LOCAL_TZ removed). Fixed: a failed or timed-out `open` logged
  the full command, including the auth token; describe_open_failure now logs
  only the kind of failure.
"""

import contextlib
import glob
import json
import logging
import logging.handlers
import os
import re
import sqlite3
import subprocess
import time
import urllib.parse
from collections import Counter
from datetime import date, datetime
from datetime import time as dt_time  # `time` is the standard-library module used for timeouts.
from typing import Callable, Dict, Iterable, Iterator, List, NamedTuple, Optional, Tuple

from calendar_check import ACCESS_UNAVAILABLE, CalendarRead, parse_calendar_output
from priority_check import (
    DEFAULT_SETTINGS,
    PRIORITIES,
    Change,
    Settings,
    Task,
    is_order_key,
    parse_settings,
)
from search_check import DEFAULT_SEARCHES, Search, parse_searches, searches_json
from view_check import ListEntry

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_PATH = os.path.join(BASE_DIR, "VERSION")
ERRORS_LOG_PATH = os.path.join(BASE_DIR, "errors.log")
LOG_MAX_BYTES = 1024 * 1024  # errors.log size cap (one older copy is kept).
INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")
ORDER_PATH = os.path.join(BASE_DIR, "task_order.json")
TOKEN_PATH = os.path.join(BASE_DIR, "auth_token.txt")
PULLS_PATH = os.path.join(BASE_DIR, "sequence_pulls.json")
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")
SEARCHES_PATH = os.path.join(BASE_DIR, "searches.json")

# Things 3 keeps its data in this group container. Since Things 3.15 the
# database sits in a ThingsData-XXXXX subfolder; older versions put it directly
# in the container. Both layouts are searched.
THINGS_CONTAINER_PATH = os.path.expanduser(
    "~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac"
)
THINGS_DB_PATTERNS = (
    os.path.join(THINGS_CONTAINER_PATH, "ThingsData-*", "Things Database.thingsdatabase", "main.sqlite"),
    os.path.join(THINGS_CONTAINER_PATH, "Things Database.thingsdatabase", "main.sqlite"),
)

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765

# How long to wait for Things to show a write in its database, and how often to look.
CONFIRM_TIMEOUT_SECONDS = 5.0
CONFIRM_POLL_SECONDS = 0.25

# Things task ids are short base58-style strings; anything else is rejected
# before it reaches a URL or a shell command.
TASK_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")

# Things TMTask column values used by the queries (full list in CLAUDE_CONTEXT.md).
TYPE_TODO, TYPE_PROJECT, TYPE_HEADING = 0, 1, 2
STATUS_OPEN, STATUS_COMPLETED = 0, 3
START_INBOX, START_ANYTIME, START_SOMEDAY = 0, 1, 2

# What read_list reads: Today, or every open task (searches with that scope).
OPEN_LISTS = ("today", "open")
# Built-in Things lists that the sidebar opens in Things (things:///show?id=<list>).
THINGS_LISTS = ("inbox", "upcoming", "anytime", "someday", "logbook")


def load_project_version() -> str:
    """Read the project version from VERSION; raise if it is missing or empty."""
    with open(VERSION_PATH, encoding="utf-8") as handle:
        version = handle.read().strip()
    if not version:
        raise RuntimeError(f"VERSION file is empty: {VERSION_PATH}")
    return version


PROJECT_VERSION = load_project_version()


def get_logger() -> logging.Logger:
    """Return the shared logger, which writes warnings and errors to errors.log.

    The log is capped: past LOG_MAX_BYTES it moves to errors.log.1 (replacing
    the previous one) and a new errors.log starts.
    """
    logger = logging.getLogger("dothings")
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            ERRORS_LOG_PATH, maxBytes=LOG_MAX_BYTES, backupCount=1, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                f"%(asctime)s version={PROJECT_VERSION} %(levelname)s %(message)s"
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
    return logger


def today_local() -> date:
    """Return today's date in the Mac's own time zone."""
    return date.today()


def start_of_day(day: date) -> float:
    """Return the Unix time of local midnight at the start of `day` (Mac time zone).

    A naive datetime's timestamp() is interpreted in the system time zone,
    including any daylight-saving change.
    """
    return datetime.combine(day, datetime.min.time()).timestamp()


# --- Things dates ---------------------------------------------------------
# Things stores startDate and deadline as a packed integer:
# year << 16 | month << 12 | day << 7.


def pack_things_date(value: date) -> int:
    """Encode a date in Things' packed-integer format."""
    return (value.year << 16) | (value.month << 12) | (value.day << 7)


def unpack_things_date(value: Optional[int]) -> Optional[date]:
    """Decode a Things packed date; return None for empty or invalid values."""
    if not value or value <= 0:
        return None
    try:
        return date(value >> 16, (value >> 12) & 0xF, (value >> 7) & 0x1F)
    except ValueError:
        # Fail safe: an unreadable date is treated as no date, never as overdue.
        return None


# Things stores a to-do's reminder time (TMTask.reminderTime) as a packed
# integer: hour << 26 | minute << 20. This layout is not documented by Things;
# it was checked against real reminders (9:15 AM, 3:00 PM) on 2026-11-08, and
# debug_things.py prints the raw and decoded values to check it again.


def unpack_things_time(value: Optional[int]) -> Optional[dt_time]:
    """Decode a Things packed reminder time; return None for empty or invalid values."""
    if value is None or value < 0:
        return None
    try:
        return dt_time((value >> 26) & 0x1F, (value >> 20) & 0x3F)
    except ValueError:
        # Fail safe: an unreadable time is treated as no reminder, never shown wrong.
        return None


# --- Things database (read-only) -----------------------------------------


def find_things_db_path() -> Optional[str]:
    """Return the newest Things database path, or None if it cannot be found."""
    candidates: List[str] = []
    for pattern in THINGS_DB_PATTERNS:
        candidates.extend(glob.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


@contextlib.contextmanager
def open_things_db(path: str) -> Iterator[sqlite3.Connection]:
    """Open the Things database read-only (so this app can never modify it) and close it after use."""
    uri = "file:" + urllib.parse.quote(path) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# Columns shared by every task query. Tags are concatenated with the ASCII unit
# separator (char 31) because tag names may contain commas, both the to-do's
# own and its project's (directly or via its heading), which decide whether it
# belongs to a sequential project (priority_check.sequence_priority).
_TASK_SELECT = f"""
SELECT t.uuid, t.title, t.notes, t.start, t.startDate, t.deadline, t.status, t.stopDate, t.reminderTime,
       COALESCE(t.project, h.project, t.area) AS list_id, t.heading AS heading_id,
       COALESCE(t.project, h.project) AS project_id, h."index" AS heading_index, t."index" AS task_index,
       t.rt1_repeatingTemplate IS NOT NULL AS repeating,
       EXISTS (SELECT 1 FROM TMChecklistItem ci WHERE ci.task = t.uuid) AS has_checklist,
       COALESCE(p.title, hp.title, a.title, ha.title, '') AS context,
       (SELECT group_concat(pg.title, char(31))
          FROM TMTaskTag pt JOIN TMTag pg ON pg.uuid = pt.tags
         WHERE pt.tasks = COALESCE(t.project, h.project)) AS project_tag_titles,
       (SELECT group_concat(tg.title, char(31))
          FROM TMTaskTag tt JOIN TMTag tg ON tg.uuid = tt.tags
         WHERE tt.tasks = t.uuid) AS tag_titles
FROM TMTask t
LEFT JOIN TMTask p ON p.uuid = t.project
LEFT JOIN TMTask h ON h.uuid = t.heading
LEFT JOIN TMTask hp ON hp.uuid = h.project
LEFT JOIN TMArea a ON a.uuid = t.area
LEFT JOIN TMArea ha ON ha.uuid = p.area
WHERE t.type = {TYPE_TODO} AND t.trashed = 0 AND t.rt1_recurrenceRule IS NULL
  AND COALESCE(p.trashed, 0) = 0 AND COALESCE(h.trashed, 0) = 0 AND COALESCE(hp.trashed, 0) = 0
"""

# A to-do keeps its own status and trashed flag when its project or heading is
# trashed, completed or canceled, so the parents are checked too: trashed in
# _TASK_SELECT (also used by read_task) and status here. A to-do with no
# project or heading counts as having an open, untrashed parent.
# Every list shows open to-dos plus those completed since the start of today
# (the `?` parameter, Unix time), which are shown checked until tomorrow.
_ACTIVE = (
    f"(t.status = {STATUS_OPEN} OR (t.status = {STATUS_COMPLETED} AND t.stopDate >= ?)) "
    f"AND COALESCE(p.status, {STATUS_OPEN}) = {STATUS_OPEN} "
    f"AND COALESCE(h.status, {STATUS_OPEN}) = {STATUS_OPEN} "
    f"AND COALESCE(hp.status, {STATUS_OPEN}) = {STATUS_OPEN}"
)


def _row_to_task(row: sqlite3.Row) -> Task:
    """Convert a task query row into a Task."""
    return Task(
        uuid=row["uuid"],
        title=row["title"] or "",
        tags=_split_tags(row["tag_titles"]),
        start_date=unpack_things_date(row["startDate"]),
        deadline=unpack_things_date(row["deadline"]),
        context=row["context"] or "",
        completed_at=row["stopDate"] if row["status"] == STATUS_COMPLETED else None,
        notes=row["notes"] or "",
        someday=row["start"] == START_SOMEDAY and row["startDate"] is None,
        list_id=row["list_id"],
        heading_id=row["heading_id"],
        project_id=row["project_id"],
        project_rank=_project_rank(row["heading_id"], row["heading_index"], row["task_index"]),
        repeating=bool(row["repeating"]),
        has_checklist=bool(row["has_checklist"]),
        project_tags=_split_tags(row["project_tag_titles"]),
        reminder=unpack_things_time(row["reminderTime"]),
    )


def _project_rank(heading_id: Optional[str], heading_index: Optional[int], task_index: Optional[int]) -> Tuple[int, int, int]:
    """Position in the project's manual order: tasks without a heading first, then by heading."""
    if heading_id is None:
        return (0, 0, task_index or 0)
    return (1, heading_index or 0, task_index or 0)


# Where clause for Do Things' Today, taking today's packed date twice: started
# tasks dated today or earlier, plus tasks due today or overdue. Unlike Things,
# a due task the user removed from Things' Today (deadlineSuppressionDate) is
# still included: Do Things always shows what is due.
_TODAY_CLAUSE = (
    f"((t.start IN ({START_ANYTIME}, {START_SOMEDAY}) AND t.startDate IS NOT NULL AND t.startDate <= ?) "
    "OR (t.deadline IS NOT NULL AND t.deadline <= ?))"
)


def _list_query(name: str, today: int) -> Tuple[str, list, str]:
    """Return (where clause, params, order clause) for one of OPEN_LISTS.

    The clause covers only what the list selects; read_list adds _ACTIVE.
    `today` is today's date in Things' packed format. Searches filter these
    lists in Python (search_check.search_results).
    """
    if name == "today":
        return _TODAY_CLAUSE, [today, today], "t.todayIndex, t.\"index\""
    if name == "open":
        return "1", [], "t.\"index\""
    raise ValueError(f"Unknown list: {name!r}")


def read_list(conn: sqlite3.Connection, name: str, today: date) -> List[Task]:
    """Return the open and today-completed to-dos in one of OPEN_LISTS, in Things' order."""
    where, params, order = _list_query(name, pack_things_date(today))
    start_of_today = start_of_day(today)
    rows = conn.execute(
        f"{_TASK_SELECT} AND {_ACTIVE} AND ({where}) ORDER BY {order}", [start_of_today] + params
    )
    return [_row_to_task(row) for row in rows]


def read_task(conn: sqlite3.Connection, task_id: str) -> Optional[Task]:
    """Return one to-do by id, or None if it does not exist."""
    row = conn.execute(f"{_TASK_SELECT} AND t.uuid = ?", [task_id]).fetchone()
    return _row_to_task(row) if row else None


def read_sequential_projects(conn: sqlite3.Connection, tags: List[str]) -> Dict[str, List[Task]]:
    """Return {project id: its open to-dos} for every open project with one of `tags`.

    `tags` are the sequential-project tags listed in Settings (none: no
    projects). Covers each whole project (not only Today), so the sequence can
    be worked out; to-dos under closed headings are left out.
    """
    if not tags:
        return {}
    marks = ", ".join("?" for _ in tags)
    sequential = (
        "EXISTS (SELECT 1 FROM TMTaskTag st JOIN TMTag sg ON sg.uuid = st.tags "
        f"WHERE st.tasks = COALESCE(t.project, h.project) AND sg.title IN ({marks}))"
    )
    open_parents = (
        f"COALESCE(p.status, {STATUS_OPEN}) = {STATUS_OPEN} AND COALESCE(h.status, {STATUS_OPEN}) = {STATUS_OPEN} "
        f"AND COALESCE(hp.status, {STATUS_OPEN}) = {STATUS_OPEN}"
    )
    projects: Dict[str, List[Task]] = {}
    rows = conn.execute(f"{_TASK_SELECT} AND t.status = {STATUS_OPEN} AND {open_parents} AND {sequential}", tags)
    for row in rows:
        task = _row_to_task(row)
        projects.setdefault(task.project_id, []).append(task)
    return projects


def _split_tags(tag_titles: Optional[str]) -> List[str]:
    """Split a unit-separator-joined tag list from a query; None means no tags."""
    return tag_titles.split(chr(31)) if tag_titles else []


def _completed_in_projects(conn: sqlite3.Connection, project_ids: Iterable[str]) -> List[sqlite3.Row]:
    """Return (uuid, project_id) of the completed, untrashed to-dos of the projects, oldest first.

    To-dos directly in a project and under its headings both count.
    """
    ids = sorted(set(project_ids))
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    return conn.execute(
        "SELECT t.uuid, COALESCE(t.project, h.project) AS project_id FROM TMTask t "
        "LEFT JOIN TMTask h ON h.uuid = t.heading "
        f"WHERE t.type = {TYPE_TODO} AND t.status = {STATUS_COMPLETED} AND t.trashed = 0 "
        f"AND COALESCE(t.project, h.project) IN ({placeholders}) ORDER BY t.stopDate",
        ids,
    ).fetchall()


def read_last_completed(conn: sqlite3.Connection, project_ids: Iterable[str]) -> Dict[str, str]:
    """Return {project id: its most recently completed to-do} (directly or under a heading)."""
    # Rows are oldest first, so later (newer) ones overwrite.
    return {row["project_id"]: row["uuid"] for row in _completed_in_projects(conn, project_ids)}


def count_completed(conn: sqlite3.Connection, project_ids: Iterable[str]) -> Dict[str, int]:
    """Return {project id: number of completed to-dos} (directly or under a heading); 0s left out."""
    return dict(Counter(row["project_id"] for row in _completed_in_projects(conn, project_ids)))


def read_edit_options(conn: sqlite3.Connection) -> Dict[str, list]:
    """Return the choices for the edit view.

    `tags`: every non-priority tag title. `areas`: [{id, title}].
    `projects`: open, untrashed projects as [{id, title, area}].
    `headings`: open, untrashed headings as [{id, title, project}].
    All sorted by title except headings, which keep Things' order.
    """
    tags = [
        row["title"] for row in conn.execute("SELECT title FROM TMTag ORDER BY title COLLATE NOCASE")
        if row["title"] not in PRIORITIES
    ]
    areas = [
        {"id": row["uuid"], "title": row["title"] or ""}
        for row in conn.execute("SELECT uuid, title FROM TMArea ORDER BY title COLLATE NOCASE")
    ]
    open_untrashed = f"status = {STATUS_OPEN} AND trashed = 0"
    projects = [
        {"id": row["uuid"], "title": row["title"] or "", "area": row["area"]}
        for row in conn.execute(
            f"SELECT uuid, title, area FROM TMTask WHERE type = {TYPE_PROJECT} AND {open_untrashed} "
            "ORDER BY title COLLATE NOCASE"
        )
    ]
    headings = [
        {"id": row["uuid"], "title": row["title"] or "", "project": row["project"]}
        for row in conn.execute(
            f"SELECT uuid, title, project FROM TMTask WHERE type = {TYPE_HEADING} AND {open_untrashed} "
            "ORDER BY \"index\""
        )
    ]
    return {"tags": tags, "areas": areas, "projects": projects, "headings": headings}


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """True if Things' `table` has `column` (its schema is undocumented and can change)."""
    return any(row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def read_sidebar(conn: sqlite3.Connection) -> List[ListEntry]:
    """Return Things' open projects and its areas in sidebar order.

    Projects outside an area come first, then each area followed by its
    projects, each by its sidebar position (`index`). If a table has no
    `index` column (an older or changed schema), it is read by title instead.
    """
    area_order = '"index", title COLLATE NOCASE' if _has_column(conn, "TMArea", "index") else "title COLLATE NOCASE"
    areas = [(row["uuid"], row["title"] or "") for row in conn.execute(f"SELECT uuid, title FROM TMArea ORDER BY {area_order}")]
    area_titles = dict(areas)
    by_area: Dict[Optional[str], List[ListEntry]] = {}
    for row in conn.execute(
        f"SELECT uuid, title, area FROM TMTask WHERE type = {TYPE_PROJECT} AND status = {STATUS_OPEN} "
        'AND trashed = 0 ORDER BY "index", title COLLATE NOCASE'
    ):
        area = row["area"] if row["area"] in area_titles else None  # An unknown area counts as none.
        by_area.setdefault(area, []).append(ListEntry(row["uuid"], row["title"] or "", "project", area_titles.get(area)))
    entries = list(by_area.get(None, []))
    for area_id, title in areas:
        entries.append(ListEntry(area_id, title, "area"))
        entries.extend(by_area.get(area_id, []))
    return entries


def count_inbox(conn: sqlite3.Connection) -> int:
    """Return the number of open, untrashed to-dos in Things' Inbox."""
    row = conn.execute(
        f"SELECT COUNT(*) FROM TMTask WHERE type = {TYPE_TODO} AND status = {STATUS_OPEN} "
        f"AND trashed = 0 AND start = {START_INBOX} AND rt1_recurrenceRule IS NULL"
    ).fetchone()
    return row[0]


def read_checklist_progress(conn: sqlite3.Connection, task_id: str) -> Dict[str, int]:
    """Return {"done", "total"} for a task's checklist (both 0 if it has none).

    Completed and canceled checklist items both count as done, as in Things.
    """
    row = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(status != {STATUS_OPEN}), 0) FROM TMChecklistItem WHERE task = ?",
        [task_id],
    ).fetchone()
    return {"done": row[1], "total": row[0]}


def read_raw_reminder_times(conn: sqlite3.Connection, task_ids: Iterable[str]) -> Dict[str, int]:
    """Return the raw reminderTime of each given task that has one.

    Used by debug_things.py to show the packed value next to the decoded time.
    """
    ids = list(task_ids)
    if not ids:
        return {}
    marks = ", ".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT uuid, reminderTime FROM TMTask WHERE uuid IN ({marks}) AND reminderTime IS NOT NULL", ids
    )
    return {row["uuid"]: row["reminderTime"] for row in rows}


def missing_tags(conn: sqlite3.Connection, tags: Iterable[str]) -> List[str]:
    """Return those of `tags` that do not exist in Things (exact names), in the given order."""
    existing = {row["title"] for row in conn.execute("SELECT title FROM TMTag")}
    return [tag for tag in tags if tag not in existing]


def missing_priority_tags(conn: sqlite3.Connection) -> List[str]:
    """Return the P tags that do not exist in Things (the URL scheme ignores unknown tags)."""
    return missing_tags(conn, PRIORITIES)


# --- Things URL commands --------------------------------------------------


def is_valid_task_id(task_id: object) -> bool:
    """Return True if `task_id` looks like a Things task id."""
    return isinstance(task_id, str) and bool(TASK_ID_RE.match(task_id))


def _tags_param(tags: List[str]) -> str:
    """Join tags for a URL command's `tags` parameter.

    Raises ValueError if a tag contains a comma, because the URL scheme uses
    commas to separate tags and the tags would be split incorrectly.
    """
    if any("," in tag for tag in tags):
        raise ValueError(f"Tag containing a comma cannot be written: {tags!r}")
    return ",".join(tags)


def _things_url(command: str, params: Dict[str, str]) -> str:
    """Build a things:///<command> URL; commas are left as-is to separate tags."""
    return f"things:///{command}?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe=",")


def build_update_url(change: Change, token: str) -> str:
    """Build the things:///update URL that applies `change`.

    Raises ValueError if a tag contains a comma (see _tags_param).
    """
    params = {"id": change.task_id, "auth-token": token}
    if change.tags is not None:
        params["tags"] = _tags_param(change.tags)
    if change.set_deadline is not None:
        params["deadline"] = change.set_deadline.isoformat()
    elif change.clear_deadline:
        params["deadline"] = ""  # An empty value clears the deadline.
    if change.set_start_date is not None:
        params["when"] = change.set_start_date.isoformat()
    elif change.set_when is not None:
        params["when"] = change.set_when
    if change.set_title is not None:
        params["title"] = change.set_title
    if change.set_notes is not None:
        params["notes"] = change.set_notes
    if change.set_list_id is not None:
        params["list-id"] = change.set_list_id
    if change.set_heading_id is not None:
        params["heading-id"] = change.set_heading_id
    if change.set_completed is not None:
        params["completed"] = "true" if change.set_completed else "false"
    return _things_url("update", params)


def build_calendar_event_url(event_id: str) -> str:
    """Build the ical:// URL that shows one event in Calendar.

    `event_id` must already pass calendar_check.is_valid_event_id: its
    characters (letters, digits, ":", ".", "_", "@", "-") are all allowed in a
    URL path, so it goes in as Calendar knows it, without encoding.
    """
    return f"ical://ekevent/{event_id}?method=show&options=more"


def build_show_url(target_id: str) -> str:
    """Build the things:///show URL that opens a task, or one of THINGS_LISTS, in Things."""
    return "things:///show?" + urllib.parse.urlencode({"id": target_id})


def open_url(url: str, background: bool) -> bool:
    """Hand a URL (things:/// or Calendar's ical://) to macOS. Returns False (and logs) on failure.

    `background` keeps the app from coming to the front (open -g).
    """
    command = ["open", "-g", url] if background else ["open", url]
    try:
        subprocess.run(command, check=True, timeout=10, capture_output=True)
        return True
    except (OSError, subprocess.SubprocessError) as error:
        # Log the URL without its query, which contains the auth token.
        get_logger().error(
            "Could not open URL (%s): %s", url.split("?")[0], describe_open_failure(error)
        )
        return False


def describe_open_failure(error: Exception) -> str:
    """Describe why `open` failed without repeating its command.

    str() of a failed or timed-out subprocess repeats the full command, which
    here includes the URL and its auth token, so it must never be logged.
    """
    if isinstance(error, subprocess.CalledProcessError):
        return f"open exited with status {error.returncode}"
    if isinstance(error, subprocess.TimeoutExpired):
        return f"open timed out after {error.timeout} seconds"
    if isinstance(error, OSError) and error.strerror:
        return error.strerror
    return type(error).__name__


def apply_change(change: Change, token: str, db_path: str) -> bool:
    """Send `change` to Things and wait until the database confirms it.

    Returns True only when the re-read task matches the change.
    """
    def confirmed(conn: sqlite3.Connection) -> bool:
        task = read_task(conn, change.task_id)
        return task is not None and change.is_satisfied_by(task)

    what = f"task {change.task_id}"
    return _send_and_confirm(lambda: _open_update_url(lambda: build_update_url(change, token), what),
                             confirmed, what, db_path)


def move_to_trash(task_id: str, db_path: str) -> bool:
    """Move a to-do to Things' Trash and wait until the database shows it trashed.

    The URL scheme has no delete, so this is the one write that uses
    AppleScript. It needs macOS's Automation permission for the app running
    Do Things (Terminal or Shortcuts) instead of the auth token.
    """
    def confirmed(conn: sqlite3.Connection) -> bool:
        row = conn.execute("SELECT trashed FROM TMTask WHERE uuid = ?", [task_id]).fetchone()
        return row is not None and row["trashed"] == 1  # A vanished row is not a confirmation.

    return _send_and_confirm(lambda: run_trash_script(task_id), confirmed, f"task {task_id}", db_path)


# AppleScript that deletes one to-do, which Things moves to its Trash
# (confirmed on a real task 2026-11-08). The task id is passed as an argument
# (argv), never written into the script, so it can't change what the script does.
TRASH_SCRIPT = (
    "on run argv",
    'tell application "Things3" to delete to do id (item 1 of argv)',
    "end run",
)


def build_trash_command(task_id: str) -> List[str]:
    """Return the osascript command that moves `task_id` to Things' Trash."""
    if not is_valid_task_id(task_id):
        raise ValueError(f"invalid task id {task_id!r}")
    command = ["osascript"]
    for line in TRASH_SCRIPT:
        command += ["-e", line]
    return command + [task_id]


def run_trash_script(task_id: str) -> bool:
    """Run the trash AppleScript for `task_id`. Returns False (and logs) on failure.

    osascript's error output names the problem (e.g. "Not authorized to send
    Apple events to Things3" when the Automation permission is off), and the
    command holds no secret, so both are safe to log.
    """
    try:
        subprocess.run(build_trash_command(task_id), check=True, timeout=10, capture_output=True, text=True)
        return True
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        detail = (getattr(error, "stderr", None) or "").strip() or str(error)
        get_logger().error("Could not move task %s to the Trash: %s", task_id, detail)
        return False


def _open_update_url(build_url: Callable[[], str], what: str) -> bool:
    """Build a things:/// URL with `build_url` and hand it to Things in the background.

    Returns False (and logs) if the URL can't be built (e.g. a tag containing
    a comma) or `open` fails.
    """
    try:
        url = build_url()
    except ValueError as error:
        get_logger().error("Skipped %s: %s", what, error)
        return False
    return open_url(url, background=True)


def _send_and_confirm(
    send: Callable[[], bool], confirmed: Callable[[sqlite3.Connection], bool], what: str, db_path: str
) -> bool:
    """Run `send`, then re-read the database until `confirmed` holds.

    `what` names the task in log lines. Returns False (and logs) if
    sending fails or Things doesn't confirm in time.
    """
    if not send():
        return False
    logger = get_logger()
    deadline = time.monotonic() + CONFIRM_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(CONFIRM_POLL_SECONDS)
        try:
            with open_things_db(db_path) as conn:
                if confirmed(conn):
                    return True
        except sqlite3.Error as error:
            logger.warning("Could not re-read %s: %s", what, error)
    logger.error("Things did not confirm the change to %s (see the checks shown on the page)", what)
    return False


# --- Calendar (read only) --------------------------------------------------

# How long one calendar read may take, and how long an access request may wait
# for the user to answer macOS's prompt (Do Things' server waits meanwhile).
CALENDAR_READ_TIMEOUT_SECONDS = 10
CALENDAR_REQUEST_TIMEOUT_SECONDS = 75

# JavaScript for Automation shared by both calendar scripts: helpers and
# readCalendar(), which returns the access status and, with full access, the
# calendars and today's events (midnight to midnight, Mac time zone; EventKit
# expands repeating events). It only reads: no EventKit save or remove call.
_CALENDAR_JS = r"""
ObjC.import('Foundation');
ObjC.import('AppKit');
ObjC.import('EventKit');

const ENTITY_EVENT = 0;  // EKEntityTypeEvent
const FULL_ACCESS = 3;   // EKAuthorizationStatusFullAccess (authorized before macOS 14)

// Turn an NSString (or nil) into a JS string.
function text(value) {
  return value === undefined || value === null || value.isNil() ? '' : ObjC.unwrap(value);
}

// A calendar's color as "#rrggbb" in sRGB, or '' if it has none.
function hexColor(color) {
  if (color === undefined || color.isNil()) return '';
  const rgb = color.colorUsingColorSpace($.NSColorSpace.sRGBColorSpace);
  if (rgb.isNil()) return '';
  const part = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0');
  return '#' + part(rgb.redComponent) + part(rgb.greenComponent) + part(rgb.blueComponent);
}

function accessStatus() {
  return Number($.EKEventStore.authorizationStatusForEntityType(ENTITY_EVENT));
}

function readCalendar() {
  const out = { status: accessStatus() };
  if (out.status !== FULL_ACCESS) return out;
  const store = $.EKEventStore.alloc.init;
  const started = Date.now();
  const calendars = store.calendarsForEntityType(ENTITY_EVENT);
  out.calendars = [];
  for (let i = 0; i < calendars.count; i++) {
    const c = calendars.objectAtIndex(i);
    out.calendars.push({
      id: text(c.calendarIdentifier),
      title: text(c.title),
      source: c.source.isNil() ? '' : text(c.source.title),
      color: hexColor(c.color),
    });
  }
  const calendar = $.NSCalendar.currentCalendar;
  const start = calendar.startOfDayForDate($.NSDate.date);
  const DAY_UNIT = 16;  // NSCalendarUnitDay (1 << 4), written out in case the enum isn't bridged.
  const end = calendar.dateByAddingUnitValueToDateOptions(DAY_UNIT, 1, start, 0);
  const events = store.eventsMatchingPredicate(store.predicateForEventsWithStartDateEndDateCalendars(start, end, $()));
  out.events = [];
  for (let i = 0; i < events.count; i++) {
    const e = events.objectAtIndex(i);
    const cal = e.calendar;
    out.events.push({
      id: text(e.eventIdentifier),
      title: text(e.title),
      all_day: !!(e.allDay !== undefined ? e.allDay : e.isAllDay),  // Property name or getter.
      start: Number(e.startDate.timeIntervalSince1970),
      end: Number(e.endDate.timeIntervalSince1970),
      calendar_id: cal.isNil() ? '' : text(cal.calendarIdentifier),
      calendar: cal.isNil() ? '' : text(cal.title),
      status: Number(e.status),
      repeating: !!e.hasRecurrenceRules,
    });
  }
  out.read_ms = Date.now() - started;
  return out;
}
"""

# Reads only; never asks for access (so a refresh can never show a prompt).
CALENDAR_READ_SCRIPT = _CALENDAR_JS + r"""
function run() {
  return JSON.stringify(readCalendar());
}
"""

# Asks for access if macOS hasn't asked yet, then reads. The request's
# completion block doesn't reliably arrive in osascript (seen on macOS 27.2),
# so it waits for the access status to change instead, up to 60 seconds.
CALENDAR_REQUEST_SCRIPT = _CALENDAR_JS + r"""
function requestAccess() {
  const answer = { answered: false };
  const store = $.EKEventStore.alloc.init;
  const done = () => { answer.answered = true; };
  try {
    if (typeof store.requestFullAccessToEventsWithCompletion === 'function') {
      answer.method = 'requestFullAccessToEventsWithCompletion';
      store.requestFullAccessToEventsWithCompletion(done);
    } else {
      answer.method = 'requestAccessToEntityTypeCompletion';
      store.requestAccessToEntityTypeCompletion(ENTITY_EVENT, done);
    }
  } catch (e) {
    answer.error = 'request failed: ' + e;
    return answer;
  }
  const until = Date.now() + 60000;
  while (!answer.answered && accessStatus() === 0 && Date.now() < until) {
    $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.25));
  }
  answer.answered = answer.answered || accessStatus() !== 0;
  return answer;
}

function run() {
  const out = { status_before: accessStatus() };
  if (out.status_before === 0) out.request = requestAccess();
  return JSON.stringify(Object.assign(out, readCalendar()));
}
"""


def run_jxa(script: str, timeout: int) -> Tuple[Optional[dict], str]:
    """Run a JavaScript for Automation script; return (its JSON result or None, a problem).

    The script goes in on standard input, so it is never parsed as
    command-line options. The problem is '' when the script ran and returned
    a JSON object.
    """
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-"],
            input=script, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except FileNotFoundError:
        return None, "osascript not found: calendar events need macOS."
    except subprocess.TimeoutExpired:
        return None, f"No answer within {timeout} seconds (a permission prompt left open?)."
    if result.returncode != 0:
        return None, f"osascript failed: {result.stderr.strip() or 'no message'}"
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None, f"Unexpected output: {result.stdout.strip()[:300]!r}"
    return (data, "") if isinstance(data, dict) else (None, "Unexpected output: not a JSON object.")


def run_calendar_script(request_access: bool) -> Tuple[Optional[dict], str]:
    """Run the calendar script (asking for access first if `request_access`); return its raw result and a problem."""
    if request_access:
        return run_jxa(CALENDAR_REQUEST_SCRIPT, CALENDAR_REQUEST_TIMEOUT_SECONDS)
    return run_jxa(CALENDAR_READ_SCRIPT, CALENDAR_READ_TIMEOUT_SECONDS)


def read_calendar(request_access: bool = False) -> CalendarRead:
    """Read today's events from macOS Calendar; any failure is "unavailable" with the problem, never an error.

    Only `request_access` can make macOS show its permission prompt; plain
    reads (every refresh) never do.
    """
    raw, problem = run_calendar_script(request_access)
    if raw is None:
        return CalendarRead(ACCESS_UNAVAILABLE, problem=problem)
    return parse_calendar_output(raw)


# --- Local task order -----------------------------------------------------


def _load_json_object(path: str) -> dict:
    """Load a JSON object from `path`; a missing, unreadable or non-object file counts as empty."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        get_logger().error("Ignoring unreadable file %s: %s", path, error)
        return {}
    if not isinstance(data, dict):
        get_logger().error("Ignoring malformed file %s", path)
        return {}
    return data


def _save_json(data: object, path: str) -> None:
    """Save JSON atomically, so a crash never leaves a half-written file."""
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(temp_path, path)


def load_order(path: str = ORDER_PATH) -> Dict[str, List[str]]:
    """Load the saved orders (each priority, All, each Project view group); an unreadable file counts as empty.

    Unknown keys and entries that aren't lists of ids are ignored.
    """
    data = _load_json_object(path)
    return {
        key: [i for i in ids if isinstance(i, str)]
        for key, ids in data.items()
        if is_order_key(key) and isinstance(ids, list)
    }


def save_order(order: Dict[str, List[str]], path: str = ORDER_PATH) -> None:
    """Save the orders of every view."""
    _save_json(order, path)


class Pull(NamedTuple):
    """A task Do Things started in a sequential project.

    `task` was given the start date `started_on`. `after` is the task whose
    completion led to it, or None (first start, or recorded by v0.1.17); if
    `after` is opened again, the start is undone.
    """

    task: str
    started_on: date
    after: Optional[str] = None


def load_pulls(path: str = PULLS_PATH) -> Dict[str, Pull]:
    """Load {project id: Pull} for tasks Do Things started.

    Malformed entries are skipped, so a damaged file never causes an undo.
    """
    pulls: Dict[str, Pull] = {}
    for project, entry in _load_json_object(path).items():
        try:
            after = entry.get("after")
            if not isinstance(entry["task"], str) or not (after is None or isinstance(after, str)):
                raise TypeError("ids must be strings")
            pulls[project] = Pull(entry["task"], date.fromisoformat(entry["date"]), after)
        except (AttributeError, TypeError, KeyError, ValueError):
            get_logger().error("Ignoring malformed sequence entry for project %s", project)
    return pulls


def save_pulls(pulls: Dict[str, Pull], path: str = PULLS_PATH) -> None:
    """Save the tasks Do Things started in sequential projects."""
    _save_json(
        {p: {"task": r.task, "date": r.started_on.isoformat(), "after": r.after} for p, r in pulls.items()},
        path,
    )


# --- Settings -------------------------------------------------------------


def load_settings(path: str = SETTINGS_PATH) -> Settings:
    """Load the user's settings; a missing file gives the defaults.

    An unreadable or invalid file is logged and the defaults are used, so a
    damaged file never stops the rules (the defaults are Do Things' original
    behavior).
    """
    if not os.path.exists(path):
        return DEFAULT_SETTINGS
    try:
        return parse_settings(_load_json_object(path))
    except ValueError as error:
        get_logger().error("Ignoring invalid settings file %s: %s", path, error)
        return DEFAULT_SETTINGS


def save_settings(settings: Settings, path: str = SETTINGS_PATH) -> None:
    """Save the user's settings."""
    _save_json(settings.to_json(), path)


def load_searches(path: str = SEARCHES_PATH) -> Tuple[Search, ...]:
    """Load the saved searches; a missing file gives the default searches.

    An unreadable or invalid file is logged and the defaults are used, so the
    sidebar always has searches (saving a search then replaces the file).
    """
    if not os.path.exists(path):
        return DEFAULT_SEARCHES
    try:
        return parse_searches(_load_json_object(path))
    except ValueError as error:
        get_logger().error("Ignoring invalid searches file %s: %s", path, error)
        return DEFAULT_SEARCHES


def save_searches(searches: Iterable[Search], path: str = SEARCHES_PATH) -> None:
    """Save the searches, in sidebar order."""
    _save_json(searches_json(searches), path)


# --- Auth token -----------------------------------------------------------


def validate_token(token: object) -> str:
    """Return the token with surrounding whitespace removed.

    Raises ValueError if it is empty or contains whitespace or line breaks.
    The real token can only be proven by a confirmed write to Things.
    """
    if not isinstance(token, str):
        raise ValueError("The token must be text.")
    cleaned = token.strip()
    if not cleaned:
        raise ValueError("The token is empty.")
    if any(ch.isspace() for ch in cleaned):
        raise ValueError("The token must not contain spaces or line breaks.")
    return cleaned


def load_token(path: str = TOKEN_PATH) -> Optional[str]:
    """Return the saved token, or None if it is missing or invalid."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return validate_token(handle.read())
    except (OSError, ValueError) as error:
        get_logger().error("Ignoring unusable token file %s: %s", path, error)
        return None


def save_token(token: str, path: str = TOKEN_PATH) -> None:
    """Validate and save the token, readable and writable by the owner only (0600)."""
    cleaned = validate_token(token)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(cleaned + "\n")
    os.chmod(path, 0o600)  # Tighten an existing file that was created looser.
