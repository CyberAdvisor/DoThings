"""Priority rules for Do Things.

Pure logic with no I/O, so every rule can be unit-tested without Things.
It decides which priority tag (P1, P2, P3) a task should carry, what changes a
manual move implies, what completing or reopening a task implies, what an
edit from the edit view implies, and how tasks are grouped and ordered for
display.

Version: 1.0.2

Change log:
- v1.0.2 (2026-11-07): Synchronized module version metadata.
- v1.0.1 (2026-11-07): Change log trimmed to v1.0.0 and later; earlier history is in git.
- v1.0.0 (2026-11-07): Synchronized module version metadata.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

# Priority tags, highest first. Their order defines "highest priority wins".
PRIORITIES = ("P1", "P2", "P3")

# Display name of each priority group in the Today view.
PRIORITY_LABELS = {"P1": "Due Today", "P2": "To Do", "P3": "Follow Up"}


@dataclass
class Task:
    """An open or completed Things to-do, as read from the Things database."""

    uuid: str
    title: str
    tags: List[str] = field(default_factory=list)
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    context: str = ""  # Project or area title, shown under the task title.
    completed_at: Optional[float] = None  # Unix time it was completed; None while open.
    notes: str = ""
    someday: bool = False  # In Someday (no start date). False with no date means Anytime.
    list_id: Optional[str] = None  # Project (directly or via its heading) or area id.
    heading_id: Optional[str] = None
    project_id: Optional[str] = None  # Project (directly or via its heading); None if not in one.
    # Position in the project's manual order: (0 = no heading / 1 = under a heading,
    # heading position, position within the heading or the project).
    project_rank: Tuple[int, int, int] = (0, 0, 0)
    repeating: bool = False  # A copy of a repeating to-do (shown with a ↻ icon).
    has_checklist: bool = False

    @property
    def completed(self) -> bool:
        """True if the task is completed."""
        return self.completed_at is not None


@dataclass
class Change:
    """A write to send to Things for one task.

    `tags` is the complete tag list the task must end up with (the Things URL
    scheme replaces all tags), or None to leave the tags alone. Deadline
    handling is one of: leave alone, set to `set_deadline`, or clear when
    `clear_deadline` is true. When `set_start_date` is given, the task's start
    date is set to it; `set_when` ("anytime" or "someday") instead removes the
    start date. When `set_completed` is given, the task is completed (True) or
    reopened (False). The remaining `set_*` fields replace that value.
    """

    task_id: str
    tags: Optional[List[str]]
    set_deadline: Optional[date] = None
    clear_deadline: bool = False
    set_start_date: Optional[date] = None
    set_completed: Optional[bool] = None
    set_when: Optional[str] = None  # "anytime" or "someday"
    set_title: Optional[str] = None
    set_notes: Optional[str] = None
    set_list_id: Optional[str] = None
    set_heading_id: Optional[str] = None

    def is_satisfied_by(self, task: Task) -> bool:
        """Return True when `task` (re-read from Things) reflects this change."""
        if self.tags is not None and set(task.tags) != set(self.tags):
            return False
        if self.set_completed is not None and task.completed != self.set_completed:
            return False
        if self.set_deadline is not None and task.deadline != self.set_deadline:
            return False
        if self.clear_deadline and task.deadline is not None:
            return False
        if self.set_start_date is not None and task.start_date != self.set_start_date:
            return False
        if self.set_when is not None and (
            task.start_date is not None or task.someday != (self.set_when == "someday")
        ):
            return False
        if self.set_title is not None and task.title != self.set_title:
            return False
        if self.set_notes is not None and task.notes != self.set_notes:
            return False
        if self.set_list_id is not None and task.list_id != self.set_list_id:
            return False
        if self.set_heading_id is not None and task.heading_id != self.set_heading_id:
            return False
        return True


def priority_tags(tags: Iterable[str]) -> List[str]:
    """Return the priority tags in `tags`, highest priority first."""
    present = set(tags)
    return [p for p in PRIORITIES if p in present]


def current_priority(tags: Iterable[str]) -> Optional[str]:
    """Return the highest priority tag in `tags`, or None if there is none."""
    found = priority_tags(tags)
    return found[0] if found else None


def required_priority(task: Task, today: date) -> str:
    """Return the priority a Today task must carry under the refresh rules.

    Rules, in order: overdue or due today -> P1; otherwise the highest P tag
    it already has; otherwise P2.
    """
    if task.deadline is not None and task.deadline <= today:
        return "P1"
    return current_priority(task.tags) or "P2"


def _with_priority(tags: List[str], priority: str) -> List[str]:
    """Return `tags` with every P tag replaced by the single tag `priority`."""
    return [t for t in tags if t not in PRIORITIES] + [priority]


def plan_refresh(task: Task, today: date) -> Optional[Change]:
    """Return the change the refresh rules require, or None if compliant.

    Fixes the priority tags, and gives a task with no start date (Inbox,
    Anytime or Someday) that is due today or overdue a start date of today,
    so it is in Things' own Today too. Completed tasks are left as they are.
    Refresh changes never touch the deadline.
    """
    if task.completed:
        return None
    desired = _with_priority(task.tags, required_priority(task, today))
    tags_wrong = set(desired) != set(task.tags)
    needs_start = task.start_date is None and task.deadline is not None and task.deadline <= today
    if not tags_wrong and not needs_start:
        return None
    return Change(
        task_id=task.uuid,
        tags=desired if tags_wrong else None,
        set_start_date=today if needs_start else None,
    )


def plan_move(task: Task, destination: str, today: date) -> Change:
    """Return the change for manually moving `task` to `destination`.

    All P tags are replaced by the destination tag; a deadline after today is
    always kept. Moving into P1 sets a missing deadline to today. Moving out of
    P1 clears a deadline of today or earlier (an overdue one would put the task
    straight back in P1), and if the task is in Today only because of that
    deadline (no start date, or one after today) also sets its start date to
    today, so it stays in Today. P2 <-> P3 leaves the deadline alone.
    """
    if destination not in PRIORITIES:
        raise ValueError(f"Unknown priority: {destination!r}")
    source = required_priority(task, today)
    change = Change(task_id=task.uuid, tags=_with_priority(task.tags, destination))
    later_deadline = task.deadline is not None and task.deadline > today
    if later_deadline:
        return change
    if destination == "P1" and source != "P1":
        change.set_deadline = today
    elif source == "P1" and destination != "P1":
        change.clear_deadline = True
        if task.start_date is None or task.start_date > today:
            change.set_start_date = today
    return change


def plan_completion(task: Task, completed: bool) -> Change:
    """Return the change that completes (`completed` True) or reopens `task`.

    Tags and dates are left alone, so a task reopens in the group it was in.
    """
    return Change(task_id=task.uuid, tags=None, set_completed=completed)


# Values a TaskEdit's `when_keyword` may take (no start date).
WHEN_KEYWORDS = ("anytime", "someday")


@dataclass
class TaskEdit:
    """The fields changed in the edit view; None means unchanged.

    For When, set `when_date` or `when_keyword` (not both). For the deadline,
    set `deadline` or `clear_deadline`. `other_tags` is the complete list of
    non-priority tags.
    """

    title: Optional[str] = None
    notes: Optional[str] = None
    when_date: Optional[date] = None
    when_keyword: Optional[str] = None
    deadline: Optional[date] = None
    clear_deadline: bool = False
    priority: Optional[str] = None
    other_tags: Optional[List[str]] = None
    list_id: Optional[str] = None
    heading_id: Optional[str] = None


def plan_edit(task: Task, edit: TaskEdit, today: date) -> Optional[Change]:
    """Return the single Change for an edit-view save, or None if nothing changed.

    A priority change applies the move rules (plan_move), then the explicit
    fields are layered on top: a deadline or When chosen in the edit wins over
    what the move rules would set. Choosing Someday or Anytime clears the
    deadline, and deferring the start to a date after today moves a deadline
    that is before that date to it, unless the edit also sets the deadline.
    """
    if edit.when_keyword is not None and edit.when_keyword not in WHEN_KEYWORDS:
        raise ValueError(f"Unknown When value: {edit.when_keyword!r}")
    if edit.priority is not None and edit.priority != required_priority(task, today):
        change = plan_move(task, edit.priority, today)
    else:
        change = Change(task_id=task.uuid, tags=None)
    if edit.other_tags is not None:
        # Keep the priority tags the move rules chose (or the task's own).
        current = change.tags if change.tags is not None else task.tags
        change.tags = list(edit.other_tags) + priority_tags(current)
    if edit.deadline is not None:
        change.set_deadline, change.clear_deadline = edit.deadline, False
    elif edit.clear_deadline:
        change.set_deadline, change.clear_deadline = None, True
    if edit.when_date is not None:
        change.set_start_date, change.set_when = edit.when_date, None
        deferred = edit.when_date > today
        deadline_before = task.deadline is not None and task.deadline < edit.when_date
        if deferred and deadline_before and edit.deadline is None and not edit.clear_deadline:
            change.set_deadline, change.clear_deadline = edit.when_date, False
    elif edit.when_keyword is not None:
        change.set_start_date, change.set_when = None, edit.when_keyword
        if edit.deadline is None:
            change.set_deadline, change.clear_deadline = None, True
    change.set_title = edit.title
    change.set_notes = edit.notes
    change.set_list_id = edit.list_id
    change.set_heading_id = edit.heading_id
    if change == Change(task_id=task.uuid, tags=None):
        return None
    return change


def in_today(task: Task, today: date) -> bool:
    """Return True if Things lists `task` in Today: started, or due today or overdue."""
    started = task.start_date is not None and task.start_date <= today
    due = task.deadline is not None and task.deadline <= today
    return started or due


def _applied(task: Task, change: Change) -> Task:
    """Return a copy of `task` with the tag, date and text fields of `change` applied."""
    after = replace(task, tags=list(change.tags) if change.tags is not None else list(task.tags))
    if change.set_deadline is not None:
        after.deadline = change.set_deadline
    elif change.clear_deadline:
        after.deadline = None
    if change.set_start_date is not None:
        after.start_date, after.someday = change.set_start_date, False
    elif change.set_when is not None:
        after.start_date, after.someday = None, change.set_when == "someday"
    for name in ("title", "notes", "list_id", "heading_id"):
        value = getattr(change, "set_" + name)
        if value is not None:
            setattr(after, name, value)
    return after


def predict(task: Task, change: Change, today: date) -> Task:
    """Return `task` as it will be once `change` is applied and the next refresh has run.

    Used to show an edit's result before Things confirms it, so the page never
    works out the rules itself. Completion is not predicted (edits don't send it).
    """
    after = _applied(task, change)
    if in_today(after, today):
        refresh = plan_refresh(after, today)  # Only Today tasks get the refresh rules.
        if refresh is not None:
            after = _applied(after, refresh)
    return after


def place_in_list(task: Task, name: str, today: date) -> Optional[str]:
    """Return where `task` appears in the app list `name`, or None if it isn't listed.

    For "today" this is its priority group (P1-P3); for a search, "list".
    Mirrors the list queries in common.py for a task already refreshed.
    """
    if name == "today":
        return required_priority(task, today) if in_today(task, today) else None
    if name in ("p1", "p2", "p3"):
        listed = in_today(task, today) and current_priority(task.tags) == name.upper()
    elif name == "overdue":
        listed = task.deadline is not None and task.deadline < today
    else:
        raise ValueError(f"Unknown list: {name!r}")
    return "list" if listed else None


def deadline_state(deadline: Optional[date], today: date) -> Optional[str]:
    """Classify a deadline as 'overdue', 'today' or 'future' (None if unset)."""
    if deadline is None:
        return None
    if deadline < today:
        return "overdue"
    return "today" if deadline == today else "future"


def apply_order(tasks: List[Task], ids: List[str]) -> List[Task]:
    """Sort `tasks` by the saved id order; unsaved tasks keep their input order after."""
    position = {task_id: i for i, task_id in enumerate(ids)}
    # Python's sort is stable, so tasks with no saved position keep Things' order.
    return sorted(tasks, key=lambda t: position.get(t.uuid, len(position)))


def today_counts(tasks: Iterable[Task], today: date) -> Dict[str, int]:
    """Count open Today tasks for the sidebar, as Things does.

    `due`: open tasks due today or overdue (the red badge). `not_due`: the
    other open tasks (the gray number). Together they are all open tasks.
    """
    open_tasks = [t for t in tasks if not t.completed]
    due = sum(1 for t in open_tasks if t.deadline is not None and t.deadline <= today)
    return {"due": due, "not_due": len(open_tasks) - due}


def in_project_order(tasks: List[Task]) -> List[Task]:
    """Reorder tasks of the same project by the project's manual order.

    Each project's tasks keep the positions they had in the list, but fill
    them in project order; tasks not in a project don't move.
    """
    result = list(tasks)
    positions: Dict[str, List[int]] = {}
    for i, task in enumerate(tasks):
        if task.project_id is not None:
            positions.setdefault(task.project_id, []).append(i)
    for slots in positions.values():
        ordered = sorted((tasks[i] for i in slots), key=lambda t: t.project_rank)
        for slot, task in zip(slots, ordered):
            result[slot] = task
    return result


def is_next_candidate(task: Task, today: date) -> bool:
    """True if `task` can be its sequential project's task in progress.

    That is an open task with no deadline, not in Someday, and with no start
    date or one of today or earlier (so it is, or can be put, in Today).
    Tasks with a deadline or a later start follow their own dates instead.
    """
    if task.completed or task.deadline is not None or task.someday:
        return False
    return task.start_date is None or task.start_date <= today


def sequence_next(project_tasks: Iterable[Task], today: date) -> Optional[Task]:
    """Return a sequential project's task in progress: its first candidate in project order."""
    for task in sorted(project_tasks, key=lambda t: t.project_rank):
        if is_next_candidate(task, today):
            return task
    return None


def sequence_place(project_tasks: Iterable[Task], task_id: str, completed: int) -> Tuple[int, int]:
    """Return (N, M) for a sequential project's "task N of M".

    N is the project's `completed` to-dos plus the task's position among the
    open ones in project order; M is completed plus open. `task_id` must be
    one of `project_tasks`.
    """
    ordered = sorted(project_tasks, key=lambda t: t.project_rank)
    position = next(i for i, t in enumerate(ordered, 1) if t.uuid == task_id)
    return completed + position, completed + len(ordered)


def plan_sequence(project_tasks: Iterable[Task], today: date) -> Optional[Change]:
    """Return the change that puts a sequential project's next task in Today, if needed.

    The task in progress (sequence_next) gets a start date of today when it
    has none. While it is open nothing else is pulled in; once it is done the
    next undated task is.
    """
    task = sequence_next(project_tasks, today)
    if task is None or task.start_date is not None:
        return None
    return Change(task_id=task.uuid, tags=None, set_start_date=today)


def find_pulled(project_tasks: Iterable[Task], task_id: str, started_on: date) -> Optional[Task]:
    """Return the task Do Things started, if it is still open with the start date Do Things gave it.

    None means the record no longer applies: the task was completed, removed,
    or its date was changed since (by the user, so it must be left alone).
    """
    for task in project_tasks:
        if task.uuid == task_id:
            return task if task.start_date == started_on else None
    return None


def plan_sequence_undo(project_tasks: Iterable[Task], pulled: Task, after_id: Optional[str]) -> Optional[Change]:
    """Return the change that puts a task Do Things started back to undated, if needed.

    `after_id` is the task whose completion led Do Things to start `pulled`.
    If that task is open again (it was unchecked), `pulled` goes back to
    Anytime with no start date, without the P tags it got in Today.
    """
    if after_id is None or not any(t.uuid == after_id and not t.completed for t in project_tasks):
        return None
    other_tags = [t for t in pulled.tags if t not in PRIORITIES]
    tags = other_tags if len(other_tags) != len(pulled.tags) else None
    return Change(task_id=pulled.uuid, tags=tags, set_when="anytime")


def completed_last(tasks: List[Task]) -> List[Task]:
    """Return open tasks in their given order, then completed tasks, oldest completion first."""
    open_tasks = [t for t in tasks if not t.completed]
    done = sorted((t for t in tasks if t.completed), key=lambda t: t.completed_at)
    return open_tasks + done


def group_today(
    tasks: List[Task], order: Dict[str, List[str]], today: date
) -> Dict[str, List[Task]]:
    """Group Today tasks by priority: open tasks in the saved order, then completed ones."""
    groups: Dict[str, List[Task]] = {p: [] for p in PRIORITIES}
    for task in tasks:
        groups[required_priority(task, today)].append(task)
    return {p: completed_last(apply_order(groups[p], order.get(p, []))) for p in PRIORITIES}


def prune_order(order: Dict[str, List[str]], keep: Iterable[str]) -> Dict[str, List[str]]:
    """Return the saved order with only the ids in `keep` (the tasks still in Today)."""
    kept = set(keep)
    return {p: [i for i in order.get(p, []) if i in kept] for p in PRIORITIES}


def update_order(
    order: Dict[str, List[str]], priority: str, ids: List[str]
) -> Dict[str, List[str]]:
    """Return a new order with `priority` set to `ids`.

    The ids are removed from every other priority, so a moved task is never
    listed in two groups.
    """
    if priority not in PRIORITIES:
        raise ValueError(f"Unknown priority: {priority!r}")
    moved = set(ids)
    updated = {
        p: [i for i in order.get(p, []) if i not in moved] for p in PRIORITIES if p != priority
    }
    updated[priority] = list(ids)
    return updated
