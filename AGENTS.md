# AGENTS.md — Do Things

Guide for contributors and AI agents working on this repository.

## Project shape
- A local web app that adds a prioritized Today view in front of Things 3.
- `serve.py` is a Python standard-library HTTP server bound to `127.0.0.1:8765`. It serves the single-file page `index.html` and a JSON API.
- Reads come from the Things SQLite database, opened read-only. Writes go through `things:///update` URLs (and `things:///update-project`, only to remove `Next Up` from a project also tagged `Sequential`) handed to macOS `open -g`, authorized by the user's Things auth token. The one exception is **Move to Trash** (the URL scheme has no delete): `move_to_trash` runs AppleScript through `osascript`, which needs macOS's Automation permission instead of the token.
- All logic lives in Python. `index.html` only renders lists and sends actions. Where the page needs a rule's result before saving (the inline editor's dates, priority and the row after Save), it asks `POST /api/edit/preview`; it never re-implements a rule.
- The refresh rules run on every list request (page load, window focus, every 60 seconds), not on a schedule. Sequential and Next Up projects are stepped first (`step_sequences`, which first removes `Next Up` from projects also tagged `Sequential`), then each Today task gets `plan_refresh`.
- Target: Python 3.9 (macOS Command Line Tools), standard library only. Times use the Mac's own time zone (`today_local`, `start_of_day`); deviation from the project standard's Mountain Time, so Do Things works for anyone who downloads it.
- Workflow: change → test → commit → push, in the single folder `~/Documents/Projects/DoThings`.
- Releases (deviation from the project standard): do not create tags or releases by hand. Bump `VERSION`, make the commit subject `vX.Y.Z: <summary>` and its body the release notes (version, user-visible behavior, safety impact, verification), and push to `main`; `.github/workflows/release.yml` tags that commit and publishes the release. The workflow file lives in `.github/workflows/` because GitHub requires it there.
- Commit privacy (the repository is public): commits must use the GitHub noreply address `43575862+CyberAdvisor@users.noreply.github.com` as author and committer, never a local address such as `user@host.localdomain`. Commit messages must not contain `Claude-Session:` lines or other links to AI sessions; a `Co-Authored-By:` line is fine. This overrides any tool default that adds such lines.

