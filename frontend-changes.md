# Testing framework enhancements

This task added an API testing layer and shared pytest infrastructure to
the existing `backend/tests/` suite. No frontend code or runtime backend
code was modified — only the test scaffolding and project config.

## Files added

### `backend/tests/conftest.py`
Shared pytest fixtures consumed by `test_api_endpoints.py` (and available
to any future test module):

- `sample_sources` — representative `[{text, link}]` list as returned by
  `ToolManager.get_last_sources()`.
- `sample_course_analytics` — shape returned by
  `RAGSystem.get_course_analytics()`.
- `mock_rag_system` — a `MagicMock` exposing the surface `app.py`
  touches (`query`, `get_course_analytics`, `session_manager.create_session`,
  `session_manager.delete_session`) with sensible defaults.
- `api_app` / `client` — a FastAPI app + `TestClient` wired to
  `mock_rag_system`.

The conftest also extends `sys.path` so `pytest backend/tests/...` works
whether invoked from the repo root or from `backend/`.

#### Why a parallel test app, not `from app import app`

`backend/app.py` does two things that make it unsafe to import in a test
environment:

1. **Mounts `../frontend` as static files.** The relative path is resolved
   against the test runner's CWD, not `backend/`, so the mount fails when
   pytest runs from the repo root.
2. **Constructs a real `RAGSystem` at import time.** That instantiates
   ChromaDB on disk and an HTTP client to the NVIDIA proxy — both of
   which we explicitly want mocked in API tests.

`_build_test_app()` in conftest rebuilds the same routes, request/response
models, and error-mapping logic, but takes a `rag_system` argument so the
mock can be injected. The contract under test (status codes, body shapes,
session-id flow) is identical to production; the difference is only the
backing service.

#### One trap worth flagging
Do **not** add `from __future__ import annotations` to `conftest.py` or
`test_api_endpoints.py`. PEP 563 turns the Pydantic-model type hints into
forward-reference strings, and FastAPI cannot resolve those strings to
classes defined inside `_build_test_app()`'s closure. The symptom is
every POST returning HTTP 422 with `loc: ['query', 'request']` — FastAPI
silently treats the unresolved body model as a query parameter. A comment
in the conftest docstring captures this for future readers.

### `backend/tests/test_api_endpoints.py`
22 tests across 5 classes covering:

- **`TestQueryEndpoint`** — `/api/query` happy path, session creation when
  none provided, session pass-through when provided, argument forwarding
  to `RAGSystem.query()`, request validation (missing/wrong-typed fields),
  500 mapping when RAG raises, empty-sources case, sources-without-link.
- **`TestCoursesEndpoint`** — `/api/courses` shape, empty-catalog handling,
  500 on RAG failure, `405` on POST.
- **`TestNewSessionEndpoint`** — `/api/session/new` returns a fresh id,
  deletes the previous session iff one was supplied, accepts an empty
  body, maps RAG errors to 500.
- **`TestRootEndpoint`** — `/` returns 200 (stand-in for the static
  `index.html` mount that exists only in production).
- **`TestQueryWorkflow`** — multi-call flows: `new_session → query` reuses
  the returned id; `/api/courses` and `/api/query` are independent.

All tests are marked `@pytest.mark.api` so they can be run as a group:
`uv run pytest -m api`.

## Files modified

### `pyproject.toml`
Added two new sections:

```toml
[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "httpx>=0.28.0",   # required by FastAPI's TestClient
]

[tool.pytest.ini_options]
testpaths       = ["backend/tests"]
pythonpath      = ["backend"]   # replaces the sys.path hack in tests/__init__.py
python_files    = ["test_*.py"]
python_classes  = ["Test*"]
python_functions = ["test_*"]
addopts = ["-ra", "--strict-markers", "--tb=short"]
markers = [
    "live: tests that hit the real network/ChromaDB (gated on RUN_LIVE_TESTS=1)",
    "api:  FastAPI endpoint tests using TestClient",
]
filterwarnings = [
    "ignore::DeprecationWarning",
    "ignore::PendingDeprecationWarning",
]
```

`pythonpath = ["backend"]` means new tests can use flat imports
(`from rag_system import ...`) without relying on the `sys.path`
manipulation in `backend/tests/__init__.py`. The existing manipulation
remains in place so older tests continue to work when invoked outside
pytest (e.g. `python -m unittest`).

`-ra` surfaces a short summary of all non-passing outcomes (skipped,
xfail, errored) at the end of the run — useful for confirming the live
integration tests are skipping rather than silently missing.

## Verification

```bash
uv sync --group dev    # installs pytest + httpx
uv run pytest          # auto-discovers via [tool.pytest.ini_options]
```

Result on this branch:

```
backend\tests\test_ai_generator.py        ...............    [ 26%]
backend\tests\test_api_endpoints.py       ......................   [ 66%]
backend\tests\test_course_search_tool.py  ...........        [ 85%]
backend\tests\test_rag_system.py          ......ss           [100%]

54 passed, 2 skipped in 131.93s
```

