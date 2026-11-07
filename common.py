"""Shared logic for Do Things.

Holds file paths, version loading, logging, read-only access to the Things
database, Things URL commands, the local task-order file and the auth token.

Version: 0.1.22

Change log:
- v0.1.22 (2026-11-07): Synchronized module version metadata.
- v0.1.21 (2026-11-07): Synchronized module version metadata.
- v0.1.20 (2026-11-07): Synchronized module version metadata.
- v0.1.19 (2026-11-07): Tasks are read with whether they are a copy of a
  repeating to-do and whether they have a checklist (for the row icons).
- v0.1.18 (2026-11-07): The sequence record (Pull) also keeps `after`, the
  task whose completion led to the start; read_last_completed finds it.
- v0.1.17 (2026-11-07): load_pulls/save_pulls keep, per sequential project,
  the task Do Things started and the date it gave it (sequence_pulls.json).
  The order and pull files share _load_json_object/_save_json.
- v0.1.16 (2026-11-07): read_sequential_projects returns the open to-dos of
  each project tagged Sequential (replaces read_next_tasks); tasks no longer
  carry a sequential flag.
- v0.1.15 (2026-11-07): Tasks are read with their project, position in the
  project and whether the project is tagged Sequential; read_next_tasks
  finds each sequential project's next open task.
- v0.1.14 (2026-11-07): Synchronized module version metadata.
- v0.1.13 (2026-11-07): Synchronized module version metadata.
- v0.1.12 (2026-11-07): Synchronized module version metadata.
- v0.1.11 (2026-11-07): Synchronized module version metadata.
- v0.1.10 (2026-11-07): count_inbox for the sidebar; read_checklist_progress
  for the editor's checklist indicator.
- v0.1.9 (2026-11-07): Synchronized module version metadata.
- v0.1.8 (2026-11-07): No longer reads whether a task is a copy of a
  repeating to-do; nothing uses it now.
- v0.1.7 (2026-11-07): Tasks are read with notes, Someday state, list and
  heading, and whether they are copies of a repeating to-do. Update URLs can
  set title, notes, When anytime/someday, list-id and
  heading-id. read_edit_options lists tags, areas, projects and headings for
  the edit view.
- v0.1.6 (2026-11-07): Lists include tasks completed today (shown checked);
  tasks carry their completion time. Update URLs can complete or reopen a task
  and leave tags alone when a change has no tag list.
- v0.1.5 (2026-11-07): Inbox, Upcoming, Anytime, Someday and Logbook now open in
  Things, so their queries, LOGBOOK_LIMIT and the constants only they used are
  removed. build_show_url opens either a task or one of those Things lists.
- v0.1.4 (2026-11-07): Synchronized module version metadata.
- v0.1.3 (2026-11-07): Synchronized module version metadata.
- v0.1.2 (2026-11-07): To-dos inside a trashed project or heading are no longer
  listed, and open lists also skip to-dos whose project or heading is completed
  or canceled. Things leaves such to-dos marked open, so their own status is not
  enough.
- v0.1.1 (2026-11-07): Update URLs include `when` when a change sets the start date.
- v0.1.0 (2026-11-07): Initial release.
"""

import contextlib
import glob
import json
import logging
import os
import re
import sqlite3
import subprocess
import time
import urllib.parse
from datetime import date, datetime
from typing import Dict, Iterable, Iterator, List, NamedTuple, Optional, Tuple
from zoneinfo import ZoneInfo

from priority_check import PRIORITIES, Change, Task

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_PATH = os.path.join(BASE_DIR, "VERSION")
ERRORS_LOG_PATH = os.path.join(BASE_DIR, "errors.log")
INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")
ORDER_PATH = os.path.join(BASE_DIR, "task_order.json")
TOKEN_PATH = os.path.join(BASE_DIR, "auth_token.txt")
PULLS_PATH = os.path.join(BASE_DIR, "sequence_pulls.json")

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

LOCAL_TZ = ZoneInfo("America/Denver")
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

# A project with this tag in Things is worked in order: only its next task shows in Today.
SEQUENTIAL_TAG = "Sequential"

# Lists Do Things shows itself: Today, then the custom searches.
APP_LISTS = ("today", "p1", "p2", "p3", "overdue")
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
    """Return the shared logger, which writes warnings and errors to errors.log."""
    logger = logging.getLogger("dothings")
    if not logger.handlers:
        handler = logging.FileHandler(ERRORS_LOG_PATH, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                f"%(asctime)s version={PROJECT_VERSION} %(levelname)s %(message)s"
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)
    return logger


