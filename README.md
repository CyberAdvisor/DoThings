# Do Things

## Change log
- **v0.1.25 (2026-11-07):** Moving a task into or out of P1 keeps a deadline that is after today. Moving into P1 sets the deadline to today only when there is none; moving out of P1 removes it only when it is today or overdue.
- **v0.1.24 (2026-11-07):** The P1, P2 and P3 searches list only tasks that are in Today. A tagged task that starts later (for example, deferred to tomorrow) no longer shows in its search until its start date.
- **v0.1.23 (2026-11-07):** The P1, P2 and P3 searches also hide the P tag on each row (the search name already says it). Only the Overdue search, which mixes priorities, shows it.
- **v0.1.22 (2026-11-07):** In Today, task rows no longer show the P1, P2 or P3 tag, since the group they're in already shows the priority. The P1, P2, P3 and Overdue searches still show it.
- **v0.1.21 (2026-11-07):** The notes icon on a task row is now a page with a folded corner, matching Things.
- **v0.1.20 (2026-11-07):** New **Settings** at the bottom of the sidebar: replace the Things auth token, and choose **Dark** or **Light** appearance. Dark is the default (whatever your Mac is set to); the choice is remembered in your browser.
- **v0.1.19 (2026-11-07):** Task rows look like Things: rounded-square checkboxes, tags (P tags included) as outlined pills right after the title, gray icons for repeating tasks, notes and checklists, a start-date badge ("Mon", "Nov 14") for tasks starting later, and a filled flag reading "1 day ago", "today" or "2 days left" (red when today or overdue).
- **v0.1.18 (2026-11-07):** Fixed: unchecking a task in a sequential project didn't undo the next task Do Things had started, because Things moves a reopened task to the bottom of the project. Do Things now remembers which task's completion started the next one and undoes it whenever that task is opened again; the reopened task then counts as the one in progress, so nothing else is started.
- **v0.1.17 (2026-11-07):** In a sequential project, if you uncheck a completed task after Do Things has started the next one, that next task goes back to undated (Anytime, without its P tag). Only tasks Do Things started itself are undone, and not if you've changed their date since. Do Things remembers them in `sequence_pulls.json`.
- **v0.1.16 (2026-11-07):** Sequential projects now work forwards instead of hiding tasks: the project's first task with no start date and no deadline gets a start date of today and appears in Today; when it is checked off, the next one does. Tasks in the project that already have a start date or deadline follow their own dates. Someday tasks are skipped.
- **v0.1.15 (2026-11-07):** Within each priority group, tasks from the same project follow the order you set in that project in Things. Projects tagged **Sequential** in Things show only their next open task in Today (top to bottom, across headings); a later task still shows if it is due today or overdue. Today's sidebar counts match what Today shows.
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
  - moving into P1 sets its deadline to today if it has none (a later deadline is kept);
  - moving out of P1 removes a deadline of today or earlier (a later deadline is kept; an overdue one has to go, or the task would return to P1), and if the task was in Today only because of that deadline (no start date, or one after today), sets its start date to today so it stays in Today;
  - moving between P2 and P3 leaves the deadline alone.
- Drag within a priority to reorder. The order is saved on your Mac in `task_order.json`. Tasks you haven't ordered here follow Things' Today order, except that tasks from the same project keep the order you set in that project in Things.
- **Sequential projects:** tag a project `Sequential` in Things (create the tag once in Window › Tags) to work it in order. On each refresh, the project's first task (in Things' project order, across headings) with no start date and no deadline gets a start date of today, so it appears in Today. Nothing else is pulled in while it is open; when it is checked off, the next undated task is. Tasks that already have a start date or a deadline follow their own dates, and Someday tasks are skipped. If the task whose completion started the next one is opened again (for example you uncheck it), the task Do Things started goes back to undated (Anytime, without its P tag), unless you've changed its date since. The reopened task is then the one in progress, even though Things moves it to the bottom of the project.
- Check a task's box to complete it in Things. It stays in its group, dim gray and struck through at the bottom, until the end of the day (tick **Hide Completed** under the searches to hide these everywhere; the setting is remembered). Uncheck it to reopen it. Completed tasks can't be dragged, and the priority rules leave them alone. Checking works even while a P tag is missing.
- Rows look like Things: tags as outlined pills after the title (the P1–P3 tag only in the Overdue search; elsewhere the group or search already shows the priority), gray icons for repeating tasks, notes and checklists, a start-date badge for tasks starting later, and the deadline as "1 day ago", "today" or "2 days left" (red when today or overdue).
- Click a task to edit it in place: title, notes, tags, When (Today, a date, Anytime or Someday), deadline (both picked from a calendar; choosing Someday or Anytime also removes the deadline; **Tomorrow** on the When line defers the start to tomorrow; deferring to any later date moves a deadline that is before it to that date), project or area and heading, and priority. Empty fields are added with the **+** buttons. **Save** sends everything to Things as one change and closes the card once Things confirms it; **Cancel** (or Escape) discards it. Changing the priority follows the drag rules, but a deadline you set in the card wins. **Open in Things** in the card opens the task in Things; if the task has a checklist, its progress is shown beside it (edit the checklist in Things). While a card is open, the list doesn't refresh and tasks can't be dragged.
- The sidebar shows Today and the searches P1, P2, P3 and Overdue in Do Things. The P1, P2 and P3 searches show the tasks in Today with that tag; Overdue shows every open task past its deadline. Inbox, Upcoming, Anytime, Someday and Logbook (marked ↗) open that list in Things. As in Things, Inbox shows its item count and Today shows a red badge of tasks due today or overdue followed by the number of other open tasks.
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

To change the token later, open **Settings** at the bottom of the sidebar and click **Replace token…**. Settings also switches the appearance between **Dark** (the default) and **Light**. If Things ever fails to confirm a change, Do Things shows a warning with a button to re-enter the token.

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
| `sequence_pulls.json` | The task Do Things started in each sequential project, so it can be undone (untracked) |
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