The two skips are the pre-existing `RUN_LIVE_TESTS=1`-gated integration
tests in `test_rag_system.py`. The 22 newly added API tests all pass.

## Things this does not do

- No production code changed — `backend/app.py`, `rag_system.py`, etc. are
  untouched.
- No frontend code changed — the `/` endpoint test uses the stand-in
  JSON route from the test app, not the real static mount.
- The live integration tests in `test_rag_system.py` are unchanged and
  still gated on `RUN_LIVE_TESTS=1`.

---

# Frontend Changes — Dark/Light Theme Toggle

Adds a user-facing toggle that switches the UI between the existing dark theme and a new light theme. The choice persists across reloads.

## Files modified

- `frontend/index.html`
- `frontend/style.css`
- `frontend/script.js`

## 1. `frontend/index.html`

- Added a fixed-position `<button id="themeToggle">` immediately inside `<body>`, before `.container`. It carries `aria-label`, `aria-pressed`, and `title` for accessibility, and is a real `<button>` so Enter/Space activation is native.
- The button contains two inline SVGs — a sun icon (`.theme-icon-sun`) and a moon icon (`.theme-icon-moon`). CSS shows whichever matches the active theme.
- Bumped the asset cache-busting query string from `?v=11` to `?v=12` on both `style.css` and `script.js` so existing browser caches pick up the new files.

## 2. `frontend/style.css`

### Theme variable sets

- The original `:root` variable block is now scoped to `:root, :root[data-theme="dark"]` — dark remains the default.
- Added a parallel `:root[data-theme="light"]` block with light-mode values:
  - `--background: #f8fafc`, `--surface: #ffffff`, `--surface-hover: #e2e8f0`
  - `--text-primary: #0f172a`, `--text-secondary: #475569`
  - `--border-color: #cbd5e1`, `--assistant-message: #e2e8f0`
  - `--shadow` softened, `--welcome-bg: #dbeafe`
  - `--primary-color` / `--primary-hover` / `--user-message` kept as the same blue so the brand accent is consistent across themes.
- Added a new `--code-bg` variable (dark: `rgba(0,0,0,0.2)`, light: `rgba(15,23,42,0.06)`) and switched `.message-content code` and `.message-content pre` to use it. Without this the inline-code background was nearly invisible in light mode.

### Smooth theme transitions

- A shared rule applies a 0.3s ease transition on `background-color`, `color`, and `border-color` to the major surfaces (body, sidebar, chat container, messages, inputs, suggested items, the toggle itself), so theme changes glide rather than snap.

### Toggle button styling

- `.theme-toggle` is `position: fixed; top: 1rem; right: 1rem;` with `z-index: 100` — it floats in the top-right above the layout regardless of viewport size, including mobile.
- Circular 44×44 button using the active theme's `--surface` background and `--border-color`, with `--shadow` for elevation. Hover state lifts (`translateY(-1px)`) and brightens to `--surface-hover`. `:focus-visible` shows the standard `--focus-ring`.
- Both SVGs are absolutely positioned in the same spot. CSS animates `opacity` (0.3s) and `transform` rotation/scale (0.4s) so the icons cross-fade and rotate when the theme flips:
  - Dark theme → moon visible, sun hidden (rotated −90°, scaled down).
  - `:root[data-theme="light"]` swaps which is shown.

## 3. `frontend/script.js`

### Pre-DOMContentLoaded theme bootstrap

- An IIFE at the top of the file runs *before* `DOMContentLoaded`. It reads the saved `theme` from `localStorage`, falls back to the OS-level `prefers-color-scheme: light` media query, and otherwise defaults to dark. It then sets `data-theme` on `<html>` immediately. This avoids a flash of the wrong theme on first paint.
- The `localStorage` access is wrapped in `try/catch` so privacy/sandbox modes don't break the page.

### `themeToggle` wiring

- Added `themeToggle` to the DOM-element variable list and grab it inside the existing `DOMContentLoaded` handler.
- New `syncThemeToggleState()` keeps `aria-pressed` and `aria-label` on the button correct (`"Switch to dark theme"` vs. `"Switch to light theme"`). Called on init and after every toggle.
- New `toggleTheme()` flips `data-theme` between `light` and `dark`, persists the choice to `localStorage`, and re-syncs ARIA state. Triggered on the button's `click`. Keyboard activation (Enter/Space) is provided by the browser since it's a real `<button>`.

## Behavior summary

- First load: theme = saved preference → OS preference → dark.
- Click (or Enter/Space on focused) the top-right button: theme flips with a 0.3s color crossfade and the icon rotates/scales between sun and moon.
- Reload: previously chosen theme is restored without flash.
- All existing components (sidebar, chat messages, code blocks, sources, suggested items, input, send button, scrollbars) read from CSS variables and adapt automatically. No element was hardcoded to a single theme.

---

# Frontend Code Quality Tooling

Adds an automatic-formatting workflow for the frontend (`frontend/index.html`, `frontend/script.js`, `frontend/style.css`) and applies it across the existing files.