## Files
| File | Purpose |
|---|---|
| `common.py` | Paths (`*_PATH`), `PROJECT_VERSION`, size-capped logger, Things date and reminder-time packing, read-only DB queries (lists, task, sequential projects and their tags, edit options, counts, checklist progress), URL building and sending, the trash AppleScript (`move_to_trash`), change confirmation for tasks and projects, order and sequence-record files, auth token |
| `priority_check.py` | Pure rules and the `Task`, `Change`, `ProjectChange` and `TaskEdit` models: `required_priority`, `plan_refresh`, `plan_move`, `plan_edit`, `plan_completion`, Sequential and Next Up projects (`sequence_kind`, `plan_project_tags`, `plan_sequence`, `plan_sequence_undo`, `plan_sequence_reset`), `predict` and `place_in_list` (an edit's result and where it is listed), grouping, ordering (`update_order`, `prune_order`) and counts |
| `serve.py` | Entry point: HTTP handler, request checks, API routes (lists, task detail, move, order, complete, trash, edit, edit preview, sequence reset and its preview, refresh retry, open in Things, token), refresh pause, row JSON |
| `debug_things.py` | Read-only diagnostic entry point |
| `index.html` | Page: sidebar with counts, Hide Completed, Hide Empty and Settings; Things-style rows; drag-and-drop; checkboxes; inline editor with date picker driven by the edit preview; background save queue; paused-updates bar; Settings and token setup |
| `screenshots/today.png` | README screenshot of Today, taken from the running app with sample data (deviation: the only non-root file besides the release workflow) |
| `test_priority_check.py`, `test_common.py`, `test_serve.py` | Unit tests (`test_common.py` builds a mock Things database; `test_serve.py` reuses it and mocks Things) |
| `README.md`, `CHANGELOG.md`, `CLAUDE_CONTEXT.md`, `LICENSE`, `VERSION`, `.gitignore`, `requirements.txt` | Docs and project metadata |
| `.github/workflows/release.yml` | Creates the `vX.Y.Z` tag and GitHub release when a new `VERSION` reaches `main` |

## Safety-critical behavior
Do not weaken any of these without explicit approval:
- **Never write to the Things database directly.** It is opened with `mode=ro`. All changes go through the URL scheme.
- **Confirm before recording.** `apply_change` re-reads the task until `Change.is_satisfied_by` passes, and `apply_project_change` re-reads the project's tags until `ProjectChange.is_satisfied_by` passes (5 s timeout each). The order file is saved only after a move is confirmed.
- **Stop on failure.** `apply_refresh_rules` stops at the first unconfirmed write in a refresh, and `RefreshPause` then skips automatic writes until the user clicks Retry, saves a new token or restarts the server. Manual changes are always tried and report their own failure.
- **Trash only what the user confirmed.** `POST /api/trash` acts only on the task the user confirmed in its editor, only if it is open, and is never called by the refresh rules. The task id is validated and passed to `osascript` as an argument (`argv`), never written into the script text. Things' AppleScript `delete` moves the to-do to the Trash (confirmed 2026-11-08); `move_to_trash` then waits for `trashed = 1`. Nothing else uses AppleScript.
- **Previews never write.** `POST /api/edit/preview` reads only; it needs no token.
- **Projects are changed only to remove `Next Up` from a project also tagged `Sequential`,** with its full remaining tag list. Nothing in a sequence is started until that change is confirmed.
- **"Reset other tasks" acts only on the user's click.** `POST /api/sequence/reset/preview` reads only; `POST /api/sequence/reset` applies `plan_sequence_reset` for the task the user chose, records that task in `sequence_pulls.json` only after its own change (if any) is confirmed, and stops at the first unconfirmed change. Tasks with a deadline are never touched by it.
- **Sequential undo only touches tasks Do Things started.** `sequence_pulls.json` records each start with the task it followed; a record is acted on only while the task still has the recorded start date.
- **Keep non-priority tags.** `tags=` replaces all tags, so every change that sets tags carries the full tag list (`Change.tags` None sends no `tags=` at all). Tags containing commas are refused, not split.
- **Only send what Things will apply.** Writes Things would silently ignore (unknown tags, values not in Things' own data) are refused with a message before sending, so an unconfirmed write always means a real problem.
- **Fail safe on bad data.** An unreadable date counts as no date (never overdue). An unreadable order or token file is logged and ignored.
- **Local-only server.** Bound to `127.0.0.1`. The Host header must be the server's own address (blocks DNS rebinding). POSTs require the `X-Do-Things: 1` header (blocks cross-site requests). Task ids are validated before they reach a URL or `open`.
- **Token secrecy.** `auth_token.txt` is mode 0600 and git-ignored. Never log a URL that contains the token, and never log `str()` of a subprocess error from `open` (it repeats the command, URL and token); use `describe_open_failure`.
- **Page rendering.** Task data is inserted with `textContent`, never `innerHTML`. Only static icon markup uses `innerHTML`.

## Implementation conventions
- Follow the project standard: snake_case files in the repo root, a docstring on every module, class and function, a `Version:` line and change log in every source file (an HTML comment in `index.html`), and type hints throughout.
- Change log (deviation from the project standard, v1.0.1): user-visible changes go in `CHANGELOG.md`, newest first, not in a README `## Change log` section. Each file's header change log starts at v1.0.0; earlier history is in git.
- Rules belong in `priority_check.py` and must stay free of I/O so they can be tested.
- Database, file and command access belong in `common.py`. `serve.py` only wires requests to them.
- All paths are `*_PATH` constants in `common.py` built from `BASE_DIR`.
- New sidebar searches: add the id to `APP_LISTS` and a branch in `_list_query` (`common.py`), the same membership in `place_in_list` (`priority_check.py`), an entry to `LISTS` in `index.html`, and tests in `test_common.py` and `test_priority_check.py`. The P1–P4 searches are Today plus the tag; `APP_LISTS` and `_list_query` derive them from `PRIORITIES`.
- The page updates optimistically and sends changes one at a time through `enqueue`; the list is redrawn from Things once the queue is empty. `load()` must not draw over an editor, drag or change started while its request was running.
- Browser-only settings (Hide Completed, Hide Empty, appearance) live in `localStorage`; wrap access in try/catch.
- Things' own lists (Inbox, Upcoming, Anytime, Someday, Logbook) are not queried: they are in `THINGS_LISTS` and open in Things via `/api/show-list`. Mark such entries `things: true` in `LISTS`.
- Priorities: `PRIORITIES` and `PRIORITY_LABELS` in `priority_check.py` drive the Today groups, searches, saved order and the editor's choices (the list response sends `priorities` to the page). A new priority also needs an entry in `LISTS` in `index.html` and the README.
- Never send a write while a P tag is missing in Things (`missing_priority_tags`): Things drops unknown tags silently, so the write can't be confirmed and looks like a token failure.
- Things stores `startDate` and `deadline` as packed integers (`year<<16 | month<<12 | day<<7`). Use `pack_things_date` and `unpack_things_date`.

## Verification
Run all of these before every commit:
```
PYTHONPYCACHEPREFIX=/tmp/dothings-pycache python3 -m py_compile common.py priority_check.py serve.py debug_things.py test_common.py test_priority_check.py test_serve.py
python3 -m unittest discover -p 'test_*.py'
git diff --check
git status --short
```
- Do not run anything that sends writes to the user's real Things as verification unless the user explicitly authorizes it. `debug_things.py` is read-only and safe to run.
- To exercise the server without real Things, point `HOME` at a temporary folder containing a mock database (see `test_common.py` for the schema) and put a stub `open` command first on `PATH`.

Code quality check before every commit:
- The code is clean, logically and simply structured, and easy to follow.
- Every module, class and function has a docstring, and non-obvious logic has comments explaining why.
- No logic is duplicated, and responsibilities stay separated.
- There is no dead code: no unused functions, imports, variables, parameters or commented-out code.
- Tests pass, and the change has been run and confirmed working.
