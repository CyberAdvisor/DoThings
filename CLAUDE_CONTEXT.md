# Context for Claude: Do Things

Paste this into a new conversation, together with `AGENTS.md`, before asking for changes. It records the design and the gotchas so they don't have to be rediscovered.

## What this is
A local web front end to Things 3. `serve.py` (Python standard library, 3.9) serves `index.html` at `http://127.0.0.1:8765`. It reads the Things SQLite database read-only and changes tasks through `things:///update` URLs using the user's auth token. The Today list is shown in three priority groups based on the tags P1 (Due Today), P2 (To Do) and P3 (Follow Up).

## Rules (the core of the app)
On every list refresh (page load, window focus, every 60 seconds), each Today task is checked in this order:
1. Overdue or due today → P1.
2. Several P tags → keep the highest.
3. No P tag → P2.
4. No start date (Inbox, Anytime or Someday) and due today or overdue → start date set to today (`when=YYYY-MM-DD`), so it is in Things' own Today too. Combined with any retag into one change.

Refresh changes never touch deadlines.

Editor: choosing Someday or Anytime for When also clears the deadline (`plan_edit`), unless the same edit sets one. Deferring the start to a date after today moves a deadline that is before that date to it (so the task leaves Today), unless the same edit sets or clears the deadline; The page doesn't apply these rules: each date or priority choice asks `POST /api/edit/preview`, which runs `plan_edit` and `predict` (the change, then the refresh rules if the task is in Today) and returns the resulting When, deadline and priority, the row (`task_to_json`) and its place in the list being shown (`place_in_list`: a Today group, "list" in a search, or null). Save fetches a final preview and puts that row in place before the write is confirmed (v0.1.27). A deadline chosen in the card is sent with a When change even if unchanged, so the defer rule doesn't move it.

Manual moves:
- All P tags are replaced with the destination tag.
- A deadline after today is kept on every move (v0.1.25).
- Into P1 → a missing deadline is set to today.
- Out of P1 → a deadline of today or earlier is cleared (an overdue one must go, or the refresh rules put the task straight back in P1). If the task is in Today only because of its deadline (no start date, or one after today), its start date is also set to today (`when=YYYY-MM-DD`), so it stays in Today.
- P2 ↔ P3 → the deadline is unchanged.

The "source" priority of a move is `required_priority` (what the rules say), not just the current tag. So an overdue task still tagged P2 counts as P1, and moving it to P2 clears its deadline.

Without the start-date step, clearing the deadline of a deadline-only task would drop it out of Today. Keep `set_start_date` in `plan_move`.

## Data model
- `Task`: uuid, title, tags, start_date, deadline, context (project or area title).
- `Change`: task_id, the full `tags` list, `set_deadline` or `clear_deadline`, and optionally `set_start_date`. `is_satisfied_by(task)` is how a write is confirmed.
- `task_order.json`: `{"P1": [ids], "P2": [ids], "P3": [ids]}`. Every list request drops ids no longer in Today (`prune_order`) and saves only if something was dropped. Ids not listed appear after the listed ones, in Things' `todayIndex` order. `update_order` removes moved ids from other groups so an id is never listed twice.

## Things database facts
- Reading it needs Full Disk Access for Terminal. Without it, macOS silently blocks access ("Operation not permitted") and the database is reported as not found.
- Location: `~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*/Things Database.thingsdatabase/main.sqlite`. Older versions have no `ThingsData-*` folder. Both layouts are searched, and the newest file wins.
- `TMTask`:
  - `type` 0 = to-do.
  - `status` 0 open, 2 canceled, 3 completed.
  - `start` 0 Inbox, 1 Anytime, 2 Someday.
  - `trashed`.
  - A to-do keeps `status` 0 and `trashed` 0 when its project or heading is trashed, completed or canceled, so queries also check the project (`project`), heading (`heading`) and heading's project. Trashed parents hide to-dos from every list; closed parents hide them from open lists.
  - `startDate` and `deadline` are packed ints (`year<<16 | month<<12 | day<<7`).
  - `todayIndex` gives the Today order.
  - `rt1_recurrenceRule` is non-null on repeating templates, which are excluded.