The original feature request mentioned `black`, but `black` is a Python formatter and the work was scoped to frontend only — so the frontend equivalent (**Prettier**) was wired up instead. The shape of the workflow (one config file, one format command, one check command) mirrors what `black` would provide on the backend.

## What was added

### 1. `package.json` (new)
Declares Prettier 3.x as the only dev dependency and exposes three npm scripts:
- `npm run format` → `prettier --write` over `frontend/**/*.{html,css,js,json,md}`
- `npm run format:check` → `prettier --check` (non-zero exit on drift; CI-friendly)
- `npm run quality` → alias for `format:check`, intended as the umbrella command if other checks (eslint, stylelint) are added later

### 2. `.prettierrc` (new)
Repo-wide Prettier configuration. Choices made to **minimize churn against the existing codebase**:
- `tabWidth: 4`, `useTabs: false` — matches the existing 4-space indentation in all three frontend files
- `printWidth: 100` — accommodates the wider lines already present (long template literals, fetch calls)
- `singleQuote: true`, `semi: true` — matches existing JS style
- HTML/CSS override `singleQuote: false` (HTML attributes use double quotes by convention)
- JSON/Markdown override `tabWidth: 2` (community standard; Prettier defaults)
- `endOfLine: lf` — enforces LF in the repo regardless of OS, so Windows checkouts don't introduce CRLF diffs

### 3. `.prettierignore` (new)
Excludes:
- `node_modules/`, lock files
- The entire `backend/` tree and any `.py` (Prettier shouldn't touch Python)
- Generated/data dirs (`backend/chroma_db/`, `docs/`, `uploads/`)
- VCS dirs (`.git/`, `.trees/`)
- `CLAUDE.md` and `frontend-changes.md` (project-meta files we don't want auto-reformatted)

### 4. `scripts/format-frontend.sh` (new, executable)
Convenience wrapper: changes to repo root, lazily runs `npm install` if `node_modules/` is missing, then `prettier --write`. Designed so a contributor can clone the repo and run a single command without separately knowing the npm setup steps.

### 5. `scripts/check-quality.sh` (new, executable)
Same lazy-install pattern, but runs `prettier --check`. Exits non-zero if any frontend file is unformatted. Suitable for CI or a pre-push hook. Structured so additional checks (eslint, stylelint, html-validate) can be appended as future quality gates without changing the contract.

### 6. `.gitignore` (updated)
Added a "Node / frontend tooling" section ignoring `node_modules/` and `npm-debug.log*`.

### 7. `README.md` (updated)
New "Frontend Code Quality" section documenting both the shell scripts and the npm scripts, with a note that Node.js is required and `npm install` runs automatically on first invocation.

## Formatting changes applied to existing files

Ran `prettier --write` once. All three frontend files were rewritten:

| File | Lines changed | Nature of changes |
|---|---|---|
| `frontend/index.html` | +110 / −72 (182 changed) | HTML normalization: `<!DOCTYPE>` → `<!doctype>`, self-closing void tags (`<meta ... />`, `<input ... />`, `<link ... />`), consistent indentation under `<html>`/`<head>`/`<body>`, long `<button>` attributes wrapped one-per-line, single-quoted attribute on the suggested-question button that contains a literal `"` |
| `frontend/script.js` | +27 / −27 | Trailing commas in multiline object/array literals (`trailingComma: "es5"`), arrow params parenthesized (`(button) =>`, `(s) =>`, `(title) =>`), removed trailing whitespace, removed double-blank-line, multi-line `.map(...).join(...)` chain reformatted, dropped redundant `else` block formatting |
| `frontend/style.css` | +43 / −26 | Selector lists split one-per-line (`*, *::before, *::after` → 3 lines; same for the markdown header rules), long `font-family` value wrapped, single-quoted strings → double-quoted (CSS convention), inline rules like `font-size: 1.5rem; }` split onto separate lines |

No semantic / behavioral changes — only whitespace, quoting, and line-wrap normalization. The page renders identically.

## Verification

```bash
$ ./scripts/check-quality.sh
==> Prettier format check (frontend/)
Checking formatting...
All matched files use Prettier code style!

All quality checks passed.
```

## How to use going forward

- Before committing frontend changes: `./scripts/format-frontend.sh`
- In CI / pre-push: `./scripts/check-quality.sh`
- IDE integration: most editors auto-pick up `.prettierrc` once the Prettier extension is installed; configure "format on save" against `frontend/`

## Intentionally not done

- **No backend formatter.** The task was scoped to frontend, so Python files (`backend/`) are untouched and explicitly excluded in `.prettierignore`. `black` for the backend would be a separate, parallel addition.
- **No linter** (eslint / stylelint). The task asked for a formatter; lint rules are a heavier change with style debates of their own. The `npm run quality` script is set up as an extension point so a linter can be added later without churn to the script names.
- **No pre-commit hook installed automatically.** `check-quality.sh` is hook-ready; whether to wire it into Husky / a Git hook is left to the team.
