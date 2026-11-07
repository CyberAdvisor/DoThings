# Do Things

## Change log
- **v0.1.14 (2026-11-07):** Deferring a task's start to a later date (with **Tomorrow** or the calendar) also moves its deadline to that date if the deadline was earlier, so a deferred task leaves Today. A deadline you set in the same edit is kept.
- **v0.1.13 (2026-11-07):** Moving, reordering, checking off and saving edits now show on the page immediately; Things confirms them in the background (the task is dimmed until it does). If Things doesn't apply a change, the list goes back to Things' real state and shows what to check. The editor's When line has a **Tomorrow** button that defers the start to tomorrow without changing the deadline.
- **v0.1.12 (2026-11-07):** Today's gray count now shows only the tasks that aren't due, as in Things (the red badge counts the due ones). The Hide Completed checkbox is the same round circle as the task checkboxes.
- **v0.1.11 (2026-11-07):** A **Hide Completed** checkbox under the searches hides tasks checked off today in every view; unchecking it shows them again. The setting is remembered in your browser.
- **v0.1.10 (2026-11-07):** The sidebar shows counts like Things: the number of Inbox items, and for Today a red badge of tasks due today or overdue plus the total open. The editor shows a task's checklist progress (e.g. "Checklist: 1 of 3 done") next to Open in Things.
- **v0.1.9 (2026-11-07):** A task with no start date (in the Inbox, Anytime or Someday) that is due today or overdue now gets a start date of today on the next refresh, so it is in Things' own Today too. In the editor, choosing Someday or Anytime for When also removes the deadline.
- **v0.1.8 (2026-11-07):** When and Deadline open a date picker in the editor: a calendar plus Today, Someday and Anytime (When) or Today and Clear (Deadline). Copies of repeating to-dos are no longer locked; their When and deadline can be changed like any task.
- **v0.1.7 (2026-11-07):** Click a task to edit it in place, like Things: title, notes, tags, When, deadline, project or area and heading, and priority, with Save and Cancel. Empty fields are added with the buttons at the bottom of the card. **Open in Things** is now in the card. Copies of repeating to-dos can't have their When or deadline changed from Do Things.
- **v0.1.6 (2026-11-07):** Every task in Today and the P1, P2, P3 and Overdue searches has a checkbox. Checking it completes the task in Things and shows it dim gray and struck through at the bottom of its group until the end of the day; unchecking reopens it. Warning messages after a failed move or check now stay visible.
- **v0.1.5 (2026-11-07):** Inbox, Upcoming, Anytime, Someday and Logbook now open in Things instead of in Do Things (marked with an arrow in the sidebar). While a P tag is missing in Things, Do Things changes no tags and explains step by step how to create them, instead of reporting a token problem. The token warning now lists what to check, in order. Browser disconnects no longer print errors in Terminal or `errors.log`.
- **v0.1.4 (2026-11-07):** Pushing a new version to `main` now creates its `vX.Y.Z` tag and GitHub release automatically, with the commit message as the release notes. `.gitignore` now also ignores Python's `__pycache__/` folder.
- **v0.1.3 (2026-11-07):** Added the missing `.gitignore`, so the auth token, the saved task order and the logs can't be committed by accident.
- **v0.1.2 (2026-11-07):** To-dos inside a trashed project or heading no longer appear, and the Today, Inbox, Anytime, Upcoming, Someday, P1–P3 and Overdue lists no longer show to-dos whose project or heading is completed or canceled. Setup now covers giving Terminal Full Disk Access, which reading the Things database requires.
- **v0.1.1 (2026-11-07):** Moving a task out of P1 that is in Today only because of its deadline now also sets its start date to today, so it stays in Today.
- **v0.1.0 (2026-11-07):** First release. A Today view grouped into P1 Due Today, P2 To Do and P3 Follow Up, with automatic tagging, drag-and-drop between and within priorities, the Things sidebar lists, P1/P2/P3/Overdue searches, opening tasks in Things, and first-run auth-token setup.

## Why this exists
Things 3's Today list is a single flat list. Do Things shows the same tasks split into three priorities, keeps the priority tags and deadlines consistent automatically, and lets you reprioritize by dragging.

## What it does
- Shows your Things Today list in three groups, based on the tags `P1`, `P2` and `P3`:
  - **P1 Due Today**
  - **P2 To Do**
  - **P3 Follow Up**