- Project order: `TMTask."index"` is a to-do's manual position in its project or heading; headings have their own `index` in the project, and unheaded to-dos come first (`Task.project_rank`). `in_project_order` fills each project's Today slots in project order; the saved Do Things order (`task_order.json`) still wins.
- Sequential projects: a project tagged `Sequential` (`SEQUENTIAL_TAG`). `read_sequential_projects` reads each one's open to-dos across the whole project. The task in progress (`sequence_next`) is the first, in project order, with no deadline, not Someday, and no start date or one of today or earlier. If it has no start date, `plan_sequence` sets it to today; the refresh does this before the Today rules, so the task is also tagged P2 in the same refresh. Nothing is hidden (v0.1.15 hid tasks; replaced in v0.1.16).
- Undo (v0.1.17, reworked v0.1.18): `serve.step_sequences` records each started task as a `Pull` (task, date given, `after` = the project's most recently completed task, `read_last_completed`) in `sequence_pulls.json`. Things moves a completed-then-reopened task to the bottom of the project (its `index` changes), so project order can't detect an unchecked task. While a recorded task is open with its date it is in progress and nothing else is started. When its `after` task is open again, `plan_sequence_undo` sends it back to Anytime and the reopened task is recorded as in progress (with no `after`, so it is never undone). Records from v0.1.17 have no `after` and are never undone. The undo sends `when=anytime` and removes the task's P tags (`tags=` with the remaining tags, possibly empty). `find_pulled` drops the record if the task was completed or its start date no longer matches (the user changed it), so user-dated tasks are never undone. Tests patch the record path into their temporary folder.
- Rows mirror Things (v0.1.19): `task_to_json` sends the tags, leaving out P tags except in the lists in `PRIORITY_TAG_LISTS` (only Overdue; Today's groups and the P1–P3 searches already show the priority), `deadline_label` ("N days ago" / "today" / "N days left"), `start_label` (weekday within a week, else "Nov 14"; only for later starts), `has_notes`, `has_checklist`, `repeating` (`rt1_repeatingTemplate` set). The editor's tag list is `other_tags` (no P tags; priority is separate). Tag order is the database's, not Things' tag order.
- Checklists: `TMChecklistItem(task, status)`; status other than 0 (completed or canceled) counts as done. Shown read-only as progress in the editor.
- "Hide Completed" (sidebar checkbox, saved in the browser's localStorage as `dothings.hideCompleted`) adds `hide_completed=1` to `/api/list`, which drops today's completed tasks from the list but not from the counts.
- Sidebar counts come with every list response: Inbox = open, untrashed to-dos with `start` 0; Today: red badge = open tasks due today or overdue, gray number = the other open Today tasks (`today_counts`: `due`, `not_due`), as in Things.
- Tags: `TMTaskTag(tasks, tags)` joins `TMTag(uuid, title)`. Tag titles are concatenated with `char(31)` because titles can contain commas.
- Today = open to-dos with `start` in (1, 2) and `startDate <= today`, plus tasks with `deadline <= today` (excluding those with `deadlineSuppressionDate` set, when that column exists).
- Every list shows open to-dos plus those completed since local midnight (`status` 3 and `stopDate` ≥ midnight; `stopDate` is Unix time). They come back as `Task.completed_at`, are sorted after open tasks (`completed_last`, oldest completion first), are skipped by the refresh rules, and can't be moved. Canceled to-dos are never shown.
- Task reads also return `notes`, Someday state (`start` 2 with no `startDate`), `list_id` (`COALESCE(t.project, heading's project, t.area)`) and `heading_id`. A to-do under a heading has `heading` set and `project` NULL.
- The P1–P3 searches are Today (`_TODAY_CLAUSE`) plus the tag, so a tagged task starting later isn't listed until it starts (v0.1.24). Overdue is any open task with a deadline before today.
- Do Things only queries Today and the searches (`APP_LISTS`). Inbox, Upcoming, Anytime, Someday and Logbook open in Things with `things:///show?id=<list>` (no token needed).

## Things URL scheme gotchas
- `tags=` replaces all tags, so always send the full list. Tags are comma-separated, and a tag containing a comma cannot be written, so it is refused.
- Tags that don't exist in Things are silently ignored. That's why the P1–P3 tags must exist (the UI warns) and why every write is confirmed by re-reading the database.
- A wrong auth token also fails silently. The only symptom is that the change never appears, which is reported as `write_failed`.
- Unknown tags are dropped silently, so while P1, P2 or P3 is missing Do Things sends no writes (refresh skipped, moves to a missing priority refused with instructions). Otherwise a missing tag shows up as an unconfirmed write, which looks like a token problem.
- The inline editor (`GET /api/task`, `POST /api/edit`) sends one update built by `plan_edit`: only changed fields; a priority change uses the move rules, and an explicit deadline or When wins. Allowed values are checked against Things' data (`read_edit_options`). `title`, `notes`, `when` (date, `anytime`, `someday`), `list-id` (project or area) and `heading-id` are sent. Things' URL command can't remove a to-do from a project/area/heading, delete it, or edit checklists safely (replacing resets ticks), so the editor doesn't offer those.
- Things' URL docs say `when`, `deadline` and `completed` "cannot be updated on repeating to-dos". That means the repeating template (never shown, since `rt1_recurrenceRule` rows are excluded): on 2026-11-07 a real copy in Today accepted `when=<date>`. v0.1.7 wrongly locked copies; v0.1.8 removed that.
- `completed=true` / `completed=false` completes or reopens a to-do. `Change.tags` is None for these, so no `tags=` is sent and the tags are left alone.
- `deadline=` with an empty value clears the deadline. `when=YYYY-MM-DD` sets the start date.
- Commas between tags are sent unencoded and spaces as `%20`, matching Things' documented format.

## Architecture notes
- A browser that disconnects mid-request raises `ConnectionError` while the reply is sent. `Handler.handle` ignores it, and `_run` sends the reply outside its `try` so it isn't logged as a Things read error.
- The page updates optimistically: drags, reorders, check-offs and edit saves change the DOM first, then `enqueue` sends the request. Requests run one at a time in order (`saveQueue`); rows are dimmed (`.saving`) and not draggable until confirmed, opening the editor waits for pending changes, and the list isn't refreshed until the queue is empty. Then `load()` redraws from Things, which undoes anything Things didn't apply. `load()` checks again after its request returns and doesn't draw over an editor, drag or change started meanwhile (a refresh can take seconds when it writes).
- Do Things' Today ignores `deadlineSuppressionDate` (v0.1.29): Things keeps a due task out of its own Today once the user removes it, but Do Things always lists what is due, and refresh rule 4 then gives an undated one a start date of today (which puts it back in Things' Today; chosen by the user).
- Sequential marker (v0.1.28): `sequence_labels` gives each task a sequential project started (a `sequence_pulls.json` record that `find_pulled` still matches) the label "task N of M" (`sequence_place`): N = completed to-dos in the project (`count_completed`, headings included) + the task's position among the open ones in project order (v0.1.29; v0.1.28 used + 1), M = completed + open. `task_to_json` sends it as `sequence`; the page shows it after the project name. The edit preview keeps it only if the edit leaves the start date and project unchanged.
- Refresh pause (v0.1.27): when `apply_refresh_rules` reports an unconfirmed write, `RefreshPause.paused` is set and later refreshes skip the rules; the list response's `refresh_paused` drives the red bar. Cleared by `POST /api/refresh/retry`, a new token, or a server restart. Manual writes are always tried.
- `errors.log` uses a `RotatingFileHandler` (1 MB, one backup).
- `HTTPServer` is single-threaded on purpose, so writes to Things and to the order file never overlap.
- Starting `serve.py` when port 8765 is already in use just opens the page and exits. The Shortcut relies on this.
- Request checks: the Host header must be `127.0.0.1:8765` or `localhost:8765`, and POSTs need `X-Do-Things: 1`.
- Writes stop at the first failure in a refresh, so a bad token costs one 5-second wait per refresh, not one per task.
- `index.html` builds task rows with `textContent`. Keep it that way: task titles are user data.
- Drag-and-drop uses HTML5 drag events. The insert position is found from row midpoints, and the page does not refresh during a drag or a save (`state.drag` and `state.busy`).
