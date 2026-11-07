"""Do Things local server.

Serves the Do Things page at http://127.0.0.1:8765 and a small JSON API that
reads Things, applies the priority rules, moves, reorders, edits, completes
and reopens tasks, opens
tasks and Things' own lists in Things, and stores the Things auth token on
first run.

If the server is already running, starting it again just opens the page.

Version: 1.0.1

Change log:
- v1.0.1 (2026-11-07): Change log trimmed to v1.0.0 and later; earlier history is in git.
- v1.0.0 (2026-11-07): Synchronized module version metadata.
"""

import argparse
import errno
import json
import sqlite3
import urllib.parse
import webbrowser
from dataclasses import replace
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from common import (
    APP_LISTS,
    INDEX_HTML_PATH,
    PROJECT_VERSION,
    Pull,
    SERVER_HOST,
    SERVER_PORT,
    THINGS_LISTS,
    apply_change,
    build_show_url,
    count_completed,
    count_inbox,
    find_things_db_path,
    get_logger,
    is_valid_task_id,
    load_order,
    load_pulls,
    load_token,
    missing_priority_tags,
    open_things_db,
    open_things_url,
    read_checklist_progress,
    read_edit_options,
    read_last_completed,
    read_list,
    read_sequential_projects,
    read_task,
    save_order,
    save_pulls,
    save_token,
    today_local,
)
from priority_check import (
    PRIORITIES,
    PRIORITY_LABELS,
    WHEN_KEYWORDS,
    Change,
    Task,
    TaskEdit,
    completed_last,
    deadline_state,
    find_pulled,
    group_today,
    in_project_order,
    plan_completion,
    plan_edit,
    plan_move,
    plan_refresh,
    plan_sequence,
    plan_sequence_undo,
    place_in_list,
    predict,
    prune_order,
    required_priority,
    sequence_place,
    today_counts,
    update_order,
)

PAGE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/"
# Requests must name this server in the Host header (blocks DNS-rebinding attacks).
ALLOWED_HOSTS = {f"{SERVER_HOST}:{SERVER_PORT}", f"localhost:{SERVER_PORT}"}
# Every POST must carry this header. Other websites open in the browser cannot
# add custom headers to requests sent here, so they cannot trigger writes.
REQUIRED_POST_HEADER = "X-Do-Things"
MAX_BODY_BYTES = 64 * 1024
MAX_TITLE_CHARS = 1000
MAX_NOTES_CHARS = 20000
# Lists whose rows show the P1-P3 tags; elsewhere the list itself shows the priority.
PRIORITY_TAG_LISTS = ("overdue",)
# Fields the edit view may change, all optional in a POST /api/edit "changes" object.
EDIT_FIELDS = {"title", "notes", "when", "deadline", "priority", "tags", "list_id", "heading_id"}


class RefreshPause:
    """Whether automatic refresh writes are paused.

    Set when a refresh write isn't confirmed, so a broken setup (URLs off,
    wrong token) isn't retried and logged every 60 seconds. Cleared by Retry
    on the page, a new token, or restarting the server.
    """

    paused = False


class ApiError(Exception):
    """An error reported to the page as JSON with an HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def task_to_json(
    task: Task, today: date, show_priority_tags: bool = True, sequence: Optional[str] = None
) -> Dict[str, Any]:
    """Convert a Task into the JSON shape the page renders, mirroring a Things row.

    Without `show_priority_tags` the P tags are left out: in Today's groups
    and the P1-P3 searches the priority is already shown by the list itself.
    `sequence` ("task 2 of 5") marks a task a sequential project started; the
    page shows it after the project name.
    """
    tags = task.tags if show_priority_tags else [t for t in task.tags if t not in PRIORITIES]
    return {
        "id": task.uuid,
        "title": task.title,
        "context": task.context,
        "sequence": sequence,
        "tags": tags,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "deadline_label": deadline_label(task.deadline, today),
        "deadline_state": deadline_state(task.deadline, today),
        "start_date": task.start_date.isoformat() if task.start_date else None,
        "start_label": start_label(task.start_date, today),
        "has_notes": bool(task.notes.strip()),
        "has_checklist": task.has_checklist,
        "repeating": task.repeating,
        "completed": task.completed,
    }


def _plural(count: int, word: str) -> str:
    """Return e.g. '1 day' or '3 days'."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def deadline_label(deadline: Optional[date], today: date) -> Optional[str]:
    """Return the deadline as Things words it: '1 day ago', 'today' or '2 days left'."""
    if deadline is None:
        return None
    days = (deadline - today).days
    if days == 0:
        return "today"
    if days < 0:
        return f"{_plural(-days, 'day')} ago"
    return f"{_plural(days, 'day')} left"


