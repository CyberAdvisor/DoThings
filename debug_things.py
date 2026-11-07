"""Read-only diagnostic for Do Things.

Prints where the Things database is, whether the columns Do Things relies on
exist, whether the P1-P3 tags exist, and every Today task with its tags,
dates, completion, project order, required priority and the change the refresh rules
would make, plus each sequential project's task in progress.
It never writes to Things or to any Do Things file.

Version: 0.1.26

Change log:
- v0.1.26 (2026-11-07): Synchronized module version metadata.
- v0.1.25 (2026-11-07): Synchronized module version metadata.
- v0.1.24 (2026-11-07): Synchronized module version metadata.
- v0.1.23 (2026-11-07): Synchronized module version metadata.
- v0.1.22 (2026-11-07): Synchronized module version metadata.
- v0.1.21 (2026-11-07): Synchronized module version metadata.
- v0.1.20 (2026-11-07): Synchronized module version metadata.
- v0.1.19 (2026-11-07): Schema check requires `rt1_repeatingTemplate` again
  (used for the repeating icon).
- v0.1.18 (2026-11-07): Sequential projects also show Do Things' record (the
  task it started and the one it followed), which decides what is in progress.
- v0.1.17 (2026-11-07): Synchronized module version metadata.
- v0.1.16 (2026-11-07): Lists each sequential project's task in progress and
  whether the refresh would give it a start date of today (no more hiding).
- v0.1.15 (2026-11-07): Each task also shows its project position and, for
  sequential projects, whether Today hides it (not next in the sequence).
- v0.1.14 (2026-11-07): Synchronized module version metadata.
- v0.1.13 (2026-11-07): Synchronized module version metadata.
- v0.1.12 (2026-11-07): Synchronized module version metadata.
- v0.1.11 (2026-11-07): Synchronized module version metadata.
- v0.1.10 (2026-11-07): Schema check also requires TMChecklistItem (task, status).
- v0.1.9 (2026-11-07): The planned change also shows a start date being set.
- v0.1.8 (2026-11-07): Schema check no longer requires `rt1_repeatingTemplate`.
- v0.1.7 (2026-11-07): Schema check also requires the `notes` and
  `rt1_repeatingTemplate` columns used by the edit view.
- v0.1.6 (2026-11-07): Today now includes tasks completed today; each is
  printed with `completed=`.
- v0.1.5 (2026-11-07): Synchronized module version metadata.
- v0.1.4 (2026-11-07): Synchronized module version metadata.
- v0.1.3 (2026-11-07): Synchronized module version metadata.
- v0.1.2 (2026-11-07): Synchronized module version metadata.
- v0.1.1 (2026-11-07): Synchronized module version metadata.
- v0.1.0 (2026-11-07): Initial release.
"""

import sqlite3

from common import (
    PROJECT_VERSION,
    find_things_db_path,
    load_pulls,
    missing_priority_tags,
    open_things_db,
    read_list,
    read_sequential_projects,
    today_local,
)
from priority_check import Change, find_pulled, plan_refresh, plan_sequence, required_priority, sequence_next

# Columns the queries in common.py depend on.
REQUIRED_COLUMNS = {
    "TMTask": (
        "uuid", "title", "type", "status", "trashed", "start", "startDate", "deadline",
        "todayIndex", "index", "project", "heading", "area", "stopDate", "rt1_recurrenceRule",
        "notes", "rt1_repeatingTemplate",
    ),
    "TMTag": ("uuid", "title"),
    "TMTaskTag": ("tasks", "tags"),
    "TMArea": ("uuid", "title"),
    "TMChecklistItem": ("task", "status"),
}


def check_schema(conn: sqlite3.Connection) -> bool:
    """Print any missing tables or columns; return True if the schema is usable."""
    usable = True
    for table, columns in REQUIRED_COLUMNS.items():
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        missing = [c for c in columns if c not in present]
        if not present:
            print(f"  MISSING TABLE {table}")
            usable = False
        elif missing:
            print(f"  {table} missing columns: {', '.join(missing)}")
            usable = False
    if usable:
        print("  Schema OK")
    return usable


def describe_change(change: Change) -> str:
    """Describe what a refresh change would do, e.g. "retag -> P1; start -> 2026-11-07"."""
    parts = []
    if change.tags is not None:
        parts.append(f"retag -> {', '.join(change.tags)}")
    if change.set_start_date is not None:
        parts.append(f"start -> {change.set_start_date.isoformat()}")
    return "; ".join(parts)


def run() -> None:
    """Print the diagnostic report."""
    print(f"Do Things v{PROJECT_VERSION} diagnostic")
    db_path = find_things_db_path()
    if db_path is None:
        print("Things database not found.")
        return
    print(f"Database: {db_path}")
    today = today_local()
    print(f"Today (Mountain Time): {today.isoformat()}")
    with open_things_db(db_path) as conn:
        if not check_schema(conn):
            return
        missing = missing_priority_tags(conn)
        print(f"Priority tags missing in Things: {', '.join(missing) if missing else 'none'}")
        tasks = read_list(conn, "today", today)
        projects = read_sequential_projects(conn)
    pulls = load_pulls()
    print(f"\nSequential projects: {len(projects)}")
    for project, project_tasks in projects.items():
        record = pulls.get(project)
        recorded = find_pulled(project_tasks, record.task, record.started_on) if record else None
        if recorded is not None:
            # The refresh treats the recorded task as in progress (see serve.step_sequences).
            state = f"in progress (recorded, after {record.after or 'none'}): {recorded.title!r}"
        else:
            current = sequence_next(project_tasks, today)
            planned = describe_change(plan_sequence(project_tasks, today) or Change("", None))
            state = f"next by order: {current.title if current else 'none'!r}; planned={planned or 'no change'}"
        print(f"- {project_tasks[0].context!r}: {len(project_tasks)} open; {state}")
    print(f"\nToday tasks: {len(tasks)}")
    for task in tasks:
        change = plan_refresh(task, today)
        planned = describe_change(change) if change else "no change"
        print(
            f"- {task.title!r} [{task.uuid}]\n"
            f"    tags={task.tags} start={task.start_date} deadline={task.deadline} "
            f"context={task.context!r} completed={task.completed}\n"
            f"    project_rank={task.project_rank}\n"
            f"    required={required_priority(task, today)} planned={planned}"
        )
    print(f"\nDo Things v{PROJECT_VERSION} complete: diagnostic finished")


if __name__ == "__main__":
    run()