def today_local() -> date:
    """Return today's date in Mountain Time."""
    return datetime.now(LOCAL_TZ).date()


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


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if `table` has `column` (the Things schema varies by version)."""
    return any(row["name"] == column for row in conn.execute(f"PRAGMA table_info({table})"))


# Columns shared by every task query. Tags are concatenated with the ASCII unit
# separator (char 31) because tag names may contain commas.
_TASK_SELECT = f"""
SELECT t.uuid, t.title, t.notes, t.start, t.startDate, t.deadline, t.status, t.stopDate,
       COALESCE(t.project, h.project, t.area) AS list_id, t.heading AS heading_id,
       COALESCE(t.project, h.project) AS project_id, h."index" AS heading_index, t."index" AS task_index,
       t.rt1_repeatingTemplate IS NOT NULL AS repeating,
       EXISTS (SELECT 1 FROM TMChecklistItem ci WHERE ci.task = t.uuid) AS has_checklist,
       COALESCE(p.title, hp.title, a.title, ha.title, '') AS context,
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
    tags = row["tag_titles"].split(chr(31)) if row["tag_titles"] else []
    return Task(
        uuid=row["uuid"],
        title=row["title"] or "",
        tags=tags,
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
    )


def _project_rank(heading_id: Optional[str], heading_index: Optional[int], task_index: Optional[int]) -> Tuple[int, int, int]:
    """Position in the project's manual order: tasks without a heading first, then by heading."""
    if heading_id is None:
        return (0, 0, task_index or 0)
    return (1, heading_index or 0, task_index or 0)


def _list_query(conn: sqlite3.Connection, name: str, today: int) -> Tuple[str, list, str]:
    """Return (where clause, params, order clause) for one of APP_LISTS.

    The clause covers only what the list selects; read_list adds _ACTIVE.
    `today` is today's date in Things' packed format.
    """
    if name == "today":
        # Today = started tasks dated today or earlier, plus tasks due today or overdue.
        deadline_clause = "(t.deadline IS NOT NULL AND t.deadline <= ?"
        if _has_column(conn, "TMTask", "deadlineSuppressionDate"):
            deadline_clause += " AND t.deadlineSuppressionDate IS NULL"
        deadline_clause += ")"
        where = (
            f"((t.start IN ({START_ANYTIME}, {START_SOMEDAY}) "
            f"AND t.startDate IS NOT NULL AND t.startDate <= ?) OR {deadline_clause})"
        )
        return where, [today, today], "t.todayIndex, t.\"index\""
    if name in ("p1", "p2", "p3"):
        where = (
            "EXISTS (SELECT 1 FROM TMTaskTag tt JOIN TMTag tg "
            "ON tg.uuid = tt.tags WHERE tt.tasks = t.uuid AND tg.title = ?)"
        )
        return where, [name.upper()], "t.deadline IS NULL, t.deadline, t.\"index\""
    if name == "overdue":
        where = "t.deadline IS NOT NULL AND t.deadline < ?"
        return where, [today], "t.deadline, t.\"index\""
    raise ValueError(f"Unknown list: {name!r}")


def read_list(conn: sqlite3.Connection, name: str, today: date) -> List[Task]:
    """Return the open and today-completed to-dos in one of APP_LISTS, in Things' order."""
    where, params, order = _list_query(conn, name, pack_things_date(today))
    start_of_today = datetime.combine(today, datetime.min.time(), tzinfo=LOCAL_TZ).timestamp()
    rows = conn.execute(
        f"{_TASK_SELECT} AND {_ACTIVE} AND ({where}) ORDER BY {order}", [start_of_today] + params
    )
    return [_row_to_task(row) for row in rows]


def read_task(conn: sqlite3.Connection, task_id: str) -> Optional[Task]:
    """Return one to-do by id, or None if it does not exist."""
    row = conn.execute(f"{_TASK_SELECT} AND t.uuid = ?", [task_id]).fetchone()
    return _row_to_task(row) if row else None


def read_sequential_projects(conn: sqlite3.Connection) -> Dict[str, List[Task]]:
    """Return {project id: its open to-dos} for every open project tagged Sequential.

    Covers each whole project (not only Today), so the sequence can be worked
    out; to-dos under closed headings are left out.
    """
    sequential = (
        "EXISTS (SELECT 1 FROM TMTaskTag st JOIN TMTag sg ON sg.uuid = st.tags "
        f"WHERE st.tasks = COALESCE(t.project, h.project) AND sg.title = '{SEQUENTIAL_TAG}')"
    )
    open_parents = (
        f"COALESCE(p.status, {STATUS_OPEN}) = {STATUS_OPEN} AND COALESCE(h.status, {STATUS_OPEN}) = {STATUS_OPEN} "
        f"AND COALESCE(hp.status, {STATUS_OPEN}) = {STATUS_OPEN}"
    )
    projects: Dict[str, List[Task]] = {}
    rows = conn.execute(f"{_TASK_SELECT} AND t.status = {STATUS_OPEN} AND {open_parents} AND {sequential}")
    for row in rows:
        task = _row_to_task(row)
        projects.setdefault(task.project_id, []).append(task)
    return projects


