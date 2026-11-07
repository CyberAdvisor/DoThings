# AGENTS.md — Do Things

Guide for contributors and AI agents working on this repository.

## Project shape
- A local web app that adds a prioritized Today view in front of Things 3.
- `serve.py` is a Python standard-library HTTP server bound to `127.0.0.1:8765`. It serves the single-file page `index.html` and a JSON API.
- Reads come from the Things SQLite database, opened read-only. Writes go through `things:///update` URLs handed to macOS `open -g`, authorized by the user's Things auth token.
- All logic lives in Python. `index.html` only renders lists and sends actions.
- Target: Python 3.9 (macOS Command Line Tools), standard library only. Times are Mountain Time (`America/Denver`).
- Workflow: change → test → commit → push, in the single folder `~/Documents/Projects/DoThings`.

## Files
| File | Purpose |
|---|---|
| `common.py` | Paths (`*_PATH`), `PROJECT_VERSION`, logger, Things date packing, read-only DB queries, URL building and sending, change confirmation, order file, auth token |
| `priority_check.py` | Pure rules: `required_priority`, `plan_refresh`, `plan_move`, `group_today`, `update_order`, the `Task` and `Change` models |
| `serve.py` | Entry point: HTTP handler, request checks, API routes |
| `debug_things.py` | Read-only diagnostic entry point |
| `index.html` | Page: sidebar, lists, drag-and-drop, token setup |
| `test_priority_check.py`, `test_common.py` | Unit tests (`test_common.py` builds a mock Things database) |
| `README.md`, `CLAUDE_CONTEXT.md`, `LICENSE`, `VERSION`, `.gitignore`, `requirements.txt` | Docs and project metadata |

## Safety-critical behavior
Do not weaken any of these without explicit approval:
- **Never write to the Things database directly.** It is opened with `mode=ro`. All changes go through the URL scheme.
- **Confirm before recording.** `apply_change` re-reads the task until `Change.is_satisfied_by` passes (5 s timeout). The order file is saved only after a move is confirmed.
- **Stop on failure.** `apply_refresh_rules` stops at the first unconfirmed write in a refresh.
- **Keep non-priority tags.** `tags=` replaces all tags, so every change carries the full tag list. Tags containing commas are refused, not split.
- **Fail safe on bad data.** An unreadable date counts as no date (never overdue). An unreadable order or token file is logged and ignored.
- **Local-only server.** Bound to `127.0.0.1`. The Host header must be the server's own address (blocks DNS rebinding). POSTs require the `X-Do-Things: 1` header (blocks cross-site requests). Task ids are validated before they reach a URL or `open`.
- **Token secrecy.** `auth_token.txt` is mode 0600 and git-ignored. Never log a URL that contains the token.
- **Page rendering.** Task data is inserted with `textContent`, never `innerHTML`. Only static icon markup uses `innerHTML`.

## Implementation conventions
- Follow the project standard: snake_case files in the repo root, a docstring on every module, class and function, a `Version:` line and change log in every source file (an HTML comment in `index.html`), and type hints throughout.
- Rules belong in `priority_check.py` and must stay free of I/O so they can be tested.
- Database, file and command access belong in `common.py`. `serve.py` only wires requests to them.
- All paths are `*_PATH` constants in `common.py` built from `BASE_DIR`.
- New sidebar searches: add the id to `CUSTOM_SEARCHES` and a branch in `_list_query` (`common.py`), add an entry to `LISTS` in `index.html`, and add a test in `test_common.py`.
- Things stores `startDate` and `deadline` as packed integers (`year<<16 | month<<12 | day<<7`). Use `pack_things_date` and `unpack_things_date`.

## Verification
Run all of these before every commit:
```
PYTHONPYCACHEPREFIX=/tmp/dothings-pycache python3 -m py_compile common.py priority_check.py serve.py debug_things.py test_common.py test_priority_check.py
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
