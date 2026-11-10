"""Today's views for Do Things: by priority, by project, or all in one list.

Pure logic with no I/O, so every rule can be unit-tested without Things. It
groups Today's tasks for the view the user picked, applies the order saved by
dragging in that view, lists the tags for the tag bar and filters by the
chosen tag, says where a task appears in a view (the edit preview), and works
out a group's full order after a drop seen through the tag filter.

Version: 2.0.1

Change log:
- v2.0.1 (2026-11-10): Project view headers show only the project or area
  name (no gray "Project", "Area" or area name after it).
- v2.0.0 (2026-11-10): New. Priority, Project and All views of Today and the
  tag bar.
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional

from priority_check import (
    ALL_ORDER_KEY,
    DEFAULT_SETTINGS,
    PRIORITIES,
    PROJECT_ORDER_PREFIX,
    Settings,
    Task,
    apply_order,
    completed_last,
    group_today,
    in_today,
    required_priority,
)

VIEW_PRIORITY, VIEW_PROJECT, VIEW_ALL = "priority", "project", "all"
VIEWS = (VIEW_PRIORITY, VIEW_PROJECT, VIEW_ALL)

# Project view's group for tasks in no project or area. Its key can't clash
# with a real one: Things ids never contain a space.
NO_PROJECT = "none"
NO_PROJECT_LABEL = "No project"


@dataclass(frozen=True)
class ListEntry:
    """A Things project or area, as listed in Things' sidebar.

    `kind` is "project" or "area"; `area` is the title of a project's area
    (None for an area, or a project outside any area).
    """

    id: str
    title: str
    kind: str
    area: Optional[str] = None


@dataclass
class ViewGroup:
    """One group of a Today view, as the page draws it.

    `key` names the group and its saved order (task_order.json). `label` is
    the header ("" for All's single, unheaded group, or a priority with no
    name), `note` the gray text after it (a named priority's tag; empty in
    the Project view, whose headers show only the name). `list_id` is the project or area a
    Project view group stands for (None otherwise). `takes_moves` is whether
    a task from another group may be dropped here.
    """

    key: str
    label: str
    note: str
    tasks: List[Task]
    list_id: Optional[str] = None
    takes_moves: bool = True


def project_key(list_id: Optional[str]) -> str:
    """Return the order key of the Project view group for `list_id` (None: No project)."""
    return PROJECT_ORDER_PREFIX + (list_id or NO_PROJECT)


def group_key(task: Task, view: str, today: date, settings: Settings = DEFAULT_SETTINGS) -> str:
    """Return the key of the group `task` is in for `view`."""
    if view == VIEW_PROJECT:
        return project_key(task.list_id)
    if view == VIEW_ALL:
        return ALL_ORDER_KEY
    return required_priority(task, today, settings)


def has_tag(task: Task, tag: Optional[str]) -> bool:
    """True if `task` carries `tag`, or no tag is chosen (None)."""
    return tag is None or tag in task.tags


def tag_choices(tasks: Iterable[Task], chosen: Optional[str]) -> List[str]:
    """Return the tag bar's tags: those on open tasks, without P tags, alphabetical.

    The chosen tag stays listed after its last task is checked off, so it can
    still be seen and cleared.
    """
    tags = {t for task in tasks if not task.completed for t in task.tags if t not in PRIORITIES}
    if chosen is not None:
        tags.add(chosen)
    return sorted(tags, key=lambda t: (t.casefold(), t))


def place_in_view(
    task: Task, view: str, today: date, settings: Settings = DEFAULT_SETTINGS, tag: Optional[str] = None
) -> Optional[str]:
    """Return the key of the group `task` appears in, or None if Today (with tag `tag`) doesn't list it.

    Mirrors Today's list for a task already refreshed (see priority_check.predict).
    """
    if not in_today(task, today) or not has_tag(task, tag):
        return None
    return group_key(task, view, today, settings)


def priority_groups(
    tasks: List[Task], order: Dict[str, List[str]], today: date, settings: Settings = DEFAULT_SETTINGS
) -> List[ViewGroup]:
    """Return the Priority view: one group per priority, empty ones included (drop targets)."""
    groups = group_today(tasks, order, today, settings)
    # A priority with a name shows the tag in gray after it; one without shows only the tag.
    return [
        ViewGroup(key=p, label=settings.names[p], note=p if settings.names[p] else "", tasks=groups[p])
        for p in PRIORITIES
    ]


def project_groups(tasks: List[Task], order: Dict[str, List[str]], entries: List[ListEntry]) -> List[ViewGroup]:
    """Return the Project view: a group per project or area with tasks, in sidebar order, then No project.

    `entries` are Things' projects and areas in sidebar order. A task's
    project or area missing from them (not expected) gets a group after the
    listed ones, by title. Tasks keep their Today order (project order within
    a project) until dragged; completed tasks go last. Headers show only the
    project or area name (Michael's choice: the kind and area add nothing).
    """
    rank = {entry.id: i for i, entry in enumerate(entries)}
    by_id = {entry.id: entry for entry in entries}
    members: Dict[Optional[str], List[Task]] = {}
    for task in tasks:
        members.setdefault(task.list_id, []).append(task)

    def position(list_id: Optional[str]) -> tuple:
        if list_id is None:
            return (2, 0, "")
        if list_id in rank:
            return (0, rank[list_id], "")
        return (1, 0, members[list_id][0].context.casefold())

    groups = []
    for list_id in sorted(members, key=position):
        key = project_key(list_id)
        ordered = completed_last(apply_order(members[list_id], order.get(key, [])))
        if list_id is None:
            groups.append(ViewGroup(key=key, label=NO_PROJECT_LABEL, note="", tasks=ordered, takes_moves=False))
            continue
        entry = by_id.get(list_id)
        label = entry.title if entry else ordered[0].context
        groups.append(ViewGroup(key=key, label=label, note="", tasks=ordered, list_id=list_id))
    return groups


def all_group(
    tasks: List[Task], order: Dict[str, List[str]], today: date, settings: Settings = DEFAULT_SETTINGS
) -> ViewGroup:
    """Return the All view: one unheaded list by priority and then the Priority view's order, until dragged.

    Tasks not in the saved All order follow the ordered ones, by priority.
    Completed tasks go last.
    """
    groups = group_today(tasks, order, today, settings)
    by_priority = [task for p in PRIORITIES for task in groups[p]]
    return ViewGroup(
        key=ALL_ORDER_KEY, label="", note="",
        tasks=completed_last(apply_order(by_priority, order.get(ALL_ORDER_KEY, []))),
    )


def view_groups(
    view: str,
    tasks: List[Task],
    order: Dict[str, List[str]],
    today: date,
    settings: Settings,
    entries: List[ListEntry],
) -> List[ViewGroup]:
    """Return the groups of Today's `view`."""
    if view == VIEW_PROJECT:
        return project_groups(tasks, order, entries)
    if view == VIEW_ALL:
        return [all_group(tasks, order, today, settings)]
    return priority_groups(tasks, order, today, settings)


def place_among(group_ids: List[str], shown_ids: List[str], moved_id: str) -> List[str]:
    """Return a group's full order after `moved_id` was dropped where `shown_ids` has it.

    `group_ids` is the group's whole order before the drop; `shown_ids` the
    order the page shows after it, which may leave tasks out (the tag
    filter, Hide Completed). Tasks not shown keep their places; the dropped
    task goes just before the shown task that follows it, or after the one
    before it if it was dropped last. With nothing left out, the result is
    `shown_ids` itself.
    """
    rest = [i for i in group_ids if i != moved_id]
    position = shown_ids.index(moved_id)
    for following in shown_ids[position + 1:]:
        if following in rest:
            index = rest.index(following)
            return rest[:index] + [moved_id] + rest[index:]
    for preceding in reversed(shown_ids[:position]):
        if preceding in rest:
            index = rest.index(preceding) + 1
            return rest[:index] + [moved_id] + rest[index:]
    return rest + [moved_id]