- Applies these rules every time the list refreshes (page load, window focus, every 60 seconds):
  1. A task that is overdue or due today is tagged P1.
  2. A task with more than one P tag keeps only the highest.
  3. A Today task with no P tag is tagged P2.
  4. A task with no start date (Inbox, Anytime or Someday) that is due today or overdue gets a start date of today.
- Drag a task to another priority to move it. The move replaces its P tags, and:
  - moving into P1 sets its deadline to today;
  - moving out of P1 removes its deadline, and if the task was in Today only because of its deadline (no start date, or one after today), sets its start date to today so it stays in Today;
  - moving between P2 and P3 leaves the deadline alone.
- Drag within a priority to reorder. The order is saved on your Mac in `task_order.json`.
- Check a task's box to complete it in Things. It stays in its group, dim gray and struck through at the bottom, until the end of the day (tick **Hide Completed** under the searches to hide these everywhere; the setting is remembered). Uncheck it to reopen it. Completed tasks can't be dragged, and the priority rules leave them alone. Checking works even while a P tag is missing.
- Shows deadline flags, red when overdue.
- Click a task to edit it in place: title, notes, tags, When (Today, a date, Anytime or Someday), deadline (both picked from a calendar; choosing Someday or Anytime also removes the deadline; **Tomorrow** on the When line defers the start to tomorrow; deferring to any later date moves a deadline that is before it to that date), project or area and heading, and priority. Empty fields are added with the **+** buttons. **Save** sends everything to Things as one change and closes the card once Things confirms it; **Cancel** (or Escape) discards it. Changing the priority follows the drag rules, but a deadline you set in the card wins. **Open in Things** in the card opens the task in Things; if the task has a checklist, its progress is shown beside it (edit the checklist in Things). While a card is open, the list doesn't refresh and tasks can't be dragged.
- The sidebar shows Today and the searches P1, P2, P3 and Overdue in Do Things. Inbox, Upcoming, Anytime, Someday and Logbook (marked ↗) open that list in Things. As in Things, Inbox shows its item count and Today shows a red badge of tasks due today or overdue followed by the number of other open tasks.
- If the P1, P2 or P3 tag doesn't exist in Things, Do Things changes no tags and shows how to create them.

Do Things reads the Things database read-only and makes every change through Things' own URL commands. Each change is only treated as done once Things' database shows it.

## 1. Requirements
- macOS with Things 3 (latest version).
- The macOS Command Line Tools Python: `/Library/Developer/CommandLineTools/usr/bin/python3` (Python 3.9 or later). No other software is needed.

## 2. Create the priority tags in Things
In Things, create three tags named exactly `P1`, `P2` and `P3`. Things ignores tags that don't exist, so Do Things cannot assign them until they do. Do Things shows a warning if any are missing.

## 3. Get the code
```
git clone https://github.com/CyberAdvisor/DoThings.git ~/Documents/Projects/DoThings
```

## 4. First run and the auth token
1. Start Do Things (see section 5). It opens `http://127.0.0.1:8765` in your browser.
2. The first time, it shows a setup screen. In Things, choose **Things › Settings › General**, turn on **Enable Things URLs**, click **Manage**, and copy the authorization token.
3. Paste it into the setup screen and click **Save**. It is stored in `auth_token.txt`, readable only by your account and never committed to git.

To change the token later, click **Things auth token…** at the bottom of the sidebar. If Things ever fails to confirm a change, Do Things shows a warning with a button to re-enter the token.

