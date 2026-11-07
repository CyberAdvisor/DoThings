"""Do Things local server.

Serves the Do Things page at http://127.0.0.1:8765 and a small JSON API that
reads Things, applies the priority rules, moves and reorders tasks, opens
tasks in Things, and stores the Things auth token on first run.

If the server is already running, starting it again just opens the page.

Version: 0.1.4

Change log:
- v0.1.4 (2026-11-07): Synchronized module version metadata.
- v0.1.3 (2026-11-07): Synchronized module version metadata.
- v0.1.2 (2026-11-07): Synchronized module version metadata.
- v0.1.1 (2026-11-07): Synchronized module version metadata.
- v0.1.0 (2026-11-07): Initial release.
"""

import argparse
import errno
import json
import sqlite3
import urllib.parse
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from common import (
    BUILTIN_LISTS,
    CUSTOM_SEARCHES,
    INDEX_HTML_PATH,
    PROJECT_VERSION,
    SERVER_HOST,
    SERVER_PORT,
    apply_change,
    build_show_url,
    find_things_db_path,
    get_logger,
    is_valid_task_id,
    load_order,
    load_token,
    missing_priority_tags,
    open_things_db,
    open_things_url,
    read_list,
    read_task,
    save_order,
    save_token,
    today_local,
)
from priority_check import (
    PRIORITIES,
    PRIORITY_LABELS,
    Task,
    deadline_state,
    group_today,
    plan_move,
    plan_refresh,
    update_order,
)

PAGE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/"
# Requests must name this server in the Host header (blocks DNS-rebinding attacks).
ALLOWED_HOSTS = {f"{SERVER_HOST}:{SERVER_PORT}", f"localhost:{SERVER_PORT}"}
# Every POST must carry this header. Other websites open in the browser cannot
# add custom headers to requests sent here, so they cannot trigger writes.
REQUIRED_POST_HEADER = "X-Do-Things"
MAX_BODY_BYTES = 64 * 1024


class ApiError(Exception):
    """An error reported to the page as JSON with an HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def task_to_json(task: Task, today: date) -> Dict[str, Any]:
    """Convert a Task into the JSON shape the page renders."""
    return {
        "id": task.uuid,
        "title": task.title,
        "context": task.context,
        # P tags are shown by grouping, so only other tags are listed.
        "tags": [t for t in task.tags if t not in PRIORITIES],
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "deadline_label": deadline_label(task.deadline, today),
        "deadline_state": deadline_state(task.deadline, today),
        "start_date": task.start_date.isoformat() if task.start_date else None,
    }


def deadline_label(deadline: Optional[date], today: date) -> Optional[str]:
    """Return a short Things-style label for a deadline ('Today', 'Nov 9')."""
    if deadline is None:
        return None
    if deadline == today:
        return "Today"
    label = f"{deadline.strftime('%b')} {deadline.day}"
    return label if deadline.year == today.year else f"{label}, {deadline.year}"


def require_db_path() -> str:
    """Return the Things database path, or raise an ApiError if it is not found."""
    path = find_things_db_path()
    if path is None:
        raise ApiError(503, "Things database not found. Is Things 3 installed?")
    return path


def apply_refresh_rules(db_path: str, token: Optional[str], today: date) -> bool:
    """Apply the refresh rules to every Today task. Returns True if a write failed.

    Stops at the first failed write so a bad token does not stall every refresh.
    """
    if token is None:
        return False
    with open_things_db(db_path) as conn:
        tasks = read_list(conn, "today", today)
    for task in tasks:
        change = plan_refresh(task, today)
        if change is not None and not apply_change(change, token, db_path):
            return True
    return False


def list_response(name: str) -> Dict[str, Any]:
    """Build the JSON for a sidebar list, applying the refresh rules first."""
    if name not in BUILTIN_LISTS + CUSTOM_SEARCHES:
        raise ApiError(404, f"Unknown list: {name}")
    db_path = require_db_path()
    token = load_token()
    today = today_local()
    write_failed = apply_refresh_rules(db_path, token, today)
    with open_things_db(db_path) as conn:
        tasks = read_list(conn, name, today)
        missing = missing_priority_tags(conn)
    response: Dict[str, Any] = {
        "name": name,
        "token_set": token is not None,
        "write_failed": write_failed,
        "missing_tags": missing,
    }
    if name == "today":
        groups = group_today(tasks, load_order(), today)
        response["groups"] = [
            {
                "priority": p,
                "label": PRIORITY_LABELS[p],
                "tasks": [task_to_json(t, today) for t in groups[p]],
            }
            for p in PRIORITIES
        ]
    else:
        response["tasks"] = [task_to_json(t, today) for t in tasks]
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


def move_task(body: Dict[str, Any]) -> Dict[str, Any]:
    """Move a task to another priority, then save the new order once Things confirms."""
    task_id = body.get("id")
    if not is_valid_task_id(task_id):
        raise ApiError(400, "Invalid task id.")
    priority, ids = parse_order(body)
    token = load_token()
    if token is None:
        raise ApiError(409, "The Things auth token is not set.")
    db_path = require_db_path()
    today = today_local()
    with open_things_db(db_path) as conn:
        task = read_task(conn, task_id)
    if task is None:
        raise ApiError(404, "Task not found in Things.")
    if not apply_change(plan_move(task, priority, today), token, db_path):
        # Order is only recorded after Things confirms the move.
        return {"ok": False, "write_failed": True}
    save_order(update_order(load_order(), priority, ids))
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


def set_token(body: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and save the Things auth token."""
    try:
        save_token(body.get("token"))
    except ValueError as error:
        raise ApiError(400, str(error))
    return {"ok": True}


POST_ROUTES = {
    "/api/move": move_task,
    "/api/order": reorder_tasks,
    "/api/open": open_task,
    "/api/token": set_token,
}


class Handler(BaseHTTPRequestHandler):
    """Serves the page and the JSON API to the local browser only."""

    def do_GET(self) -> None:  # noqa: N802 (name required by http.server)
        """Serve the page, the status, or a task list."""
        if not self._host_allowed():
            return
        path, _, query = self.path.partition("?")
        if path == "/":
            self._send_page()
        elif path == "/api/status":
            self._send_json(200, {"version": PROJECT_VERSION, "token_set": load_token() is not None})
        elif path == "/api/list":
            name = urllib.parse.parse_qs(query).get("name", [""])[0]
            self._run(lambda: list_response(name))
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
        """Run an API action and send its result or error as JSON."""
        try:
            self._send_json(200, action())
        except ApiError as error:
            self._send_json(error.status, {"error": error.message})
        except (sqlite3.Error, OSError) as error:
            get_logger().error("Request %s %s failed: %s", self.command, self.path, error)
            self._send_json(500, {"error": "Could not read Things. See errors.log."})

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
