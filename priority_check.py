"""Priority rules for Do Things.

Pure logic with no I/O, so every rule can be unit-tested without Things.
It decides which priority tag (P1, P2, P3) a task should carry, what changes a
manual move implies, and how tasks are grouped and ordered for display.

Version: 0.1.2

Change log:
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
    """An open or logged Things to-do, as read from the Things database."""

    uuid: str
    title: str
    tags: List[str] = field(default_factory=list)
    start_date: Optional[date] = None
    deadline: Optional[date] = None
    context: str = ""  # Project or area title, shown under the task title.


@dataclass
class Change:
    """A write to send to Things for one task.

    `tags` is the complete tag list the task must end up with (the Things URL
    scheme replaces all tags). Deadline handling is one of: leave alone,
    set to `set_deadline`, or clear when `clear_deadline` is true. When
    `set_start_date` is given, the task's start date is set to it.
    """

    task_id: str
    tags: List[str]
    set_deadline: Optional[date] = None
    clear_deadline: bool = False
    set_start_date: Optional[date] = None

    def is_satisfied_by(self, task: Task) -> bool:
        """Return True when `task` (re-read from Things) reflects this change."""
        if set(task.tags) != set(self.tags):
            return False
        if self.set_deadline is not None and task.deadline != self.set_deadline:
            return False
        if self.clear_deadline and task.deadline is not None:
            return False
        if self.set_start_date is not None and task.start_date != self.set_start_date:
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

    Refresh changes never touch the deadline.
    """
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


def group_today(
    tasks: List[Task], order: Dict[str, List[str]], today: date
) -> Dict[str, List[Task]]:
    """Group Today tasks by priority, each group sorted by the saved order."""
    groups: Dict[str, List[Task]] = {p: [] for p in PRIORITIES}
    for task in tasks:
        groups[required_priority(task, today)].append(task)
    return {p: apply_order(groups[p], order.get(p, [])) for p in PRIORITIES}


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
