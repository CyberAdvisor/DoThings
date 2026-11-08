"""Tests for the priority rules in priority_check.py.

Version: 1.2.0

Change log:
- v1.2.0 (2026-11-08): Tests for P4 by default in Next Up projects and for
  plan_sequence_reset.
- v1.1.0 (2026-11-08): Tests for P4, Next Up projects and the project tag
  change.
- v1.0.3 (2026-11-07): Synchronized module version metadata.
- v1.0.2 (2026-11-07): Synchronized module version metadata.
- v1.0.1 (2026-11-07): Change log trimmed to v1.0.0 and later; earlier history is in git.
- v1.0.0 (2026-11-07): Synchronized module version metadata.
"""

import unittest
from datetime import date, timedelta

from priority_check import (
    NEXT_UP_TAG,
    SEQUENTIAL_TAG,
    Change,
    ProjectChange,
    Task,
    TaskEdit,
    apply_order,
    completed_last,
    current_priority,
    deadline_state,
    find_pulled,
    group_today,
    in_project_order,
    in_today,
    place_in_list,
    plan_completion,
    plan_edit,
    plan_move,
    plan_project_tags,
    plan_refresh,
    plan_sequence,
    plan_sequence_reset,
    plan_sequence_undo,
    predict,
    prune_order,
    required_priority,
    sequence_kind,
    sequence_next,
    sequence_place,
    today_counts,
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


class StartDateRuleTests(unittest.TestCase):
    """Tasks with no start date that are due today or overdue get a start date of today."""

    def test_no_start_date_due_today_or_overdue_gets_start_today(self) -> None:
        for deadline in (TODAY, YESTERDAY):
            with self.subTest(deadline=deadline):
                change = plan_refresh(make_task(tags=["P1"], deadline=deadline), TODAY)
                self.assertEqual(change.set_start_date, TODAY)
                self.assertIsNone(change.tags)  # Already P1, so tags are left alone.
                self.assertIsNone(change.set_deadline)
                self.assertFalse(change.clear_deadline)

    def test_combined_with_retag(self) -> None:
        change = plan_refresh(make_task(tags=["Home"], deadline=TODAY), TODAY)
        self.assertEqual((change.tags, change.set_start_date), (["Home", "P1"], TODAY))

    def test_someday_counts_too(self) -> None:
        task = make_task(tags=["P1"], deadline=TODAY)
        task.someday = True
        self.assertEqual(plan_refresh(task, TODAY).set_start_date, TODAY)

    def test_left_alone(self) -> None:
        cases = {
            "future deadline": make_task(tags=["P2"], deadline=TOMORROW),
            "no deadline": make_task(tags=["P2"]),
            "has start date": make_task(tags=["P1"], deadline=TODAY, start_date=YESTERDAY),
            "completed": make_task(tags=["P1"], deadline=TODAY, completed_at=1.0),
        }
        for name, task in cases.items():
            with self.subTest(name):
                self.assertIsNone(plan_refresh(task, TODAY))


def in_project(uuid: str, project: str, rank, **kwargs) -> Task:
    """Build a task in `project` at `rank` (see Task.project_rank)."""
    task = make_task(uuid, **kwargs)
    task.project_id, task.project_rank = project, rank
    return task


class ProjectOrderTests(unittest.TestCase):
    """Tasks of the same project follow the project's manual order."""

    def test_same_project_reordered_in_place(self) -> None:
        tasks = [
            in_project("p3", "P", (0, 0, 3)),
            make_task("loose"),
            in_project("p1", "P", (0, 0, 1)),
            in_project("q1", "Q", (0, 0, 1)),
            in_project("h1", "P", (1, 0, 0)),  # Under the first heading: after unheaded tasks.
            in_project("p2", "P", (0, 0, 2)),
        ]
        self.assertEqual([t.uuid for t in in_project_order(tasks)], ["p1", "loose", "p2", "q1", "p3", "h1"])

    def test_headings_in_heading_order(self) -> None:
        tasks = [in_project("b", "P", (1, 2, 0)), in_project("a", "P", (1, 1, 5))]
        self.assertEqual([t.uuid for t in in_project_order(tasks)], ["a", "b"])


class SequenceTests(unittest.TestCase):
    """Sequential projects: the next undated task gets a start date of today, one at a time."""

    def test_first_undated_task_gets_start_today(self) -> None:
        tasks = [in_project("second", "S", (0, 0, 2)), in_project("first", "S", (0, 0, 1))]
        change = plan_sequence(tasks, TODAY)
        self.assertEqual((change.task_id, change.set_start_date, change.tags), ("first", TODAY, None))

    def test_nothing_new_while_task_in_progress(self) -> None:
        tasks = [in_project("first", "S", (0, 0, 1), start_date=TODAY), in_project("second", "S", (0, 0, 2))]
        self.assertEqual(sequence_next(tasks, TODAY).uuid, "first")
        self.assertIsNone(plan_sequence(tasks, TODAY))

    def test_next_after_completion(self) -> None:
        tasks = [in_project("first", "S", (0, 0, 1), start_date=TODAY, completed_at=1.0),
                 in_project("second", "S", (0, 0, 2))]
        self.assertEqual(plan_sequence(tasks, TODAY).task_id, "second")

    def test_dated_and_someday_tasks_are_skipped(self) -> None:
        someday = in_project("someday", "S", (0, 0, 3))
        someday.someday = True
        tasks = [
            in_project("deadline", "S", (0, 0, 1), deadline=TOMORROW),
            in_project("future", "S", (0, 0, 2), start_date=TOMORROW),
            someday,
            in_project("plain", "S", (1, 0, 0)),  # Under a heading: after the unheaded tasks.
        ]
        self.assertEqual(plan_sequence(tasks, TODAY).task_id, "plain")

    def test_started_earlier_counts_as_in_progress(self) -> None:
        tasks = [in_project("old", "S", (0, 0, 1), start_date=YESTERDAY), in_project("next", "S", (0, 0, 2))]
        self.assertIsNone(plan_sequence(tasks, TODAY))

    def test_find_pulled(self) -> None:
        tasks = [in_project("a", "S", (0, 0, 1), start_date=TODAY)]
        self.assertEqual(find_pulled(tasks, "a", TODAY).uuid, "a")
        self.assertIsNone(find_pulled(tasks, "a", YESTERDAY))  # Date changed since: leave it alone.
        self.assertIsNone(find_pulled(tasks, "gone", TODAY))   # Completed or removed.

    def test_undo_when_triggering_task_reopened(self) -> None:
        # Things moves a reopened task to the bottom, so it now sorts after the started one.
        reopened = in_project("first", "S", (0, 0, 9), start_date=TODAY)
        pulled = in_project("second", "S", (0, 0, 2), tags=["Home", "P2"], start_date=TODAY)
        change = plan_sequence_undo([pulled, reopened], pulled, "first")
        self.assertEqual((change.task_id, change.set_when, change.tags), ("second", "anytime", ["Home"]))
        self.assertIsNone(change.set_start_date)

    def test_undo_keeps_tags_without_p_tag(self) -> None:
        reopened = in_project("first", "S", (0, 0, 1), start_date=TODAY)
        pulled = in_project("second", "S", (0, 0, 2), tags=["Home"], start_date=TODAY)
        self.assertIsNone(plan_sequence_undo([reopened, pulled], pulled, "first").tags)

    def test_no_undo_while_triggering_task_stays_done_or_unknown(self) -> None:
        pulled = in_project("second", "S", (0, 0, 2), start_date=TODAY)
        done = in_project("first", "S", (0, 0, 1), start_date=TODAY, completed_at=1.0)
        self.assertIsNone(plan_sequence_undo([done, pulled], pulled, "first"))
        self.assertIsNone(plan_sequence_undo([pulled], pulled, "first"))  # Not open (not listed).
        self.assertIsNone(plan_sequence_undo([done, pulled], pulled, None))  # Unknown trigger.

    def test_nothing_to_do(self) -> None:
        self.assertIsNone(plan_sequence([], TODAY))
        self.assertIsNone(plan_sequence([in_project("due", "S", (0, 0, 1), deadline=TODAY)], TODAY))


class NextUpTests(unittest.TestCase):
    """P4 (Next Up): the lowest priority, and Next Up projects that start their task as P4."""

    def test_p4_is_lowest(self) -> None:
        self.assertEqual(required_priority(make_task(tags=["P4"]), TODAY), "P4")
        self.assertEqual(required_priority(make_task(tags=["P4", "P3"]), TODAY), "P3")
        self.assertEqual(required_priority(make_task(tags=["P4"], deadline=YESTERDAY), TODAY), "P1")
        change = plan_refresh(make_task(tags=["P4", "P2"]), TODAY)
        self.assertEqual(change.tags, ["P2"])

    def test_moves_into_and_out_of_p4(self) -> None:
        # Out of P1: a deadline of today goes and the task stays in Today.
        change = plan_move(make_task(tags=["P1"], deadline=TODAY), "P4", TODAY)
        self.assertEqual((change.tags, change.clear_deadline, change.set_start_date), (["P4"], True, TODAY))
        # Among P2-P4 the deadline is left alone; a later deadline is always kept.
        change = plan_move(make_task(tags=["P2"], deadline=TOMORROW, start_date=TODAY), "P4", TODAY)
        self.assertEqual((change.tags, change.clear_deadline, change.set_deadline), (["P4"], False, None))
        change = plan_move(make_task(tags=["P4"], start_date=TODAY), "P1", TODAY)
        self.assertEqual((change.tags, change.set_deadline), (["P1"], TODAY))

    def test_p4_search(self) -> None:
        task = make_task(tags=["P4"], start_date=TODAY)
        self.assertEqual(place_in_list(task, "p4", TODAY), "list")
        self.assertIsNone(place_in_list(task, "p3", TODAY))
        self.assertEqual(place_in_list(task, "today", TODAY), "P4")

    def test_sequence_kind(self) -> None:
        self.assertEqual(sequence_kind(["Home", SEQUENTIAL_TAG]), SEQUENTIAL_TAG)
        self.assertEqual(sequence_kind([NEXT_UP_TAG]), NEXT_UP_TAG)
        self.assertEqual(sequence_kind([NEXT_UP_TAG, SEQUENTIAL_TAG]), SEQUENTIAL_TAG)  # Sequential wins.
        self.assertIsNone(sequence_kind(["Home"]))

    def test_next_up_removed_when_also_sequential(self) -> None:
        change = plan_project_tags("proj", ["Home", NEXT_UP_TAG, SEQUENTIAL_TAG])
        self.assertEqual(change, ProjectChange("proj", ["Home", SEQUENTIAL_TAG]))
        self.assertTrue(change.is_satisfied_by([SEQUENTIAL_TAG, "Home"]))
        self.assertFalse(change.is_satisfied_by(["Home", NEXT_UP_TAG, SEQUENTIAL_TAG]))
        self.assertIsNone(plan_project_tags("proj", [NEXT_UP_TAG]))
        self.assertIsNone(plan_project_tags("proj", [SEQUENTIAL_TAG]))

    def test_untagged_next_up_task_is_p4(self) -> None:
        task = make_task(start_date=TODAY)
        task.next_up = True
        self.assertEqual(required_priority(task, TODAY), "P4")
        self.assertEqual(plan_refresh(task, TODAY).tags, ["P4"])
        task.tags = ["P2"]  # Moved by hand: the tag wins.
        self.assertEqual(required_priority(task, TODAY), "P2")
        task.deadline = TODAY
        self.assertEqual(required_priority(task, TODAY), "P1")
        self.assertEqual(required_priority(make_task(start_date=TODAY), TODAY), "P2")  # Not Next Up.

    def test_undo_removes_p4(self) -> None:
        reopened = in_project("first", "N", (0, 0, 9), start_date=TODAY)
        pulled = in_project("second", "N", (0, 0, 2), tags=["Books", "P4"], start_date=TODAY)
        self.assertEqual(plan_sequence_undo([pulled, reopened], pulled, "first").tags, ["Books"])


class SequenceResetTests(unittest.TestCase):
    """Reset other tasks: only the chosen task of a sequential project stays in Today."""

    def test_other_started_tasks_go_back_to_anytime(self) -> None:
        keep = in_project("keep", "S", (0, 0, 3), tags=["P4"], start_date=TODAY)
        done = in_project("done", "S", (0, 0, 0), start_date=TODAY, completed_at=1.0)
        someday = in_project("someday", "S", (0, 0, 7))
        someday.someday = True
        tasks = [
            in_project("later", "S", (0, 0, 2), tags=["Books", "P4"], start_date=YESTERDAY),
            in_project("first", "S", (0, 0, 1), start_date=TODAY),
            keep, done, someday,
            in_project("due", "S", (0, 0, 4), start_date=TODAY, deadline=TOMORROW),  # Has a deadline.
            in_project("future", "S", (0, 0, 5), start_date=TOMORROW),
            in_project("undated", "S", (0, 0, 6)),
        ]
        changes = plan_sequence_reset(tasks, keep, TODAY)
        # In project order; P tags removed (None when there were none to remove).
        self.assertEqual([(c.task_id, c.set_when, c.tags) for c in changes],
                         [("first", "anytime", None), ("later", "anytime", ["Books"])])

    def test_kept_task_due_only_gets_start_date(self) -> None:
        keep = in_project("keep", "S", (0, 0, 2), deadline=YESTERDAY)
        other = in_project("other", "S", (0, 0, 1), start_date=TODAY)
        changes = plan_sequence_reset([keep, other], keep, TODAY)
        self.assertEqual([(c.task_id, c.set_start_date, c.set_when) for c in changes],
                         [("keep", TODAY, None), ("other", None, "anytime")])

    def test_nothing_to_reset(self) -> None:
        keep = in_project("keep", "S", (0, 0, 1), start_date=TODAY)
        self.assertEqual(plan_sequence_reset([keep, in_project("next", "S", (0, 0, 2))], keep, TODAY), [])


class TodayCountsTests(unittest.TestCase):
    """Sidebar counts for Today."""

    def test_open_and_due(self) -> None:
        tasks = [
            make_task("overdue", deadline=YESTERDAY),
            make_task("due", deadline=TODAY),
            make_task("later", deadline=TOMORROW),
            make_task("plain"),
            make_task("done_due", deadline=TODAY, completed_at=1.0),
        ]
        self.assertEqual(today_counts(tasks, TODAY), {"due": 2, "not_due": 2})
        self.assertEqual(today_counts([], TODAY), {"due": 0, "not_due": 0})


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


class PlanEditTests(unittest.TestCase):
    """Turning an edit-view save into one Change."""

    def test_nothing_changed(self) -> None:
        self.assertIsNone(plan_edit(make_task(tags=["P2"]), TaskEdit(), TODAY))

    def test_text_fields_only(self) -> None:
        change = plan_edit(make_task(tags=["P2"]), TaskEdit(title="New", notes="Body"), TODAY)
        self.assertEqual((change.set_title, change.set_notes), ("New", "Body"))
        self.assertIsNone(change.tags)
        self.assertIsNone(change.set_deadline)
        self.assertIsNone(change.set_start_date)

    def test_priority_uses_move_rules(self) -> None:
        change = plan_edit(make_task(tags=["Home", "P2"]), TaskEdit(priority="P1"), TODAY)
        self.assertEqual(change.tags, ["Home", "P1"])
        self.assertEqual(change.set_deadline, TODAY)

    def test_explicit_deadline_wins_over_move_rules(self) -> None:
        later = TODAY + timedelta(days=5)
        change = plan_edit(make_task(tags=["P2"]), TaskEdit(priority="P1", deadline=later), TODAY)
        self.assertEqual(change.set_deadline, later)
        change = plan_edit(make_task(tags=["P1"], deadline=TODAY), TaskEdit(priority="P2", deadline=later), TODAY)
        self.assertEqual(change.set_deadline, later)
        self.assertFalse(change.clear_deadline)

    def test_explicit_when_wins_over_move_rules(self) -> None:
        # Out of P1 for a deadline-only task would set the start date to today.
        task = make_task(tags=["P1"], deadline=TODAY)
        change = plan_edit(task, TaskEdit(priority="P3", when_keyword="someday"), TODAY)
        self.assertIsNone(change.set_start_date)
        self.assertEqual(change.set_when, "someday")

    def test_someday_and_anytime_clear_the_deadline(self) -> None:
        for keyword in ("someday", "anytime"):
            with self.subTest(keyword=keyword):
                change = plan_edit(make_task(tags=["P1"], deadline=TODAY, start_date=TODAY),
                                   TaskEdit(when_keyword=keyword), TODAY)
                self.assertEqual(change.set_when, keyword)
                self.assertTrue(change.clear_deadline)

    def test_deferral_moves_earlier_deadline_to_new_start(self) -> None:
        friday = TODAY + timedelta(days=6)
        for deadline in (TODAY, YESTERDAY, TOMORROW):
            with self.subTest(deadline=deadline):
                change = plan_edit(make_task(tags=["P1"], deadline=deadline, start_date=TODAY),
                                   TaskEdit(when_date=friday), TODAY)
                self.assertEqual((change.set_start_date, change.set_deadline), (friday, friday))

    def test_deferral_leaves_later_or_missing_deadline_alone(self) -> None:
        later = TODAY + timedelta(days=10)
        for deadline in (later, TOMORROW, None):
            with self.subTest(deadline=deadline):
                change = plan_edit(make_task(tags=["P2"], deadline=deadline, start_date=TODAY),
                                   TaskEdit(when_date=TOMORROW), TODAY)
                self.assertIsNone(change.set_deadline)
                self.assertFalse(change.clear_deadline)

    def test_start_today_is_not_a_deferral(self) -> None:
        change = plan_edit(make_task(tags=["P1"], deadline=YESTERDAY), TaskEdit(when_date=TODAY), TODAY)
        self.assertIsNone(change.set_deadline)

    def test_explicit_deadline_wins_over_deferral(self) -> None:
        change = plan_edit(make_task(tags=["P1"], deadline=TODAY), TaskEdit(when_date=TOMORROW, deadline=TODAY), TODAY)
        self.assertEqual(change.set_deadline, TODAY)
        change = plan_edit(make_task(tags=["P1"], deadline=TODAY), TaskEdit(when_date=TOMORROW, clear_deadline=True), TODAY)
        self.assertTrue(change.clear_deadline)

    def test_deadline_set_in_same_edit_is_kept_with_someday(self) -> None:
        later = TODAY + timedelta(days=9)
        change = plan_edit(make_task(tags=["P2"], deadline=TODAY), TaskEdit(when_keyword="someday", deadline=later), TODAY)
        self.assertEqual(change.set_deadline, later)
        self.assertFalse(change.clear_deadline)

    def test_same_priority_is_not_a_move(self) -> None:
        self.assertIsNone(plan_edit(make_task(tags=["P2"]), TaskEdit(priority="P2"), TODAY))

    def test_other_tags_keep_priority_tag(self) -> None:
        change = plan_edit(make_task(tags=["Home", "P3"]), TaskEdit(other_tags=["Work"]), TODAY)
        self.assertEqual(change.tags, ["Work", "P3"])
        change = plan_edit(make_task(tags=["Home", "P3"]), TaskEdit(other_tags=[], priority="P2"), TODAY)
        self.assertEqual(change.tags, ["P2"])

    def test_clear_deadline_and_list_heading(self) -> None:
        change = plan_edit(
            make_task(tags=["P2"], deadline=TOMORROW),
            TaskEdit(clear_deadline=True, list_id="proj", heading_id="head"), TODAY,
        )
        self.assertTrue(change.clear_deadline)
        self.assertEqual((change.set_list_id, change.set_heading_id), ("proj", "head"))

    def test_unknown_when_keyword_rejected(self) -> None:
        with self.assertRaises(ValueError):
            plan_edit(make_task(), TaskEdit(when_keyword="evening"), TODAY)

    def test_new_fields_confirmed(self) -> None:
        task = Task(uuid="A1", title="T", notes="N", someday=True, list_id="L", heading_id="H")
        self.assertTrue(Change("A1", None, set_title="T", set_notes="N", set_when="someday",
                               set_list_id="L", set_heading_id="H").is_satisfied_by(task))
        self.assertFalse(Change("A1", None, set_when="anytime").is_satisfied_by(task))
        self.assertFalse(Change("A1", None, set_title="Other").is_satisfied_by(task))
        anytime = Task(uuid="A1", title="T")
        self.assertTrue(Change("A1", None, set_when="anytime").is_satisfied_by(anytime))
        self.assertFalse(Change("A1", None, set_when="anytime").is_satisfied_by(make_task(start_date=TODAY)))


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

    def test_later_deadline_kept_moving_into_or_out_of_p1(self) -> None:
        for tags, destination in ((["P2"], "P1"), (["P3"], "P1"), (["P1"], "P2"), (["P1"], "P3")):
            with self.subTest(tags=tags, destination=destination):
                task = make_task(tags=tags, deadline=TOMORROW, start_date=TODAY)
                change = plan_move(task, destination, TODAY)
                self.assertEqual(change.tags, [destination])
                self.assertIsNone(change.set_deadline)
                self.assertFalse(change.clear_deadline)
                self.assertIsNone(change.set_start_date)

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
            plan_move(make_task(), "P5", TODAY)


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
            update_order(order, "P2", ["B", "C"]), {"P1": ["A"], "P2": ["B", "C"], "P3": [], "P4": []}
        )

    def test_update_order_rejects_unknown_priority(self) -> None:
        with self.assertRaises(ValueError):
            update_order({}, "P9", [])

    def test_deadline_state(self) -> None:
        self.assertEqual(deadline_state(YESTERDAY, TODAY), "overdue")
        self.assertEqual(deadline_state(TODAY, TODAY), "today")
        self.assertEqual(deadline_state(TOMORROW, TODAY), "future")
        self.assertIsNone(deadline_state(None, TODAY))



