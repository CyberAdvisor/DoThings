"""Tests for Today's views and the tag bar in view_check.py.

Version: 2.0.1

Change log:
- v2.0.1 (2026-11-10): Project view headers have no gray note.
- v2.0.0 (2026-11-10): New. Priority, Project and All views, the tag bar
  and drops seen through the tag filter.
"""

import unittest
from datetime import date, timedelta

from priority_check import DEFAULT_SETTINGS, Task, parse_settings
from view_check import (
    VIEW_ALL,
    VIEW_PRIORITY,
    VIEW_PROJECT,
    ListEntry,
    all_group,
    group_key,
    has_tag,
    place_among,
    place_in_view,
    priority_groups,
    project_groups,
    project_key,
    tag_choices,
    view_groups,
)

TODAY = date(2026, 11, 10)
TOMORROW = TODAY + timedelta(days=1)

# Sidebar: a project outside any area, then the Home area and its project.
ENTRIES = [
    ListEntry("vac", "Vacation", "project"),
    ListEntry("home", "Home Chores", "area"),
    ListEntry("books", "Books to read", "project", "Home Chores"),
]


def make_task(uuid, tags=(), list_id=None, context="", completed_at=None, start_date=TODAY, deadline=None) -> Task:
    """Build a Today task for tests."""
    return Task(
        uuid=uuid, title=uuid, tags=list(tags), start_date=start_date, deadline=deadline,
        context=context, list_id=list_id, completed_at=completed_at,
    )


class KeyTests(unittest.TestCase):
    """Group keys and the tag filter."""

    def test_project_key(self) -> None:
        self.assertEqual(project_key("vac"), "project:vac")
        self.assertEqual(project_key(None), "project:none")

    def test_group_key_per_view(self) -> None:
        task = make_task("a", ["P3"], list_id="vac")
        self.assertEqual(group_key(task, VIEW_PRIORITY, TODAY), "P3")
        self.assertEqual(group_key(task, VIEW_PROJECT, TODAY), "project:vac")
        self.assertEqual(group_key(task, VIEW_ALL, TODAY), "all")

    def test_has_tag(self) -> None:
        task = make_task("a", ["Calls"])
        self.assertTrue(has_tag(task, None))
        self.assertTrue(has_tag(task, "Calls"))
        self.assertFalse(has_tag(task, "calls"))  # Tags match exactly, as in Things.


class TagChoiceTests(unittest.TestCase):
    """The tag bar lists the open tasks' tags without P tags."""

    def test_open_tasks_without_p_tags_alphabetical(self) -> None:
        tasks = [
            make_task("a", ["P1", "work", "Calls"]),
            make_task("b", ["Errand", "Calls"]),
            make_task("c", ["Done only"], completed_at=1.0),
        ]
        self.assertEqual(tag_choices(tasks, None), ["Calls", "Errand", "work"])

    def test_chosen_tag_stays_listed(self) -> None:
        tasks = [make_task("c", ["Calls"], completed_at=1.0)]
        self.assertEqual(tag_choices(tasks, "Calls"), ["Calls"])


class PlaceTests(unittest.TestCase):
    """Where an edited task appears in each view."""

    def test_place_in_each_view(self) -> None:
        task = make_task("a", ["P2", "Calls"], list_id="vac")
        self.assertEqual(place_in_view(task, VIEW_PRIORITY, TODAY), "P2")
        self.assertEqual(place_in_view(task, VIEW_PROJECT, TODAY), "project:vac")
        self.assertEqual(place_in_view(task, VIEW_ALL, TODAY, tag="Calls"), "all")

    def test_overdue_task_is_p1(self) -> None:
        task = make_task("a", ["P2"], deadline=TODAY - timedelta(days=1))
        self.assertEqual(place_in_view(task, VIEW_PRIORITY, TODAY), "P1")

    def test_leaves_today_or_the_tag(self) -> None:
        self.assertIsNone(place_in_view(make_task("a", ["P2"], start_date=TOMORROW), VIEW_ALL, TODAY))
        self.assertIsNone(place_in_view(make_task("a", ["P2"]), VIEW_PROJECT, TODAY, tag="Calls"))


class PriorityViewTests(unittest.TestCase):
    """The Priority view keeps every priority as a group."""

    def test_groups_with_names_and_tags(self) -> None:
        groups = priority_groups([make_task("a", ["P2"]), make_task("b", ["P5"])], {}, TODAY)
        self.assertEqual([g.key for g in groups], ["P1", "P2", "P3", "P4", "P5"])
        self.assertEqual((groups[1].label, groups[1].note), ("To Do", "P2"))
        self.assertEqual((groups[4].label, groups[4].note), ("", ""))  # P5 has no name: the page shows the tag.
        self.assertEqual([t.uuid for t in groups[1].tasks], ["a"])
        self.assertEqual(groups[0].tasks, [])

    def test_names_from_settings(self) -> None:
        settings = parse_settings({"names": {"P5": "Someday-ish"}})
        groups = priority_groups([], {}, TODAY, settings)
        self.assertEqual((groups[4].label, groups[4].note), ("Someday-ish", "P5"))