def start_label(start: Optional[date], today: date) -> Optional[str]:
    """Return the badge Things shows for a later start: 'Mon' within a week, else 'Nov 14'.

    None for no start date or one of today or earlier (the task is in Today).
    """
    if start is None or start <= today:
        return None
    if (start - today).days < 7:
        return start.strftime("%a")
    label = f"{start.strftime('%b')} {start.day}"
    return label if start.year == today.year else f"{label}, {start.year}"


def require_db_path() -> str:
    """Return the Things database path, or raise an ApiError if it is not found."""
    path = find_things_db_path()
    if path is None:
        raise ApiError(503, "Things database not found. Is Things 3 installed?")
    return path


def apply_refresh_rules(
    db_path: str, token: Optional[str], today: date, missing_tags: List[str]
) -> bool:
    """Apply the refresh rules. Returns True if a write failed.

    First the sequential projects are stepped (step_sequences), then every
    Today task, including any just started, gets the Today rules (plan_refresh). Skipped while any P tag is missing in Things:
    Things silently ignores unknown tags, so the write could never be
    confirmed and would look like a token problem. Stops at the first failed
    write so a bad token does not stall every refresh.
    """
    if token is None or missing_tags:
        return False
    if step_sequences(db_path, token, today):
        return True
    with open_things_db(db_path) as conn:
        tasks = read_list(conn, "today", today)
    for task in tasks:
        change = plan_refresh(task, today)
        if change is not None and not apply_change(change, token, db_path):
            return True
    return False


def step_sequences(db_path: str, token: str, today: date) -> bool:
    """Start or undo the next task of each sequential project. Returns True if a write failed.

    Each started task is recorded (sequence_pulls.json) with the date given
    and the task whose completion led to it, so only tasks Do Things started
    are ever put back to undated. While a recorded task is open with that
    date it is the one in progress and nothing else is started. If the task
    it followed is open again (unchecked), it returns to Anytime
    (plan_sequence_undo) and the reopened task is recorded as in progress
    instead; Things moves a reopened task to the bottom of the project, so
    position can't be relied on. With no task in progress, the next undated
    task is started (plan_sequence). Records that no longer apply are dropped.
    """
    with open_things_db(db_path) as conn:
        projects = read_sequential_projects(conn)
        last_done = read_last_completed(conn, projects)
    pulls = load_pulls()
    kept = {p: pulls[p] for p in pulls if p in projects}  # Drop projects no longer sequential or open.
    for project, tasks in projects.items():
        record = kept.get(project)
        pulled = find_pulled(tasks, record.task, record.started_on) if record else None
        if pulled is None:
            kept.pop(project, None)
            start = plan_sequence(tasks, today)
            if start is not None:
                if not apply_change(start, token, db_path):
                    return save_and_fail(kept, pulls)
                kept[project] = Pull(start.task_id, today, last_done.get(project))
            continue
        undo = plan_sequence_undo(tasks, pulled, record.after)
        if undo is None:
            continue  # The recorded task is in progress.
        if not apply_change(undo, token, db_path):
            return save_and_fail(kept, pulls)
        reopened = next(t for t in tasks if t.uuid == record.after)
        if reopened.start_date is not None:
            kept[project] = Pull(reopened.uuid, reopened.start_date, None)
        else:
            del kept[project]
    if kept != pulls:
        save_pulls(kept)
    return False


def save_and_fail(kept: Dict[str, Pull], pulls: Dict[str, Pull]) -> bool:
    """Save the records changed so far after a failed write, and report the failure."""
    if kept != pulls:
        save_pulls(kept)
    return True


def sequence_labels(conn: sqlite3.Connection) -> Dict[str, str]:
    """Return {task id: "task N of M"} for each task a sequential project started.

    Only tasks still open with the start date Do Things gave them count
    (find_pulled). N and M come from sequence_place.
    """
    projects = read_sequential_projects(conn)
    done = count_completed(conn, projects)
    labels = {}
    for project, record in load_pulls().items():
        tasks = projects.get(project, [])
        if find_pulled(tasks, record.task, record.started_on) is not None:
            place, total = sequence_place(tasks, record.task, done.get(project, 0))
            labels[record.task] = f"task {place} of {total}"
    return labels


