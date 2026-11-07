"""Priority rules for Do Things.

Pure logic with no I/O, so every rule can be unit-tested without Things.
It decides which priority tag (P1, P2, P3) a task should carry, what changes a
manual move implies, what completing or reopening a task implies, what an
edit from the edit view implies, and how tasks are grouped and ordered for
display.

Version: 0.1.8

Change log:
- v0.1.8 (2026-11-07): Removed `Task.repeating` and `Change.changes_dates`:
  copies of repeating to-dos can have their dates changed by URL after all.
- v0.1.7 (2026-11-07): Tasks carry notes, Someday state, list and heading.
  `TaskEdit` and `plan_edit` turn an edit-view save into one Change (priority
  uses the move rules; an explicit deadline or When wins). Change can also set
  title, notes, When "anytime"/"someday", list and heading, and reports
  `changes_dates`. Tasks flag copies of repeating to-dos (`repeating`).
- v0.1.6 (2026-11-07): Tasks carry `completed_at`. `plan_completion` builds a
  complete/reopen change; `Change.tags` may be None (tags left alone). The
  refresh rules skip completed tasks, and completed tasks sort after open ones
  (oldest completion first) in Today groups and in the searches.
- v0.1.5 (2026-11-07): Synchronized module version metadata.
- v0.1.4 (2026-11-07): Synchronized module version metadata.
- v0.1.3 (2026-11-07): Synchronized module version metadata.
- v0.1.2 (2026-11-07): Synchronized module version metadata.
- v0.1.1 (2026-11-07): Moving a deadline-only Today task out of P1 also sets its start date to today.
- v0.1.0 (2026-11-07): Initial release.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional

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
    """Return the tag change the refresh rules require, or None if compliant.

    Completed tasks are left as they are. Refresh changes never touch the deadline.
    """
    if task.completed:
        return None
    desired = _with_priority(task.tags, required_priority(task, today))
    if set(desired) == set(task.tags):
        return None
    return Change(task_id=task.uuid, tags=desired)


def plan_move(task: Task, destination: str, today: date) -> Change:
    """Return the change for manually moving `task` to `destination`.

    All P tags are replaced by the destination tag. Moving into P1 sets the
    deadline to today; P2 <-> P3 leaves it alone. Moving out of P1 clears the
    deadline, and if the task is in Today only because of its deadline (no
    start date, or one after today) also sets its start date to today, so it
    stays in Today.
    """
    if destination not in PRIORITIES:
        raise ValueError(f"Unknown priority: {destination!r}")
    source = required_priority(task, today)
    change = Change(task_id=task.uuid, tags=_with_priority(task.tags, destination))
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
    what the move rules would set.
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
    elif edit.when_keyword is not None:
        change.set_start_date, change.set_when = None, edit.when_keyword
    change.set_title = edit.title
    change.set_notes = edit.notes
    change.set_list_id = edit.list_id
    change.set_heading_id = edit.heading_id
    if change == Change(task_id=task.uuid, tags=None):
        return None
    return change


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
