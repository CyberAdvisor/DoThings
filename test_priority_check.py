"""Tests for the priority rules in priority_check.py.

Version: 0.1.6

Change log:
- v0.1.6 (2026-11-07): Tests for completing and reopening tasks, and for
  completed tasks sorting last and being skipped by the refresh rules.
- v0.1.5 (2026-11-07): Synchronized module version metadata.
- v0.1.4 (2026-11-07): Synchronized module version metadata.
- v0.1.3 (2026-11-07): Synchronized module version metadata.
- v0.1.2 (2026-11-07): Synchronized module version metadata.
- v0.1.1 (2026-11-07): Tests for setting the start date when moving out of P1.
- v0.1.0 (2026-11-07): Initial release.
"""

import unittest
from datetime import date, timedelta

from priority_check import (
    Change,
    Task,
    apply_order,
    completed_last,
    current_priority,
    deadline_state,
    group_today,
    plan_completion,
    plan_move,
    plan_refresh,
    required_priority,
    update_order,
)

TODAY = date(2026, 11, 7)
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


def make_task(uuid: str = "A1", tags=None, deadline=None, start_date=None, completed_at=None) -> Task:
    """Build a Today task for tests."""
    return Task(
        uuid=uuid, title=uuid, tags=list(tags or []), deadline=deadline,
        start_date=start_date, completed_at=completed_at,
    )


class RequiredPriorityTests(unittest.TestCase):
    """Refresh rules: overdue/due today -> P1, highest P tag wins, untagged -> P2."""

    def test_overdue_is_p1(self) -> None:
        self.assertEqual(required_priority(make_task(tags=["P3"], deadline=YESTERDAY), TODAY), "P1")

    def test_due_today_is_p1(self) -> None:
        self.assertEqual(required_priority(make_task(tags=["P2"], deadline=TODAY), TODAY), "P1")

    def test_future_deadline_keeps_tag(self) -> None:
        self.assertEqual(required_priority(make_task(tags=["P3"], deadline=TOMORROW), TODAY), "P3")

    def test_highest_tag_wins(self) -> None:
        self.assertEqual(required_priority(make_task(tags=["P3", "P2"]), TODAY), "P2")

    def test_untagged_is_p2(self) -> None:
        self.assertEqual(required_priority(make_task(tags=["Home"]), TODAY), "P2")

    def test_current_priority_none_without_p_tag(self) -> None:
        self.assertIsNone(current_priority(["Home"]))


class PlanRefreshTests(unittest.TestCase):
    """Refresh changes retag only when needed and keep non-priority tags."""

    def test_compliant_task_needs_no_change(self) -> None:
        self.assertIsNone(plan_refresh(make_task(tags=["Home", "P2"]), TODAY))

    def test_untagged_gets_p2_and_keeps_other_tags(self) -> None:
        change = plan_refresh(make_task(tags=["Home"]), TODAY)
        self.assertEqual(change.tags, ["Home", "P2"])
        self.assertIsNone(change.set_deadline)
        self.assertFalse(change.clear_deadline)

    def test_extra_p_tags_removed(self) -> None:
        self.assertEqual(plan_refresh(make_task(tags=["P1", "P3"]), TODAY).tags, ["P1"])

    def test_overdue_p2_retagged_p1(self) -> None:
        self.assertEqual(plan_refresh(make_task(tags=["P2"], deadline=YESTERDAY), TODAY).tags, ["P1"])


class CompletionTests(unittest.TestCase):
    """Completing and reopening tasks."""

    def test_refresh_skips_completed_tasks(self) -> None:
        # Untagged and overdue: an open task would be retagged P1.
        self.assertIsNone(plan_refresh(make_task(deadline=YESTERDAY, completed_at=100.0), TODAY))

    def test_plan_completion_leaves_tags_and_dates_alone(self) -> None:
        for completed in (True, False):
            with self.subTest(completed=completed):
                change = plan_completion(make_task(tags=["P2"], deadline=TODAY), completed)
                self.assertEqual(change.set_completed, completed)
                self.assertIsNone(change.tags)
                self.assertIsNone(change.set_deadline)
                self.assertFalse(change.clear_deadline)
                self.assertIsNone(change.set_start_date)

    def test_completion_confirmed_by_state_not_tags(self) -> None:
        done = Change(task_id="A1", tags=None, set_completed=True)
        self.assertTrue(done.is_satisfied_by(make_task(tags=["P3"], completed_at=100.0)))
        self.assertFalse(done.is_satisfied_by(make_task(tags=["P3"])))
        reopen = Change(task_id="A1", tags=None, set_completed=False)
        self.assertTrue(reopen.is_satisfied_by(make_task(tags=["P3"])))
        self.assertFalse(reopen.is_satisfied_by(make_task(tags=["P3"], completed_at=100.0)))

    def test_completed_last_oldest_completion_first(self) -> None:
        tasks = [
            make_task("late", completed_at=300.0),
            make_task("open1"),
            make_task("early", completed_at=100.0),
            make_task("open2"),
        ]
        self.assertEqual([t.uuid for t in completed_last(tasks)], ["open1", "open2", "early", "late"])

    def test_group_today_puts_completed_last_despite_saved_order(self) -> None:
        tasks = [make_task("done", tags=["P2"], completed_at=100.0), make_task("open", tags=["P2"])]
        groups = group_today(tasks, {"P2": ["done", "open"]}, TODAY)
        self.assertEqual([t.uuid for t in groups["P2"]], ["open", "done"])


