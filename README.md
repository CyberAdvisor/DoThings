# Do Things

## Change log
- **v1.0.0 (2026-11-07):** Do Things uses your Mac's own time zone for "today" instead of Mountain Time, so it works wherever you are. The sidebar has a title, **Do Things**, with the tagline "Getting Things Done in Things", and the version at the bottom of the sidebar opens this guide. **Security fix:** if Do Things couldn't hand a change to Things (the `open` command failed or timed out), the line it wrote to `errors.log` included your Things auth token. It now records only what went wrong. If your `errors.log` contains lines starting "Could not open Things URL", delete the file; to be thorough, also replace the token in Things (Things › Settings › General › Manage) and save the new one in Do Things' Settings. The README is rewritten for people downloading Do Things: why it exists, a screenshot of Today, its advantages over Things, installing from a release, running it from a shortcut, cloning it to change it, and reporting problems.
- **v0.1.29 (2026-11-07):** A task due today or overdue always shows in Do Things' Today, even if you removed it from Things' Today; the usual rule then gives it a start date of today, so it is back in Things' Today too. The sequential marker's first number is now the task's place in the project's order (completed tasks plus its position among the open ones), not just completed tasks plus one.
- **v0.1.28 (2026-11-07):** A task started by a sequential project shows its place after the project name, for example "Seq Project · task 2 of 5" (completed tasks plus its position among the open ones in project order, of completed plus open tasks in the project). The marker goes once the task is completed or its date is changed.
- **v0.1.27 (2026-11-07):** When you save an edit, the task shows its new deadline, start badge and group straight away, or leaves the list at once if it no longer belongs there (it stays dimmed until Things confirms). While editing, the dates and priority shown are worked out by Do Things' server, the same way the save will be. If Things doesn't apply an automatic update, Do Things pauses automatic updates and shows a red bar with the checks to make and a **Retry** button, instead of retrying and logging every minute. `errors.log` is capped at 1 MB (the previous one is kept as `errors.log.1`). The saved order forgets tasks that have left Today.
- **v0.1.26 (2026-11-07):** Fixed: **+ Deadline** and **+ When** in the editor did nothing. The calendar opened and closed again on the same click.
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
Things 3 is good at capturing and organizing everything you might do. Do Things is for the other half of the job: doing it.

It is a companion view for your Things Today list. It sorts today's tasks into three priorities:
- **P1 Due Today:** must be done today.
- **P2 To Do:** today's planned work.
- **P3 Follow Up:** waiting on someone, or to check on.

You work from the top down. Reprioritizing is a drag. The housekeeping that usually eats into the day is done for you: tagging, deadlines, and starting the next step of a project.

Everything stays in Things. Do Things holds no tasks of its own. It reads your Things data and makes every change through Things itself, so Things on your Mac, iPhone and iPad shows the same tasks with the same tags and dates.