def read_today(conn: sqlite3.Connection, today: date) -> List[Task]:
    """Read Today as Do Things shows it: tasks of the same project in the project's manual order."""
    return in_project_order(read_list(conn, "today", today))


def list_response(name: str, hide_completed: bool = False) -> Dict[str, Any]:
    """Build the JSON for Today or a search, applying the refresh rules first.

    With `hide_completed`, tasks completed today are left out. Every response
    also carries the sidebar counts, so they stay current.
    """
    if name not in APP_LISTS:
        raise ApiError(404, f"Unknown list: {name}")
    db_path = require_db_path()
    token = load_token()
    today = today_local()
    with open_things_db(db_path) as conn:
        missing = missing_priority_tags(conn)
    if not RefreshPause.paused and apply_refresh_rules(db_path, token, today, missing):
        RefreshPause.paused = True
        get_logger().error("Automatic updates paused until Retry: Things didn't confirm a change.")
    with open_things_db(db_path) as conn:
        today_tasks = read_today(conn, today)
        tasks = today_tasks if name == "today" else read_list(conn, name, today)
        counts = {"inbox": count_inbox(conn), "today": today_counts(today_tasks, today)}
        labels = sequence_labels(conn)
    order = load_order()
    kept = prune_order(order, [t.uuid for t in today_tasks])  # Forget tasks that left Today.
    if kept != {p: order.get(p, []) for p in PRIORITIES}:
        save_order(kept)
    if hide_completed:
        tasks = [t for t in tasks if not t.completed]
    response: Dict[str, Any] = {
        "name": name,
        "token_set": token is not None,
        "refresh_paused": RefreshPause.paused,
        "missing_tags": missing,
        "counts": counts,
    }
    if name == "today":
        groups = group_today(tasks, kept, today)
        response["groups"] = [
            {
                "priority": p,
                "label": PRIORITY_LABELS[p],
                "tasks": [
                    task_to_json(t, today, show_priority_tags=False, sequence=labels.get(t.uuid))
                    for t in groups[p]
                ],
            }
            for p in PRIORITIES
        ]
    else:
        # Only Overdue mixes priorities, so only it shows the P tags.
        shown = name in PRIORITY_TAG_LISTS
        response["tasks"] = [
            task_to_json(t, today, show_priority_tags=shown, sequence=labels.get(t.uuid))
            for t in completed_last(tasks)
        ]
    return response


