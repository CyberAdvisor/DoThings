# Do Things

## Change log
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
- Drag a task to another priority to move it. The move replaces its P tags, and:
  - moving into P1 sets its deadline to today;
  - moving out of P1 removes its deadline, and if the task was in Today only because of its deadline (no start date, or one after today), sets its start date to today so it stays in Today;
  - moving between P2 and P3 leaves the deadline alone.
- Drag within a priority to reorder. The order is saved on your Mac in `task_order.json`.
- Shows deadline flags, red when overdue.
- Click a task to open it in Things for editing.
- The sidebar has Things' lists (Inbox, Today, Upcoming, Anytime, Someday, Logbook) and the searches P1, P2, P3 and Overdue.

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
| `common.py` | Paths, version, logging, read-only Things database access, Things URL commands, order file, auth token |
| `priority_check.py` | The priority and move rules, grouping and ordering (pure logic) |
| `serve.py` | Entry point: local server and JSON API |
| `debug_things.py` | Read-only diagnostic |
| `index.html` | The page: sidebar, task lists, drag-and-drop, token setup |
| `test_priority_check.py` | Tests for the rules |
| `test_common.py` | Tests for token handling, dates, URLs, the order file and database queries |
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
- The Logbook shows the most recent 200 entries.
- The custom searches are fixed (P1, P2, P3, Overdue). New ones are added in code.
- Each change waits up to 5 seconds for Things to confirm it, so moves take a moment.

## Customizing this with Claude
Start a new conversation with Claude, paste in `CLAUDE_CONTEXT.md` and `AGENTS.md`, and describe the change you want. Ask Claude to confirm the design and file list before writing code, to run the verification commands in `AGENTS.md`, and to follow the release checklist (version bump, change logs, commit, tag, release).
