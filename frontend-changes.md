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
