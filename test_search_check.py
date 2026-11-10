"""Tests for the saved-search logic in search_check.py.

Version: 2.0.1

Change log:
- v2.0.1 (2026-11-10): Synchronized module version metadata.
- v2.0.0 (2026-11-10): Synchronized module version metadata.
- v1.9.2 (2026-11-10): Synchronized module version metadata.
- v1.9.1 (2026-11-10): Synchronized module version metadata.
- v1.9.0 (2026-11-10): New. Tests for parsing, matching, order, pills,
  the summary line and search ids.
"""

import unittest
from datetime import date, timedelta

from priority_check import Task
from search_check import (
    DEFAULT_SEARCHES,
    MAX_SEARCHES,
    SCOPE_ALL,
    Search,
    describe,
    find_search,
    matches,
    new_search_id,
    parse_search,
    parse_searches,
    search_results,
    searches_json,
    shows_priority_pills,
    with_search,
    without_search,
)

TODAY = date(2026, 11, 10)
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


def task(uuid="t", tags=("P2",), start=TODAY, deadline=None, title="Task", notes="", list_id=None) -> Task:
    """Build a task for the search tests (in Today unless `start` is later or None)."""
    return Task(
        uuid=uuid, title=title, tags=list(tags), start_date=start, deadline=deadline,
        notes=notes, list_id=list_id,
    )


class ParseTests(unittest.TestCase):
    """Validation of one search and of searches.json."""

    def test_minimal_search_uses_no_criteria(self) -> None:
        search = parse_search({"name": "  Everything  "}, "s1")
        self.assertEqual(search, Search("s1", "Everything"))

    def test_criteria_are_trimmed_ordered_and_deduplicated(self) -> None:
        search = parse_search(
            {"name": "Mix", "scope": "all", "priorities": ["P3", "P1", "P3"], "tags": [" Calls ", "Calls", "Home"],
             "text": " lisbon ", "lists": ["A1", "A1"], "overdue": True},
            "s2",
        )
        self.assertEqual(
            (search.scope, search.priorities, search.tags, search.text, search.lists, search.overdue),
            ("all", ("P1", "P3"), ("Calls", "Home"), "lisbon", ("A1",), True),
        )

    def test_refused_values(self) -> None:
        bad = [
            ({"name": ""}, "s1"),
            ({"name": "a\nb"}, "s1"),
            ({"name": "x" * 61}, "s1"),
            ({"name": "Ok", "scope": "week"}, "s1"),
            ({"name": "Ok", "priorities": ["P6"]}, "s1"),
            ({"name": "Ok", "tags": ["P2"]}, "s1"),
            ({"name": "Ok", "tags": [""]}, "s1"),
            ({"name": "Ok", "tags": "Calls"}, "s1"),
            ({"name": "Ok", "tags": ["t%d" % i for i in range(21)]}, "s1"),
            ({"name": "Ok", "text": "a\nb"}, "s1"),
            ({"name": "Ok", "lists": ["bad id!"]}, "s1"),
            ({"name": "Ok", "overdue": "yes"}, "s1"),
            ({"name": "Ok"}, "today"),
            ({"name": "Ok"}, "Bad Id"),
            ("not an object", "s1"),
        ]
        for raw, search_id in bad:
            with self.subTest(raw=raw, search_id=search_id), self.assertRaises(ValueError):
                parse_search(raw, search_id)

    def test_round_trip_of_the_defaults(self) -> None:
        self.assertEqual(parse_searches(searches_json(DEFAULT_SEARCHES)), DEFAULT_SEARCHES)

    def test_empty_list_stays_empty(self) -> None:
        self.assertEqual(parse_searches({"searches": []}), ())

    def test_file_problems(self) -> None:
        dup_name = {"searches": [{"id": "a", "name": "X"}, {"id": "b", "name": "x"}]}
        dup_id = {"searches": [{"id": "a", "name": "X"}, {"id": "a", "name": "Y"}]}
        too_many = {"searches": [{"id": f"s{i}", "name": f"S{i}"} for i in range(MAX_SEARCHES + 1)]}
        for raw in ([], {"searches": "x"}, {"searches": [{"name": "No id"}]}, dup_name, dup_id, too_many):
            with self.subTest(raw=str(raw)[:40]), self.assertRaises(ValueError):
                parse_searches(raw)


class EditTests(unittest.TestCase):
    """Adding, replacing and removing searches, and new ids."""

    def test_new_search_id_fills_the_first_gap(self) -> None:
        self.assertEqual(new_search_id(DEFAULT_SEARCHES), "s1")
        self.assertEqual(new_search_id([Search("s1", "A"), Search("s3", "B")]), "s2")

    def test_with_search_adds_at_the_end_or_replaces_in_place(self) -> None:
        added = with_search(DEFAULT_SEARCHES, Search("s1", "Calls", tags=("Calls",)))
        self.assertEqual([s.id for s in added], ["p1", "p2", "p3", "p4", "overdue", "s1"])
        changed = with_search(added, Search("p2", "To do now", priorities=("P2",)))
        self.assertEqual(find_search(changed, "p2").name, "To do now")
        self.assertEqual([s.id for s in changed], [s.id for s in added])

    def test_with_search_refuses_a_taken_name(self) -> None:
        with self.assertRaises(ValueError):
            with_search(DEFAULT_SEARCHES, Search("s1", "overdue"))
        # Keeping its own name is fine.
        with_search(DEFAULT_SEARCHES, Search("overdue", "Overdue", overdue=True))

    def test_with_search_refuses_too_many(self) -> None:
        full = tuple(Search(f"s{i}", f"S{i}") for i in range(MAX_SEARCHES))
        with self.assertRaises(ValueError):
            with_search(full, Search("new", "New"))

    def test_without_search(self) -> None:
        self.assertEqual([s.id for s in without_search(DEFAULT_SEARCHES, "p3")], ["p1", "p2", "p4", "overdue"])
        self.assertEqual(without_search(DEFAULT_SEARCHES, "nope"), DEFAULT_SEARCHES)