def parse_order(body: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Validate and return the priority and id list from a move/order request."""
    priority = body.get("priority")
    ids = body.get("order")
    if priority not in PRIORITIES:
        raise ApiError(400, "Unknown priority.")
    if not isinstance(ids, list) or not all(is_valid_task_id(i) for i in ids):
        raise ApiError(400, "Invalid task order.")
    return priority, ids


def load_task_for_write(task_id: object) -> Tuple[Task, str, str, List[str]]:
    """Check a write request and return (task, token, db_path, missing P tags).

    Raises an ApiError for a missing token, a bad id or an unknown task.
    """
    token = load_token()
    if token is None:
        raise ApiError(409, "The Things auth token is not set.")
    task, db_path, missing = load_task(task_id)
    return task, token, db_path, missing


def load_task(task_id: object) -> Tuple[Task, str, List[str]]:
    """Return (task, db_path, missing P tags) for a request naming a task.

    Raises an ApiError for a bad id or an unknown task.
    """
    if not is_valid_task_id(task_id):
        raise ApiError(400, "Invalid task id.")
    db_path = require_db_path()
    with open_things_db(db_path) as conn:
        task = read_task(conn, task_id)
        missing = missing_priority_tags(conn)
    if task is None:
        raise ApiError(404, "Task not found in Things.")
    return task, db_path, missing


def move_task(body: Dict[str, Any]) -> Dict[str, Any]:
    """Move a task to another priority, then save the new order once Things confirms."""
    priority, ids = parse_order(body)
    task, token, db_path, missing = load_task_for_write(body.get("id"))
    if task.completed:
        raise ApiError(409, "Uncheck the task before moving it.")
    if priority in missing:
        # Things would silently drop the unknown tag, so the move could never be confirmed.
        raise ApiError(409, f"Create the {priority} tag in Things first (Window › Tags), then try again.")
    if not apply_change(plan_move(task, priority, today_local()), token, db_path):
        # Order is only recorded after Things confirms the move.
        return {"ok": False, "write_failed": True}
    save_order(update_order(load_order(), priority, ids))
    return {"ok": True}


def complete_task(body: Dict[str, Any]) -> Dict[str, Any]:
    """Complete (`completed` true) or reopen a task in Things.

    Needs no P tags, so it works even while a priority tag is missing.
    """
    completed = body.get("completed")
    if not isinstance(completed, bool):
        raise ApiError(400, "`completed` must be true or false.")
    task, token, db_path, _ = load_task_for_write(body.get("id"))
    if task.completed == completed:
        return {"ok": True}  # Already in the requested state.
    if not apply_change(plan_completion(task, completed), token, db_path):
        return {"ok": False, "write_failed": True}
    return {"ok": True}


def when_json(task: Task, today: date) -> Dict[str, Optional[str]]:
    """Describe a task's When for the edit view: kind today/date/anytime/someday, plus the date."""
    if task.someday:
        return {"kind": "someday", "date": None}
    if task.start_date is None:
        return {"kind": "anytime", "date": None}
    kind = "today" if task.start_date <= today else "date"
    return {"kind": kind, "date": task.start_date.isoformat()}


def task_detail(task_id: object) -> Dict[str, Any]:
    """Return one task for the edit view, with the choices for its fields."""
    if not is_valid_task_id(task_id):
        raise ApiError(400, "Invalid task id.")
    today = today_local()
    with open_things_db(require_db_path()) as conn:
        task = read_task(conn, task_id)
        options = read_edit_options(conn)
        checklist = read_checklist_progress(conn, task_id)
    if task is None:
        raise ApiError(404, "Task not found in Things.")
    detail = task_to_json(task, today)
    detail.update(
        other_tags=[t for t in task.tags if t not in PRIORITIES],  # The editor shows priority separately.
        notes=task.notes,
        when=when_json(task, today),
        priority=required_priority(task, today),
        list_id=task.list_id,
        heading_id=task.heading_id,
        checklist=checklist,
    )
    return {"task": detail, "options": options, "today": today.isoformat()}


def _parse_date(value: object, field: str) -> date:
    """Parse a YYYY-MM-DD string or raise an ApiError naming the field."""
    message = f"{field} must be a date (YYYY-MM-DD)."
    if not isinstance(value, str):
        raise ApiError(400, message)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(400, message)


def parse_edit(changes: object, task: Task, options: Dict[str, list], today: date) -> TaskEdit:
    """Validate the edit view's changes and return them as a TaskEdit.

    Everything is checked against Things' own data (existing tags, open
    projects and areas, headings of the chosen project), so only values Things
    can apply are sent.
    """
    if not isinstance(changes, dict) or not set(changes) <= EDIT_FIELDS:
        raise ApiError(400, "Invalid changes.")
    edit = TaskEdit()
    if "title" in changes:
        title = changes["title"]
        if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE_CHARS or "\n" in title:
            raise ApiError(400, "The title must be one line of text and can't be empty.")
        edit.title = title.strip()
    if "notes" in changes:
        if not isinstance(changes["notes"], str) or len(changes["notes"]) > MAX_NOTES_CHARS:
            raise ApiError(400, "Notes are too long.")
        edit.notes = changes["notes"]
    if "when" in changes:
        when = changes["when"]
        if when == "today":
            edit.when_date = today
        elif when in WHEN_KEYWORDS:
            edit.when_keyword = when
        else:
            edit.when_date = _parse_date(when, "When")
    if "deadline" in changes:
        if changes["deadline"] == "":
            edit.clear_deadline = True
        else:
            edit.deadline = _parse_date(changes["deadline"], "Deadline")
    if "priority" in changes:
        if changes["priority"] not in PRIORITIES:
            raise ApiError(400, "Unknown priority.")
        edit.priority = changes["priority"]
    if "tags" in changes:
        tags = changes["tags"]
        if not isinstance(tags, list) or not all(t in options["tags"] for t in tags):
            raise ApiError(400, "Tags must be existing Things tags.")
        if any("," in t for t in tags):
            raise ApiError(400, "Tags containing a comma can't be set from Do Things.")
        edit.other_tags = list(dict.fromkeys(tags))  # Drop duplicates, keep order.
    list_ids = {a["id"] for a in options["areas"]} | {p["id"] for p in options["projects"]}
    if "list_id" in changes:
        if changes["list_id"] not in list_ids:
            raise ApiError(400, "Unknown project or area.")
        edit.list_id = changes["list_id"]
    if "heading_id" in changes:
        project = edit.list_id or task.list_id
        headings = {h["id"] for h in options["headings"] if h["project"] == project}
        if changes["heading_id"] not in headings:
            raise ApiError(400, "That heading isn't in the chosen project.")
        edit.heading_id = changes["heading_id"]
    return edit


def plan_edit_request(
    body: Dict[str, Any], task: Task, db_path: str, today: date
) -> Tuple[Optional[Change], Dict[str, list]]:
    """Validate an edit request for `task` and return (the planned change, the edit options)."""
    if task.completed:
        raise ApiError(409, "Uncheck the task before editing it.")
    with open_things_db(db_path) as conn:
        options = read_edit_options(conn)
    return plan_edit(task, parse_edit(body.get("changes"), task, options, today), today), options


def preview_edit(body: Dict[str, Any]) -> Dict[str, Any]:
    """Show what an edit would do, without writing anything.

    Returns the When, deadline and priority the save would end up with (after
    the edit and refresh rules), the task's row as it will look, and where it
    will appear in the list `list` the page is showing ("P1"-"P3" in Today,
    "list" in a search, None if it leaves the list). The page shows these
    instead of working out the rules itself.
    """
    name = body.get("list")
    if name not in APP_LISTS:
        raise ApiError(400, "Unknown list.")
    task, db_path, _ = load_task(body.get("id"))
    today = today_local()
    change, options = plan_edit_request(body, task, db_path, today)
    after = task if change is None else predict(task, change, today)
    if change is not None and change.set_list_id is not None:
        titles = {item["id"]: item["title"] for item in options["areas"] + options["projects"]}
        after = replace(after, context=titles[change.set_list_id])
    sequence = None
    if after.start_date == task.start_date and after.list_id == task.list_id:
        # Still the started task of its sequential project (changing its date ends that).
        with open_things_db(db_path) as conn:
            sequence = sequence_labels(conn).get(task.uuid)
    return {
        "when": when_json(after, today),
        "deadline": after.deadline.isoformat() if after.deadline else None,
        "priority": required_priority(after, today),
        "row": task_to_json(after, today, show_priority_tags=name in PRIORITY_TAG_LISTS, sequence=sequence),
        "place": place_in_list(after, name, today),
    }


def edit_task(body: Dict[str, Any]) -> Dict[str, Any]:
    """Apply an edit-view save to Things as one confirmed update."""
    task, token, db_path, missing = load_task_for_write(body.get("id"))
    today = today_local()
    change, _ = plan_edit_request(body, task, db_path, today)
    if change is None:
        return {"ok": True}  # Nothing changed.
    blocked = [p for p in missing if change.tags is not None and p in change.tags]
    if blocked:
        # Things would silently drop the unknown tag, so the edit could never be confirmed.
        raise ApiError(409, f"Create the {blocked[0]} tag in Things first (Window › Tags), then try again.")
    if not apply_change(change, token, db_path):
        return {"ok": False, "write_failed": True}
    new_priority = body["changes"].get("priority")
    if new_priority and new_priority != required_priority(task, today):
        # Put the task at the end of its new group, as a drag to the bottom would.
        order = load_order()
        ids = [i for i in order.get(new_priority, []) if i != task.uuid] + [task.uuid]
        save_order(update_order(order, new_priority, ids))
    return {"ok": True}


def reorder_tasks(body: Dict[str, Any]) -> Dict[str, Any]:
    """Save a new order within one priority (no change in Things)."""
    priority, ids = parse_order(body)
    save_order(update_order(load_order(), priority, ids))
    return {"ok": True}


def open_task(body: Dict[str, Any]) -> Dict[str, Any]:
    """Open a task in Things for editing."""
    task_id = body.get("id")
    if not is_valid_task_id(task_id):
        raise ApiError(400, "Invalid task id.")
    return {"ok": open_things_url(build_show_url(task_id), background=False)}


def show_list(body: Dict[str, Any]) -> Dict[str, Any]:
    """Open one of Things' own lists (Inbox, Upcoming, ...) in Things."""
    name = body.get("name")
    if name not in THINGS_LISTS:
        raise ApiError(400, "Unknown Things list.")
    return {"ok": open_things_url(build_show_url(name), background=False)}


def set_token(body: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and save the Things auth token."""
    try:
        save_token(body.get("token"))
    except ValueError as error:
        raise ApiError(400, str(error))
    RefreshPause.paused = False  # A new token may be the fix; try automatic updates again.
    return {"ok": True}


def retry_refresh(body: Dict[str, Any]) -> Dict[str, Any]:
    """Resume automatic updates; the page's next list request tries them again.

    `body` is unused: every POST route takes the request body.
    """
    RefreshPause.paused = False
    return {"ok": True}


POST_ROUTES = {
    "/api/move": move_task,
    "/api/complete": complete_task,
    "/api/edit": edit_task,
    "/api/edit/preview": preview_edit,
    "/api/refresh/retry": retry_refresh,
    "/api/order": reorder_tasks,
    "/api/open": open_task,
    "/api/show-list": show_list,
    "/api/token": set_token,
}


class Handler(BaseHTTPRequestHandler):
    """Serves the page and the JSON API to the local browser only."""

    def handle(self) -> None:
        """Handle a request, ignoring a browser that disconnects before the reply.

        The page drops requests when it reloads or loses focus mid-request; that
        is normal and not an error worth a traceback or an errors.log entry.
        """
        try:
            super().handle()
        except ConnectionError:
            pass

    def do_GET(self) -> None:  # noqa: N802 (name required by http.server)
        """Serve the page, the status, a task list, or one task for editing."""
        if not self._host_allowed():
            return
        path, _, query = self.path.partition("?")
        if path == "/":
            self._send_page()
        elif path == "/api/status":
            self._send_json(200, {"version": PROJECT_VERSION, "token_set": load_token() is not None})
        elif path == "/api/list":
            params = urllib.parse.parse_qs(query)
            name = params.get("name", [""])[0]
            hide_completed = params.get("hide_completed", [""])[0] == "1"
            self._run(lambda: list_response(name, hide_completed))
        elif path == "/api/task":
            task_id = urllib.parse.parse_qs(query).get("id", [""])[0]
            self._run(lambda: task_detail(task_id))
        else:
            self._send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:  # noqa: N802 (name required by http.server)
        """Run a write action after checking the request came from the Do Things page."""
        if not self._host_allowed():
            return
        route = POST_ROUTES.get(self.path)
        if route is None:
            self._send_json(404, {"error": "Not found."})
            return
        if self.headers.get(REQUIRED_POST_HEADER) != "1":
            self._send_json(403, {"error": "Forbidden."})
            return
        self._run(lambda: route(self._read_json_body()))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence per-request logging; errors go to errors.log instead."""

    def _host_allowed(self) -> bool:
        """Reject requests whose Host header is not this server."""
        if self.headers.get("Host") in ALLOWED_HOSTS:
            return True
        self._send_json(403, {"error": "Forbidden."})
        return False

    def _read_json_body(self) -> Dict[str, Any]:
        """Read and parse the JSON request body."""
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "Request too large.")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise ApiError(400, "Invalid JSON.")
        if not isinstance(body, dict):
            raise ApiError(400, "Invalid JSON.")
        return body

    def _run(self, action: Callable[[], Dict[str, Any]]) -> None:
        """Run an API action and send its result or error as JSON.

        The reply is sent outside the try block so that a browser disconnecting
        during the send is not mistaken for a failure to read Things.
        """
        try:
            status, payload = 200, action()
        except ApiError as error:
            status, payload = error.status, {"error": error.message}
        except (sqlite3.Error, OSError) as error:
            get_logger().error("Request %s %s failed: %s", self.command, self.path, error)
            status, payload = 500, {"error": "Could not read Things. See errors.log."}
        self._send_json(status, payload)

    def _send_page(self) -> None:
        """Send index.html."""
        with open(INDEX_HTML_PATH, "rb") as handle:
            body = handle.read()
        self._send(200, "text/html; charset=utf-8", body)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        """Send a JSON response."""
        self._send(status, "application/json", json.dumps(payload).encode("utf-8"))

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        """Send a response with no caching."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def run() -> None:
    """Start the server and open the page; if already running, just open the page."""
    parser = argparse.ArgumentParser(description="Run the Do Things local server.")
    parser.add_argument("--no-browser", action="store_true", help="do not open the page")
    args = parser.parse_args()
    try:
        # A single-threaded server handles one request at a time, so two
        # writes to Things or to the order file can never overlap.
        server = HTTPServer((SERVER_HOST, SERVER_PORT), Handler)
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        print(f"Do Things v{PROJECT_VERSION} already running at {PAGE_URL}")
        if not args.no_browser:
            webbrowser.open(PAGE_URL)
        return
    print(f"Do Things v{PROJECT_VERSION} serving at {PAGE_URL}", flush=True)
    if not args.no_browser:
        webbrowser.open(PAGE_URL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print(f"Do Things v{PROJECT_VERSION} complete: server stopped")


if __name__ == "__main__":
    run()