def read_last_completed(conn: sqlite3.Connection, project_ids: Iterable[str]) -> Dict[str, str]:
    """Return {project id: its most recently completed to-do} (directly or under a heading)."""
    ids = sorted(set(project_ids))
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    rows = conn.execute(
        "SELECT t.uuid, COALESCE(t.project, h.project) AS project_id FROM TMTask t "
        "LEFT JOIN TMTask h ON h.uuid = t.heading "
        f"WHERE t.type = {TYPE_TODO} AND t.status = {STATUS_COMPLETED} AND t.trashed = 0 "
        f"AND COALESCE(t.project, h.project) IN ({placeholders}) ORDER BY t.stopDate",
        ids,
    )
    return {row["project_id"]: row["uuid"] for row in rows}  # Later rows (newer) overwrite.


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


def missing_priority_tags(conn: sqlite3.Connection) -> List[str]:
    """Return the P tags that do not exist in Things (the URL scheme ignores unknown tags)."""
    existing = {row["title"] for row in conn.execute("SELECT title FROM TMTag")}
    return [p for p in PRIORITIES if p not in existing]


# --- Things URL commands --------------------------------------------------


def is_valid_task_id(task_id: object) -> bool:
    """Return True if `task_id` looks like a Things task id."""
    return isinstance(task_id, str) and bool(TASK_ID_RE.match(task_id))


def build_update_url(change: Change, token: str) -> str:
    """Build the things:///update URL that applies `change`.

    Raises ValueError if a tag contains a comma, because the URL scheme uses
    commas to separate tags and the task's tags would be split incorrectly.
    """
    params = {"id": change.task_id, "auth-token": token}
    if change.tags is not None:
        if any("," in tag for tag in change.tags):
            raise ValueError(f"Tag containing a comma cannot be written: {change.tags!r}")
        params["tags"] = ",".join(change.tags)
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
    return "things:///update?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe=",")


def build_show_url(target_id: str) -> str:
    """Build the things:///show URL that opens a task, or one of THINGS_LISTS, in Things."""
    return "things:///show?" + urllib.parse.urlencode({"id": target_id})


def open_things_url(url: str, background: bool) -> bool:
    """Hand a things:/// URL to macOS. Returns False (and logs) on failure.

    `background` keeps Things from coming to the front (open -g).
    """
    command = ["open", "-g", url] if background else ["open", url]
    try:
        subprocess.run(command, check=True, timeout=10, capture_output=True)
        return True
    except (OSError, subprocess.SubprocessError) as error:
        # Log the command without the URL, which contains the auth token.
        get_logger().error("Could not open Things URL (%s): %s", url.split("?")[0], error)
        return False


def apply_change(change: Change, token: str, db_path: str) -> bool:
    """Send `change` to Things and wait until the database confirms it.

    Returns True only when the re-read task matches the change.
    """
    logger = get_logger()
    try:
        url = build_update_url(change, token)
    except ValueError as error:
        logger.error("Skipped task %s: %s", change.task_id, error)
        return False
    if not open_things_url(url, background=True):
        return False
    deadline = time.monotonic() + CONFIRM_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(CONFIRM_POLL_SECONDS)
        try:
            with open_things_db(db_path) as conn:
                task = read_task(conn, change.task_id)
        except sqlite3.Error as error:
            logger.warning("Could not re-read task %s: %s", change.task_id, error)
            continue
        if task is not None and change.is_satisfied_by(task):
            return True
    logger.error(
        "Things did not confirm the change to task %s (wrong auth token, missing tag, "
        "or Things not running)",
        change.task_id,
    )
    return False


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
    """Load the saved order within each priority; an unreadable file counts as empty."""
    data = _load_json_object(path)
    return {
        p: [i for i in data.get(p, []) if isinstance(i, str)]
        for p in PRIORITIES
        if isinstance(data.get(p), list)
    }


def save_order(order: Dict[str, List[str]], path: str = ORDER_PATH) -> None:
    """Save the order within each priority."""
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