class MatchTests(unittest.TestCase):
    """Each criterion, AND between criteria, OR within one."""

    def test_today_scope_needs_a_task_in_today(self) -> None:
        search = Search("s", "S")
        self.assertTrue(matches(task(), search, TODAY))
        self.assertTrue(matches(task(start=None, deadline=YESTERDAY), search, TODAY))
        self.assertFalse(matches(task(start=TOMORROW), search, TODAY))
        self.assertFalse(matches(task(start=None), search, TODAY))

    def test_all_scope_takes_any_open_task(self) -> None:
        self.assertTrue(matches(task(start=None), Search("s", "S", scope=SCOPE_ALL), TODAY))

    def test_priorities_any_of(self) -> None:
        search = Search("s", "S", priorities=("P1", "P3"))
        self.assertTrue(matches(task(tags=["P3"]), search, TODAY))
        self.assertFalse(matches(task(tags=["P2"]), search, TODAY))
        self.assertFalse(matches(task(tags=["Home"]), search, TODAY))  # No P tag.

    def test_tags_any_of(self) -> None:
        search = Search("s", "S", tags=("Calls", "Errand"))
        self.assertTrue(matches(task(tags=["P2", "Errand"]), search, TODAY))
        self.assertFalse(matches(task(tags=["P2", "Home"]), search, TODAY))

    def test_text_in_title_or_notes_ignoring_case(self) -> None:
        search = Search("s", "S", text="lisbon")
        self.assertTrue(matches(task(title="Book hotel in Lisbon"), search, TODAY))
        self.assertTrue(matches(task(notes="Flights to LISBON"), search, TODAY))
        self.assertFalse(matches(task(title="Book hotel"), search, TODAY))

    def test_lists_any_of(self) -> None:
        search = Search("s", "S", lists=("proj", "area"))
        self.assertTrue(matches(task(list_id="area"), search, TODAY))
        self.assertFalse(matches(task(list_id="other"), search, TODAY))
        self.assertFalse(matches(task(list_id=None), search, TODAY))

    def test_overdue_is_before_today(self) -> None:
        search = Search("s", "S", scope=SCOPE_ALL, overdue=True)
        self.assertTrue(matches(task(deadline=YESTERDAY), search, TODAY))
        self.assertFalse(matches(task(deadline=TODAY), search, TODAY))
        self.assertFalse(matches(task(), search, TODAY))

    def test_all_criteria_must_match(self) -> None:
        search = Search("s", "S", priorities=("P1",), tags=("Calls",))
        self.assertTrue(matches(task(tags=["P1", "Calls"]), search, TODAY))
        self.assertFalse(matches(task(tags=["P1"]), search, TODAY))
        self.assertFalse(matches(task(tags=["P2", "Calls"]), search, TODAY))

    def test_defaults_behave_like_the_old_searches(self) -> None:
        p2, overdue = find_search(DEFAULT_SEARCHES, "p2"), find_search(DEFAULT_SEARCHES, "overdue")
        self.assertTrue(matches(task(tags=["P2"]), p2, TODAY))
        self.assertFalse(matches(task(tags=["P2"], start=TOMORROW), p2, TODAY))  # Not started yet.
        # Overdue covers every open task, including one starting later.
        self.assertTrue(matches(task(start=TOMORROW, deadline=YESTERDAY), overdue, TODAY))


class DisplayTests(unittest.TestCase):
    """Result order, priority pills and the summary line."""

    def test_results_soonest_deadline_first_then_input_order(self) -> None:
        tasks = [task("none1"), task("later", deadline=TOMORROW), task("none2"), task("soon", deadline=TODAY)]
        found = search_results(tasks, Search("s", "S"), TODAY)
        self.assertEqual([t.uuid for t in found], ["soon", "later", "none1", "none2"])

    def test_pills_unless_one_priority(self) -> None:
        self.assertTrue(shows_priority_pills(Search("s", "S")))
        self.assertTrue(shows_priority_pills(Search("s", "S", priorities=("P1", "P2"))))
        self.assertFalse(shows_priority_pills(Search("s", "S", priorities=("P2",))))

    def test_describe(self) -> None:
        self.assertEqual(describe(Search("s", "S", tags=("Calls",)), {}), "Today tasks · tag Calls")
        full = Search(
            "s", "S", scope=SCOPE_ALL, priorities=("P1", "P2"), tags=("Calls", "Home"), text="hotel",
            lists=("p", "gone"), overdue=True,
        )
        self.assertEqual(
            describe(full, {"p": "Vacation"}),
            "All open tasks · P1 or P2 · tags Calls or Home · “hotel” in title or notes · "
            "in Vacation or a project or area not in Things · overdue",
        )


if __name__ == "__main__":
    unittest.main()