class PlanMoveTests(unittest.TestCase):
    """Manual moves replace P tags and set or clear the deadline."""

    def test_into_p1_sets_deadline_today(self) -> None:
        change = plan_move(make_task(tags=["P2"]), "P1", TODAY)
        self.assertEqual(change.tags, ["P1"])
        self.assertEqual(change.set_deadline, TODAY)

    def test_p3_into_p1_sets_deadline_today(self) -> None:
        self.assertEqual(plan_move(make_task(tags=["P3"]), "P1", TODAY).set_deadline, TODAY)

    def test_out_of_p1_clears_deadline_and_keeps_existing_start(self) -> None:
        for start in (TODAY, YESTERDAY):
            change = plan_move(make_task(tags=["P1"], deadline=TODAY, start_date=start), "P3", TODAY)
            self.assertEqual(change.tags, ["P3"])
            self.assertTrue(change.clear_deadline)
            self.assertIsNone(change.set_start_date)

    def test_deadline_only_task_out_of_p1_gets_start_today(self) -> None:
        for destination in ("P2", "P3"):
            for start in (None, TOMORROW):
                task = make_task(tags=["P1"], deadline=YESTERDAY, start_date=start)
                change = plan_move(task, destination, TODAY)
                self.assertTrue(change.clear_deadline)
                self.assertEqual(change.set_start_date, TODAY)

    def test_into_p1_and_p2_p3_leave_start_alone(self) -> None:
        self.assertIsNone(plan_move(make_task(tags=["P2"]), "P1", TODAY).set_start_date)
        self.assertIsNone(plan_move(make_task(tags=["P2"]), "P3", TODAY).set_start_date)

    def test_overdue_task_moved_to_p2_clears_deadline(self) -> None:
        self.assertTrue(plan_move(make_task(tags=["P2"], deadline=YESTERDAY), "P2", TODAY).clear_deadline)

    def test_p2_to_p3_leaves_deadline(self) -> None:
        change = plan_move(make_task(tags=["P2"], deadline=TOMORROW), "P3", TODAY)
        self.assertIsNone(change.set_deadline)
        self.assertFalse(change.clear_deadline)

    def test_move_replaces_all_p_tags(self) -> None:
        self.assertEqual(plan_move(make_task(tags=["Home", "P2", "P3"]), "P3", TODAY).tags, ["Home", "P3"])

    def test_unknown_destination_rejected(self) -> None:
        with self.assertRaises(ValueError):
            plan_move(make_task(), "P4", TODAY)


class ChangeConfirmationTests(unittest.TestCase):
    """A change is confirmed only when the re-read task matches it."""

    def test_matching_tags_in_any_order(self) -> None:
        change = Change(task_id="A1", tags=["Home", "P1"])
        self.assertTrue(change.is_satisfied_by(make_task(tags=["P1", "Home"])))

    def test_tags_not_applied(self) -> None:
        self.assertFalse(Change(task_id="A1", tags=["P1"]).is_satisfied_by(make_task(tags=["P2"])))

    def test_deadline_not_set(self) -> None:
        change = Change(task_id="A1", tags=["P1"], set_deadline=TODAY)
        self.assertFalse(change.is_satisfied_by(make_task(tags=["P1"])))

    def test_start_date_not_set(self) -> None:
        change = Change(task_id="A1", tags=["P2"], clear_deadline=True, set_start_date=TODAY)
        self.assertFalse(change.is_satisfied_by(make_task(tags=["P2"])))
        self.assertTrue(change.is_satisfied_by(make_task(tags=["P2"], start_date=TODAY)))

    def test_deadline_not_cleared(self) -> None:
        change = Change(task_id="A1", tags=["P2"], clear_deadline=True)
        self.assertFalse(change.is_satisfied_by(make_task(tags=["P2"], deadline=TODAY)))
        self.assertTrue(change.is_satisfied_by(make_task(tags=["P2"])))


class OrderingTests(unittest.TestCase):
    """Grouping and saved order."""

    def test_apply_order_puts_unsaved_last_in_input_order(self) -> None:
        tasks = [make_task("A"), make_task("B"), make_task("C"), make_task("D")]
        self.assertEqual([t.uuid for t in apply_order(tasks, ["C", "A", "GONE"])], ["C", "A", "B", "D"])

    def test_group_today(self) -> None:
        tasks = [
            make_task("A", ["P2"]),
            make_task("B", ["P3"], deadline=TODAY),
            make_task("C"),
            make_task("D", ["P3"]),
        ]
        groups = group_today(tasks, {"P2": ["C", "A"]}, TODAY)
        self.assertEqual([t.uuid for t in groups["P1"]], ["B"])
        self.assertEqual([t.uuid for t in groups["P2"]], ["C", "A"])
        self.assertEqual([t.uuid for t in groups["P3"]], ["D"])

    def test_update_order_removes_ids_from_other_groups(self) -> None:
        order = {"P1": ["A", "B"], "P2": ["C"]}
        self.assertEqual(
            update_order(order, "P2", ["B", "C"]), {"P1": ["A"], "P2": ["B", "C"], "P3": []}
        )

    def test_update_order_rejects_unknown_priority(self) -> None:
        with self.assertRaises(ValueError):
            update_order({}, "P9", [])

    def test_deadline_state(self) -> None:
        self.assertEqual(deadline_state(YESTERDAY, TODAY), "overdue")
        self.assertEqual(deadline_state(TODAY, TODAY), "today")
        self.assertEqual(deadline_state(TOMORROW, TODAY), "future")
        self.assertIsNone(deadline_state(None, TODAY))


if __name__ == "__main__":
    unittest.main()