Before the first run, give Terminal **Full Disk Access**: **System Settings › Privacy & Security › Full Disk Access**, turn on **Terminal** (add it with **+** if it isn't listed), then quit and reopen Terminal. Without it, macOS blocks reading the Things database without asking: `debug_things.py` reports "Things database not found", and `ls` on the Things folder shows "Operation not permitted". Turning on the toggle may ask for an administrator password.

## 5. Test manually before automating
```
cd ~/Documents/Projects/DoThings
/Library/Developer/CommandLineTools/usr/bin/python3 debug_things.py
/Library/Developer/CommandLineTools/usr/bin/python3 serve.py
```
- `debug_things.py` changes nothing. It shows the database location, checks that the database has the expected layout, lists any missing P tags, and prints every Today task with the change the rules would make.
- `serve.py` starts the server and opens the page. Press Ctrl-C to stop it.

## 6. Project location and development workflow
- Folder: `~/Documents/Projects/DoThings`. It is the only copy, used for editing, testing and running.
- Clone: `git clone https://github.com/CyberAdvisor/DoThings.git ~/Documents/Projects/DoThings`
- Workflow: edit → test (see the verification commands in `AGENTS.md`) → commit → push.
- Releases: bump `VERSION` and push to `main`. The `Release` GitHub Action then creates the `vX.Y.Z` tag on that commit and a GitHub release titled with the commit subject, using the commit message body as the notes. Pushes that don't change `VERSION` create nothing. Don't create the tag by hand, or the action will skip that version's release.

## 7. Start with Shortcuts
Do Things is a server that keeps running while you use it, so the shortcut starts it in the background.
1. In Shortcuts, create a shortcut named **Do Things** with one **Run Shell Script** action:
   ```
   cd ~/Documents/Projects/DoThings && nohup /Library/Developer/CommandLineTools/usr/bin/python3 serve.py >> run.log 2>&1 &
   ```
   If the server is already running, this just opens the page.
2. Optional: to start it automatically, add a Personal Automation (for example **Time of Day**, **Daily**, with **Ask Before Running** off) that runs the **Do Things** shortcut.

To stop the server: `lsof -ti tcp:8765 | xargs kill`

## Files
| File | Purpose |
|---|---|
| `README.md` | This guide |
| `AGENTS.md` | Rules and checks for contributors and AI agents |
| `CLAUDE_CONTEXT.md` | Primer for a fresh Claude conversation: data model, architecture, gotchas |
| `LICENSE` | MIT license |
| `VERSION` | Project version |
| `.gitignore` | Keeps logs, the order file and the token out of git |
| `requirements.txt` | States that only the standard library is used |
| `.github/workflows/release.yml` | GitHub Action that tags and releases each new version pushed to `main` |
| `common.py` | Paths, version, logging, read-only Things database access, Things URL commands, order file, auth token |
| `priority_check.py` | The priority and move rules, grouping and ordering (pure logic) |
| `serve.py` | Entry point: local server and JSON API |
| `debug_things.py` | Read-only diagnostic |
| `index.html` | The page: sidebar, task lists, drag-and-drop, token setup |
| `test_priority_check.py` | Tests for the rules |
| `test_common.py` | Tests for token handling, dates, URLs, the order file and database queries |
| `test_serve.py` | Tests for the server: missing-tag guards, opening Things lists, browser disconnects |
| `errors.log`, `run.log` | Runtime logs (untracked) |
| `task_order.json` | Saved order within each priority (untracked) |
| `auth_token.txt` | Things auth token, owner-only permissions (untracked) |

## Safety notes
- The Things database is opened read-only; all changes go through Things' URL commands.
- A change counts as done only after it appears in the database. The saved order is updated only after a move is confirmed.
- If a change is not confirmed, the refresh stops writing for that round, logs the failure and shows a warning, so a wrong token doesn't trigger a stream of failed writes.
- Tags are written as a full list, so non-priority tags are kept. A tag containing a comma can't be written safely through the URL command, so such a task is logged and skipped.
- The server only listens on `127.0.0.1`, only accepts requests addressed to itself, and only accepts writes carrying a header that other websites cannot add.
- The auth token is never written to logs.

## Limitations
- Things' database layout isn't documented and could change with a Things update. `debug_things.py` reports missing columns.
- Only to-dos are shown, not projects or headings.
- Today membership is worked out from start dates and deadlines. It may differ slightly from Things in edge cases, such as tasks inside a project that is itself scheduled later.
- The custom searches are fixed (P1, P2, P3, Overdue). New ones are added in code.
- Changes show immediately but are confirmed with Things in the background, one at a time; while one is pending, that task can't be dragged or opened, and a change Things doesn't apply within 5 seconds is undone on the page.
- The editor can't delete a task, edit its checklist, change repeat settings or attachments, or take a task out of a project, area or heading. Use **Open in Things** for those.

## Customizing this with Claude
Start a new conversation with Claude, paste in `CLAUDE_CONTEXT.md` and `AGENTS.md`, and describe the change you want. Ask Claude to confirm the design and file list before writing code, to run the verification commands in `AGENTS.md`, and to follow the release checklist (version bump, change logs, commit, tag, release).
