"""Saved searches for Do Things.

Pure logic with no I/O, so every rule can be unit-tested without Things. A
search lists tasks from Today (or from every open task) that match all of its
criteria: priority, tag, text, project or area, and an overdue deadline.
Within one criterion any of the chosen values is enough. This module holds
the `Search` model, the default searches, validation of searches.json and of
the builder's input, matching, result order, the summary line under a
search's title, and new search ids.

Version: 1.9.2

Change log:
- v1.9.2 (2026-11-10): Synchronized module version metadata.
- v1.9.1 (2026-11-10): Synchronized module version metadata.
- v1.9.0 (2026-11-10): New. Saved searches replace the fixed P1-P4 and
  Overdue searches.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from priority_check import PRIORITIES, Task, current_priority, in_today

SCOPE_TODAY, SCOPE_ALL = "today", "all"
SCOPES = (SCOPE_TODAY, SCOPE_ALL)

MAX_SEARCHES = 50
MAX_NAME_CHARS = 60
MAX_TEXT_CHARS = 100
MAX_TAG_CHARS = 60
MAX_VALUES = 20  # Most tags, or projects and areas, one search can list.

# Search ids are made by Do Things (new_search_id) and by the defaults; the
# page only sends them back. "today" is Today's own list name, so never an id.
SEARCH_ID_RE = re.compile(r"^[a-z0-9-]{1,40}$")
# A Things project or area id (same shape as task ids).
LIST_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")


@dataclass(frozen=True)
class Search:
    """A saved search: its name, scope and criteria.

    `scope`: SCOPE_TODAY (tasks in Today) or SCOPE_ALL (every open task).
    `priorities`, `tags`, `lists` (project or area ids): any of the values
    matches; empty means the criterion isn't used. `text`: found in the title
    or the notes, ignoring case; empty means not used. `overdue`: only tasks
    with a deadline before today. All criteria in use must match.
    """

    id: str
    name: str
    scope: str = SCOPE_TODAY
    priorities: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    text: str = ""
    lists: Tuple[str, ...] = ()
    overdue: bool = False

    def to_json(self) -> Dict[str, object]:
        """Return the search as stored in searches.json and sent to the page."""
        return {
            "id": self.id,
            "name": self.name,
            "scope": self.scope,
            "priorities": list(self.priorities),
            "tags": list(self.tags),
            "text": self.text,
            "lists": list(self.lists),
            "overdue": self.overdue,
        }


# The searches Do Things had before v1.9.0, used until the user changes any.
# Their ids are the old list names. Overdue keeps its old reach (every open
# task, not only Today), which the scope choice now offers to any search.
DEFAULT_SEARCHES: Tuple[Search, ...] = (
    Search("p1", "P1 · Due Today", priorities=("P1",)),
    Search("p2", "P2 · To Do", priorities=("P2",)),
    Search("p3", "P3 · Follow Up", priorities=("P3",)),
    Search("p4", "P4 · Next Up", priorities=("P4",)),
    Search("overdue", "Overdue", scope=SCOPE_ALL, overdue=True),
)


def _one_line(value: object, what: str, most: int, allow_empty: bool = False) -> str:
    """Return `value` trimmed if it is one line of text within `most` characters; else raise ValueError."""
    if not isinstance(value, str):
        raise ValueError(f"{what} must be text.")
    value = value.strip()
    if "\n" in value or len(value) > most or (not value and not allow_empty):
        least = 0 if allow_empty else 1
        raise ValueError(f"{what} must be one line of {least} to {most} characters.")
    return value


def _values(raw: object, what: str, check) -> Tuple[str, ...]:
    """Return a list of up to MAX_VALUES strings, each passed through `check`, repeats dropped."""
    if not isinstance(raw, list) or len(raw) > MAX_VALUES:
        raise ValueError(f"{what} must be a list of up to {MAX_VALUES} choices.")
    return tuple(dict.fromkeys(check(value) for value in raw))


def _tag(value: object) -> str:
    """Return a valid tag name for a search; P tags are refused (Priority covers them)."""
    tag = _one_line(value, "A tag", MAX_TAG_CHARS)
    if tag in PRIORITIES:
        raise ValueError(f"{tag} is a priority: choose it under Priority.")
    return tag


def _list_id(value: object) -> str:
    """Return a valid project or area id."""
    if not isinstance(value, str) or not LIST_ID_RE.match(value):
        raise ValueError("Unknown project or area.")
    return value


def parse_search(raw: object, search_id: str) -> Search:
    """Return a validated Search with id `search_id`; raise ValueError naming the first problem.

    Missing criteria are not used, so only the name is required. Text values
    are trimmed; repeated choices are dropped; priorities are kept in P1-P5
    order.
    """
    if not isinstance(raw, dict):
        raise ValueError("A search must be a JSON object.")
    if not SEARCH_ID_RE.match(search_id) or search_id == "today":
        raise ValueError("Invalid search id.")
    scope = raw.get("scope", SCOPE_TODAY)
    if scope not in SCOPES:
        raise ValueError("A search covers Today or all open tasks.")
    priorities = raw.get("priorities", [])
    if not isinstance(priorities, list) or not set(priorities) <= set(PRIORITIES):
        raise ValueError("Priorities must be chosen from P1 to P5.")
    overdue = raw.get("overdue", False)
    if not isinstance(overdue, bool):
        raise ValueError("overdue must be true or false.")
    return Search(
        id=search_id,
        name=_one_line(raw.get("name"), "The name", MAX_NAME_CHARS),
        scope=scope,
        priorities=tuple(p for p in PRIORITIES if p in priorities),
        tags=_values(raw.get("tags", []), "Tags", _tag),
        text=_one_line(raw.get("text", ""), "The text", MAX_TEXT_CHARS, allow_empty=True),
        lists=_values(raw.get("lists", []), "Projects and areas", _list_id),
        overdue=overdue,
    )


def check_names(searches: Iterable[Search]) -> None:
    """Raise ValueError if two searches share an id or a name (names ignoring case)."""
    ids, names = set(), set()
    for search in searches:
        if search.id in ids:
            raise ValueError(f"The search id {search.id} is used twice.")
        if search.name.casefold() in names:
            raise ValueError(f"There is already a search named “{search.name}”.")
        ids.add(search.id)
        names.add(search.name.casefold())


def parse_searches(raw: object) -> Tuple[Search, ...]:
    """Return the searches from searches.json ({"searches": [...]}); raise ValueError naming the first problem."""
    if not isinstance(raw, dict) or not isinstance(raw.get("searches"), list):
        raise ValueError("searches.json must hold a list of searches.")
    entries = raw["searches"]
    if len(entries) > MAX_SEARCHES:
        raise ValueError(f"There can be at most {MAX_SEARCHES} searches.")
    searches = []
    for entry in entries:
        search_id = entry.get("id") if isinstance(entry, dict) else None
        searches.append(parse_search(entry, search_id if isinstance(search_id, str) else ""))
    check_names(searches)
    return tuple(searches)


def searches_json(searches: Iterable[Search]) -> Dict[str, object]:
    """Return the searches as stored in searches.json."""
    return {"searches": [search.to_json() for search in searches]}


def new_search_id(searches: Iterable[Search]) -> str:
    """Return the first unused id of the form s1, s2, ..."""
    used = {search.id for search in searches}
    number = 1
    while f"s{number}" in used:
        number += 1
    return f"s{number}"


def find_search(searches: Iterable[Search], search_id: object) -> Optional[Search]:
    """Return the search with id `search_id`, or None."""
    return next((s for s in searches if s.id == search_id), None)


def with_search(searches: Tuple[Search, ...], search: Search) -> Tuple[Search, ...]:
    """Return `searches` with `search` replacing the one with its id, or added at the end.

    Raises ValueError if its name is taken or there would be too many.
    """
    if find_search(searches, search.id) is not None:
        updated = tuple(search if s.id == search.id else s for s in searches)
    elif len(searches) >= MAX_SEARCHES:
        raise ValueError(f"There can be at most {MAX_SEARCHES} searches.")
    else:
        updated = searches + (search,)
    check_names(updated)
    return updated


def without_search(searches: Tuple[Search, ...], search_id: str) -> Tuple[Search, ...]:
    """Return `searches` without the one with id `search_id` (unchanged if there is none)."""
    return tuple(s for s in searches if s.id != search_id)


def matches(task: Task, search: Search, today: date) -> bool:
    """Return True if `task` is listed by `search` on `today`.

    The task must be in the search's scope and match every criterion in use.
    Priority is the task's own P tag (the refresh rules have already run), so
    a task without one only matches a search that doesn't use Priority.
    """
    if search.scope == SCOPE_TODAY and not in_today(task, today):
        return False
    if search.priorities and current_priority(task.tags) not in search.priorities:
        return False
    if search.tags and not set(search.tags) & set(task.tags):
        return False
    if search.text:
        needle = search.text.casefold()
        if needle not in task.title.casefold() and needle not in task.notes.casefold():
            return False
    if search.lists and task.list_id not in search.lists:
        return False
    if search.overdue and (task.deadline is None or task.deadline >= today):
        return False
    return True


def search_results(tasks: Iterable[Task], search: Search, today: date) -> List[Task]:
    """Return the tasks `search` lists, soonest deadline first, tasks without one last.

    Ties keep the input order (Things' order), as Python's sort is stable.
    """
    found = [task for task in tasks if matches(task, search, today)]
    return sorted(found, key=lambda t: (t.deadline is None, t.deadline or date.min))


def shows_priority_pills(search: Search) -> bool:
    """Return True if `search` can list more than one priority, so its rows show priority pills."""
    return len(search.priorities) != 1


def describe(search: Search, list_titles: Dict[str, str]) -> str:
    """Return the line under a search's title saying what it lists, e.g. "Today tasks · tag Calls".

    `list_titles` maps project and area ids to their titles; one no longer in
    Things is named as such.
    """
    parts = ["Today tasks" if search.scope == SCOPE_TODAY else "All open tasks"]
    if search.priorities:
        parts.append(" or ".join(search.priorities))
    if search.tags:
        parts.append(("tag " if len(search.tags) == 1 else "tags ") + " or ".join(search.tags))
    if search.text:
        parts.append(f"“{search.text}” in title or notes")
    if search.lists:
        parts.append("in " + " or ".join(list_titles.get(i, "a project or area not in Things") for i in search.lists))
    if search.overdue:
        parts.append("overdue")
    return " · ".join(parts)

