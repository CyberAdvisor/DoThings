# Context for Claude: Do Things

Paste this into a new conversation, together with `AGENTS.md`, before asking for changes. It records the design and the gotchas so they don't have to be rediscovered.

## What this is
A local web front end to Things 3. `serve.py` (Python standard library, 3.9) serves `index.html` at `http://127.0.0.1:8765`. It reads the Things SQLite database read-only and changes tasks through `things:///update` URLs using the user's auth token. The Today list is shown in three priority groups based on the tags P1 (Due Today), P2 (To Do) and P3 (Follow Up).

## Rules (the core of the app)
On every list refresh (page load, window focus, every 60 seconds), each Today task is checked in this order:
1. Overdue or due today → P1.
2. Several P tags → keep the highest.
3. No P tag → P2.

Refresh changes never touch deadlines.

Manual moves:
- All P tags are replaced with the destination tag.
- Into P1 → the deadline is set to today.
- Out of P1 → the deadline is cleared. If the task is in Today only because of its deadline (no start date, or one after today), its start date is also set to today (`when=YYYY-MM-DD`), so it stays in Today.
- P2 ↔ P3 → the deadline is unchanged.

The "source" priority of a move is `required_priority` (what the rules say), not just the current tag. So an overdue task still tagged P2 counts as P1, and moving it to P2 clears its deadline.

Without the start-date step, clearing the deadline of a deadline-only task would drop it out of Today. Keep `set_start_date` in `plan_move`.

## Data model
- `Task`: uuid, title, tags, start_date, deadline, context (project or area title).
- `Change`: task_id, the full `tags` list, `set_deadline` or `clear_deadline`, and optionally `set_start_date`. `is_satisfied_by(task)` is how a write is confirmed.
- `task_order.json`: `{"P1": [ids], "P2": [ids], "P3": [ids]}`. Ids not listed appear after the listed ones, in Things' `todayIndex` order. `update_order` removes moved ids from other groups so an id is never listed twice.

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
- Tags: `TMTaskTag(tasks, tags)` joins `TMTag(uuid, title)`. Tag titles are concatenated with `char(31)` because titles can contain commas.
- Today = open to-dos with `start` in (1, 2) and `startDate <= today`, plus tasks with `deadline <= today` (excluding those with `deadlineSuppressionDate` set, when that column exists).
- Every list shows open to-dos plus those completed since local midnight (`status` 3 and `stopDate` ≥ midnight; `stopDate` is Unix time). They come back as `Task.completed_at`, are sorted after open tasks (`completed_last`, oldest completion first), are skipped by the refresh rules, and can't be moved. Canceled to-dos are never shown.
- Task reads also return `notes`, Someday state (`start` 2 with no `startDate`), `list_id` (`COALESCE(t.project, heading's project, t.area)`) and `heading_id`. A to-do under a heading has `heading` set and `project` NULL.
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
- `HTTPServer` is single-threaded on purpose, so writes to Things and to the order file never overlap.
- Starting `serve.py` when port 8765 is already in use just opens the page and exits. The Shortcut relies on this.
- Request checks: the Host header must be `127.0.0.1:8765` or `localhost:8765`, and POSTs need `X-Do-Things: 1`.
- Writes stop at the first failure in a refresh, so a bad token costs one 5-second wait per refresh, not one per task.
- `index.html` builds task rows with `textContent`. Keep it that way: task titles are user data.
- Drag-and-drop uses HTML5 drag events. The insert position is found from row midpoints, and the page does not refresh during a drag or a save (`state.drag` and `state.busy`).