class SequencePlaceTests(unittest.TestCase):
    """The "task N of M" place of a sequential project's started task."""

    def test_position_in_project_order_after_completed(self) -> None:
        tasks = [Task("A", "A", project_rank=(0, 0, 5)), Task("B", "B", project_rank=(0, 0, 1)),
                 Task("C", "C", project_rank=(1, 0, 0))]
        self.assertEqual(sequence_place(tasks, "A", 2), (4, 5))
        self.assertEqual(sequence_place(tasks, "B", 0), (1, 3))
        self.assertEqual(sequence_place(tasks, "C", 0), (3, 3))


class PredictTests(unittest.TestCase):
    """Predicting a task after an edit and the next refresh, and where it is listed."""

    def test_in_today(self) -> None:
        self.assertTrue(in_today(make_task(start_date=TODAY), TODAY))
        self.assertTrue(in_today(make_task(deadline=YESTERDAY), TODAY))
        self.assertFalse(in_today(make_task(start_date=TOMORROW, deadline=TOMORROW), TODAY))
        self.assertFalse(in_today(make_task(), TODAY))

    def test_predict_applies_change_then_refresh(self) -> None:
        task = make_task(tags=["P2", "Home"], start_date=TODAY)
        after = predict(task, Change("A1", None, set_deadline=TODAY), TODAY)
        self.assertEqual((after.deadline, sorted(after.tags)), (TODAY, ["Home", "P1"]))
        self.assertEqual(task.deadline, None)  # The original is unchanged.

    def test_predict_no_refresh_outside_today(self) -> None:
        task = make_task(tags=["P1"], start_date=TODAY, deadline=TODAY)
        after = predict(task, Change("A1", None, set_when="someday", clear_deadline=True), TODAY)
        self.assertEqual((after.start_date, after.deadline, after.someday, after.tags), (None, None, True, ["P1"]))

    def test_predict_undated_due_today_gets_start(self) -> None:
        after = predict(make_task(tags=["P2"]), Change("A1", None, set_deadline=TODAY), TODAY)
        self.assertEqual((after.start_date, after.tags), (TODAY, ["P1"]))

    def test_place_in_list(self) -> None:
        p2 = make_task(tags=["P2"], start_date=TODAY)
        self.assertEqual(place_in_list(p2, "today", TODAY), "P2")
        self.assertEqual(place_in_list(p2, "p2", TODAY), "list")
        self.assertIsNone(place_in_list(p2, "p1", TODAY))
        self.assertIsNone(place_in_list(p2, "overdue", TODAY))
        later = make_task(tags=["P1"], start_date=TOMORROW)
        self.assertIsNone(place_in_list(later, "today", TODAY))
        self.assertIsNone(place_in_list(later, "p1", TODAY))
        self.assertEqual(place_in_list(make_task(tags=["P1"], deadline=YESTERDAY), "overdue", TODAY), "list")
        with self.assertRaises(ValueError):
            place_in_list(p2, "inbox", TODAY)

    def test_prune_order(self) -> None:
        order = {"P1": ["a", "gone"], "P3": ["b"]}
        self.assertEqual(prune_order(order, ["a", "b"]), {"P1": ["a"], "P2": [], "P3": ["b"], "P4": []})


if __name__ == "__main__":
    unittest.main()