class ProjectViewTests(unittest.TestCase):
    """The Project view: sidebar order, areas, No project last."""

    def setUp(self) -> None:
        self.tasks = [
            make_task("free", ["P1"]),
            make_task("book", ["P4"], list_id="books", context="Books to read"),
            make_task("chore", ["P2"], list_id="home", context="Home Chores"),
            make_task("hotel", ["P2"], list_id="vac", context="Vacation"),
            make_task("odd", ["P3"], list_id="gone", context="Old project"),
            make_task("flight", ["P2"], list_id="vac", context="Vacation"),
        ]

    def test_groups_in_sidebar_order(self) -> None:
        groups = project_groups(self.tasks, {}, ENTRIES)
        self.assertEqual(
            [g.key for g in groups],
            ["project:vac", "project:home", "project:books", "project:gone", "project:none"],
        )
        # Not in the sidebar read: "Old project" comes after the listed ones.
        self.assertEqual([g.label for g in groups], ["Vacation", "Home Chores", "Books to read", "Old project", "No project"])
        self.assertEqual({g.note for g in groups}, {""})  # Headers show only the name.
        self.assertEqual([g.list_id for g in groups], ["vac", "home", "books", "gone", None])

    def test_no_project_takes_no_moves(self) -> None:
        groups = project_groups(self.tasks, {}, ENTRIES)
        self.assertEqual([g.takes_moves for g in groups], [True, True, True, True, False])

    def test_only_groups_with_tasks(self) -> None:
        groups = project_groups([make_task("hotel", list_id="vac", context="Vacation")], {}, ENTRIES)
        self.assertEqual([g.key for g in groups], ["project:vac"])

    def test_today_order_then_saved_order_then_completed(self) -> None:
        tasks = self.tasks + [make_task("done", list_id="vac", completed_at=5.0)]
        vac = project_groups(tasks, {}, ENTRIES)[0]
        self.assertEqual([t.uuid for t in vac.tasks], ["hotel", "flight", "done"])
        vac = project_groups(tasks, {"project:vac": ["done", "flight"]}, ENTRIES)[0]
        self.assertEqual([t.uuid for t in vac.tasks], ["flight", "hotel", "done"])


class AllViewTests(unittest.TestCase):
    """The All view: by priority until dragged."""

    def setUp(self) -> None:
        self.tasks = [make_task("c", ["P3"]), make_task("a", ["P1"]), make_task("b2", ["P2"]), make_task("b1", ["P2"])]

    def test_by_priority_then_priority_order(self) -> None:
        group = all_group(self.tasks, {"P2": ["b1", "b2"]}, TODAY)
        self.assertEqual((group.key, group.label), ("all", ""))
        self.assertEqual([t.uuid for t in group.tasks], ["a", "b1", "b2", "c"])

    def test_saved_order_then_new_tasks_by_priority(self) -> None:
        tasks = self.tasks + [make_task("new", ["P1"])]
        group = all_group(tasks, {"all": ["c", "b2"]}, TODAY)
        self.assertEqual([t.uuid for t in group.tasks], ["c", "b2", "a", "new", "b1"])

    def test_completed_last(self) -> None:
        tasks = [make_task("done", ["P1"], completed_at=1.0)] + self.tasks
        group = all_group(tasks, {"all": ["done"]}, TODAY)
        self.assertEqual(group.tasks[-1].uuid, "done")

    def test_view_groups_dispatch(self) -> None:
        self.assertEqual(len(view_groups(VIEW_ALL, self.tasks, {}, TODAY, DEFAULT_SETTINGS, [])), 1)
        self.assertEqual(len(view_groups(VIEW_PRIORITY, self.tasks, {}, TODAY, DEFAULT_SETTINGS, [])), 5)
        self.assertEqual(
            [g.key for g in view_groups(VIEW_PROJECT, self.tasks, {}, TODAY, DEFAULT_SETTINGS, [])], ["project:none"]
        )


class PlaceAmongTests(unittest.TestCase):
    """A group's full order after a drop the page saw through a filter."""

    def test_nothing_hidden_gives_the_shown_order(self) -> None:
        self.assertEqual(place_among(["a", "b", "c"], ["b", "a", "c"], "b"), ["b", "a", "c"])
        self.assertEqual(place_among(["a", "b", "c"], ["a", "c", "b"], "b"), ["a", "c", "b"])

    def test_hidden_tasks_keep_their_places(self) -> None:
        # x and y are hidden by the tag filter; c is dropped above a.
        self.assertEqual(place_among(["x", "a", "y", "b", "c"], ["c", "a", "b"], "c"), ["x", "c", "a", "y", "b"])

    def test_dropped_last_goes_after_the_one_before(self) -> None:
        self.assertEqual(place_among(["a", "x", "b", "y"], ["b", "a"], "a"), ["x", "b", "a", "y"])

    def test_moved_in_from_another_group(self) -> None:
        self.assertEqual(place_among(["a", "x", "b"], ["a", "new", "b"], "new"), ["a", "x", "new", "b"])
        self.assertEqual(place_among([], ["new"], "new"), ["new"])

    def test_neighbours_not_in_the_group_are_skipped(self) -> None:
        # "gone" left Today since the page drew it.
        self.assertEqual(place_among(["a", "b"], ["new", "gone", "b"], "new"), ["a", "new", "b"])


if __name__ == "__main__":
    unittest.main()