## What it does
![Do Things' Today screen: tasks grouped into Due Today, To Do and Follow Up, with "Reserve hotel" started by the sequential Vacation project as task 2 of 5](screenshots/today.png)

*Today in Do Things, with sample data. "Reserve hotel" is the next step of the sequential **Vacation** project (task 2 of 5; "Book flights" is done). "Water the plants" was checked off today.*

- **Today in three priorities.** Today's tasks are grouped by their `P1`, `P2` and `P3` tags. Within each group you set the order by dragging. Tasks you haven't ordered follow Things' Today order, and tasks from the same project keep their order from that project.
- **Priority rules kept for you.** On every refresh (page load, returning to the window, and every 60 seconds):
  1. A task due today or overdue is tagged P1.
  2. A task with more than one P tag keeps only the highest.
  3. A Today task with no P tag is tagged P2.
  4. A task with no start date that is due today or overdue gets a start date of today, so it is in Things' Today too.
- **Move tasks between priorities.** Dragging a task to another group replaces its P tag.
  - **Moving into P1** gives it a deadline of today if it has none.
  - **Moving out of P1** removes a deadline of today or earlier. If the task was in Today only because of that deadline, it gets a start date of today so it stays in Today.
  - **A deadline after today** is always kept.
- **Sequential projects.** Tag a Things project `Sequential` and Do Things brings its tasks into Today one at a time, in project order. When you check one off, the next one starts. Each such task shows its place, for example "Seq Project · task 2 of 5". If you uncheck a task, the task it started goes back.
- **Searches.** P1, P2, P3 and Overdue in the sidebar. The P searches show today's tasks with that tag; Overdue shows every open task past its deadline. **Hide Completed** hides tasks checked off today, in every view.
- **Complete and edit in place.** Check a task off from Do Things. Click a task to edit its title, notes, tags, When, deadline, project or area, heading and priority. **Open in Things** handles everything else.
- **Help one click away.** The version at the bottom of the sidebar opens this guide on GitHub.
- **Looks like Things.** Rows show tags, deadline flags ("2 days left", or red "1 day ago"), start-date badges, and icons for notes, checklists and repeating tasks. Dark and Light appearance.
- **Things' other lists one click away.** Inbox, Upcoming, Anytime, Someday and Logbook (marked ↗) open in Things. The sidebar shows the Inbox count and Today's due and open counts, as in Things.

## Advantages over Things
| | Things 3 | Do Things |
|---|---|---|
| **Priorities** | No priority field. Today is one list. | Three priority groups. Drag between them, and tags and deadlines follow the rules above. |
| **Moving tasks** | Moving a task in Today changes only its position. | Moving a task to another group changes its priority and, where the rules say so, its deadline and start date. |
| **Sequential projects** | Every task in a project is available at once. | A project tagged `Sequential` releases one task at a time into Today, in order, and shows each task's place in the project. |
| **Saved searches** | Quick Find and tag filters, but no saved searches in the sidebar. | P1, P2, P3 and Overdue are always one click away. |
| **Due tasks** | A due task can be removed from Today and stays out of view. | Anything due today or overdue is always in Today, in P1. |
| **Project order in Today** | Today has its own order, separate from each project's order. | Tasks from the same project keep their project order within a priority. |

Do Things doesn't replace Things. Planning, projects, areas, repeating tasks, checklists and syncing stay in Things.

## 1. Requirements
- A Mac with **Things 3** (latest version).
- The macOS **Command Line Tools**, which include Python 3. If `/Library/Developer/CommandLineTools/usr/bin/python3` doesn't exist, run `xcode-select --install` in Terminal.
- No other software. Do Things uses only Python's standard library.

## 2. Install (download)
1. Open the latest release: <https://github.com/CyberAdvisor/DoThings/releases/latest>.
2. Under **Assets**, download **Source code (zip)**.
3. Double-click the zip to unzip it. You get a folder named like `DoThings-1.0.0`.
4. Rename the folder to `DoThings`.
5. Move it into a `Projects` folder inside your Documents folder, so its path is `~/Documents/Projects/DoThings`. Create the `Projects` folder if you don't have one.

The commands in this guide assume that location. If you put it elsewhere, change the `cd` path in them.

**Updating to a new version:**
1. Stop Do Things (see section 7).
2. Download and unzip the new release.
3. Copy these files from your old `DoThings` folder into the new one: `auth_token.txt`, `task_order.json` and `sequence_pulls.json`. These are your token, your saved order and your sequential-project progress.
4. Replace the old folder with the new one.

## 3. Prepare Things and your Mac
1. **Create the priority tags.** In Things, open **Window › Tags** and create three tags named exactly `P1`, `P2` and `P3`. Things ignores tags that don't exist, so Do Things can't assign priorities until these do. Do Things shows how to create them if any are missing.
2. **Optional: create the `Sequential` tag** the same way, and add it to any project you want worked in order.
3. **Give Terminal Full Disk Access.** Things keeps its data in a protected folder.
   - Open **System Settings › Privacy & Security › Full Disk Access** and turn on **Terminal**. If Terminal isn't listed, add it with **+**.
   - Quit and reopen Terminal. Turning on the toggle may ask for an administrator password.
   - Without this, macOS blocks reading the Things data without asking, and Do Things reports "Things database not found".

## 4. First run and the auth token
1. Open Terminal and start Do Things:
   ```
   cd ~/Documents/Projects/DoThings
   /Library/Developer/CommandLineTools/usr/bin/python3 serve.py
   ```
   It opens `http://127.0.0.1:8765` in your browser.
2. The first time, it shows a setup screen asking for your Things auth token. Do Things needs it to change tags and dates in Things.
   - In Things, choose **Things › Settings › General**.
   - Turn on **Enable Things URLs**.
   - Click **Manage** and copy the authorization token.
3. Paste the token into the setup screen and click **Save**.
   - It is stored in `auth_token.txt` in the Do Things folder, readable only by your account.
   - It is never committed to git or written to a log.
4. To stop Do Things, press Ctrl-C in Terminal.

**Settings** at the bottom of the sidebar lets you replace the token and switch between **Dark** (the default) and **Light** appearance.

If Things doesn't apply an automatic update, Do Things pauses automatic updates and shows a red bar. The bar lists what to check, and has a **Retry** button and a button to re-enter the token.

## 5. Test manually before automating
To check your setup without changing anything:
```
cd ~/Documents/Projects/DoThings
/Library/Developer/CommandLineTools/usr/bin/python3 debug_things.py
```
It changes nothing in Things or in Do Things. It shows:
- where the Things database is;
- whether the database has the layout Do Things expects;
- any missing P tags;
- every Today task, with the change the rules would make;
- each sequential project's task in progress.

## 6. Project location and development workflow (clone to change Do Things)
If you want Do Things to work differently, work from a clone instead of a download.

1. On GitHub, **fork** `CyberAdvisor/DoThings` to your own account.
2. Clone your fork into the usual location:
   ```
   git clone https://github.com/<your-account>/DoThings.git ~/Documents/Projects/DoThings
   ```
   If you just want to follow the latest changes without forking, clone `https://github.com/CyberAdvisor/DoThings.git` instead and update with `git pull`.
3. Keep this one folder as your only copy. It is where you edit, test, commit and run.
4. Workflow:
   1. Edit.
   2. Test with the verification commands in `AGENTS.md`.
   3. Commit.
   4. Push.
5. Read `AGENTS.md` before changing anything. It lists the safety rules (for example, Do Things never writes to the Things database directly) and the project conventions.
6. **Releases:** bump `VERSION` and push to `main`.
   - The `Release` GitHub Action then tags that commit `vX.Y.Z` and publishes a GitHub release, using the commit message as the notes.
   - Don't create tags by hand, or the action skips that version.
   - In a fork, turn on Actions under the fork's **Actions** tab for this to run.

To make changes with Claude's help, see **Customizing this with Claude** below.

## 7. Start with Shortcuts
Do Things is a small server that runs while you use it. A shortcut starts it in the background and opens the page, without Terminal.

1. **Allow scripts in Shortcuts:** open **Shortcuts**, choose **Shortcuts › Settings › Advanced**, and turn on **Allow Running Scripts**.
2. **New shortcut:** choose **File › New Shortcut** (⌘N), click the title at the top, and name it **Do Things**.
3. **Add the action:** in the action search on the right, type **Run Shell Script** and drag it into the shortcut.
4. **Set up the action:** leave Shell as **zsh** and Input as nothing. Replace the sample text with this one line:
   ```
   cd ~/Documents/Projects/DoThings && nohup /Library/Developer/CommandLineTools/usr/bin/python3 serve.py >> run.log 2>&1 &
   ```
5. **Choose how to launch it (optional):**
   - **Pin in Menu Bar:** click **ⓘ** (Shortcut Details) at the top right and turn it on.
   - **Dock:** choose **File › Add to Dock**.
   - **Spotlight:** finds the shortcut by name.
6. **Run it:** click **▶︎**. Your browser opens Do Things.

Running the shortcut while Do Things is already running just opens the page again.

**Start automatically (optional):** in Shortcuts, open **Automation**, create a Personal Automation (for example **Time of Day**, **Daily**), turn **Ask Before Running** off, and have it run the **Do Things** shortcut.

**Stop Do Things:** in Terminal, run `lsof -ti tcp:8765 | xargs kill`.

**If the shortcut reports "Things database not found"** but Terminal works, also give **Shortcuts** Full Disk Access (section 3, step 3).

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
| `priority_check.py` | The priority, move and sequential-project rules, grouping and ordering (pure logic) |
| `serve.py` | Entry point: local server and JSON API |
| `debug_things.py` | Read-only diagnostic |
| `index.html` | The page: sidebar, task lists, drag-and-drop, editor, settings and token setup |
| `screenshots/today.png` | The Today screenshot shown in this guide (sample data) |
| `test_priority_check.py` | Tests for the rules |
| `test_common.py` | Tests for token handling, dates, time zone, URLs, saved files and database queries |
| `test_serve.py` | Tests for the server against a mock Things database |
| `errors.log`, `run.log` | Runtime logs (untracked). `errors.log` is capped at 1 MB, with the previous one kept as `errors.log.1` |
| `task_order.json` | Saved order within each priority; tasks that leave Today are dropped from it (untracked) |
| `sequence_pulls.json` | The task Do Things started in each sequential project, so it can be undone (untracked) |
| `auth_token.txt` | Things auth token, owner-only permissions (untracked) |

## Safety notes
- The Things database is opened read-only. All changes go through Things' own URL commands, as if you'd made them in Things.
- A change counts as done only after it appears in Things' data. The saved order is updated only after a move is confirmed.
- If an automatic update isn't confirmed, automatic updates pause until you click **Retry**, save a new token or restart Do Things. The failure is logged once. Changes you make yourself are still sent, each with its own message if it fails.
- Tags are written as a full list, so your other tags are kept. A tag containing a comma can't be written safely, so such a task is logged and skipped.
- In a sequential project, Do Things only ever undoes a task it started itself, and not if you've changed that task's date since.
- The server listens only on your Mac (`127.0.0.1`). It accepts only requests addressed to itself, and only accepts changes carrying a header that other websites can't add.
- The auth token is never written to logs.

## Limitations
- Things' database layout isn't published and could change with a Things update. `debug_things.py` reports missing columns.
- Only to-dos are listed, not projects or headings.
- Today is worked out from start dates and deadlines. It can differ from Things in edge cases, such as tasks inside a project that is itself scheduled later. By design, Do Things also lists due tasks you've removed from Things' Today.
- The searches are fixed: P1, P2, P3 and Overdue. New ones are added in code.
- Changes show immediately but are confirmed with Things in the background, one at a time. While a change is pending, that task can't be dragged or opened. A change Things doesn't apply within 5 seconds is undone on the page.
- The editor can't delete a task, edit its checklist, change repeat settings or attachments, or take a task out of a project, area or heading. Use **Open in Things** for those.
- Do Things runs only on the Mac where Things is installed. It has no iPhone or iPad version, but changes it makes appear there through Things' sync.

## Reporting issues and errors
Open an issue at <https://github.com/CyberAdvisor/DoThings/issues/new>. Include:
1. **What happened and what you expected,** and the steps to make it happen again.
2. **Versions:**
   - Do Things, shown at the bottom of the sidebar or in the `VERSION` file.
   - macOS, from  › About This Mac.
   - Things, from Things › About Things.
3. **The diagnostic output:**
   ```
   cd ~/Documents/Projects/DoThings
   /Library/Developer/CommandLineTools/usr/bin/python3 debug_things.py > debug.txt
   ```
   It lists your Today task titles, so remove or replace any you'd rather not share before attaching it.
4. **Recent errors:** the last lines of the logs, from `tail -n 50 errors.log` and `tail -n 50 run.log`.

**Never** attach or paste `auth_token.txt` or your auth token. Do Things never writes the token to its logs, but check anything you attach for task titles you'd rather keep private.

## Customizing this with Claude
1. Clone the repository (section 6).
2. Start a new conversation with Claude, paste in `CLAUDE_CONTEXT.md` and `AGENTS.md`, and describe the change you want.
3. Ask Claude to:
   - confirm the design and file list before writing code;
   - run the verification commands in `AGENTS.md`;
   - follow the release steps: version bump, change logs, then commit and push. The Release action creates the tag and release.
