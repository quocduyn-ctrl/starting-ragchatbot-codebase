"""Shared pytest fixtures for the backend test suite.

Key design decisions:

1. We do NOT import `backend/app.py` directly. That module mounts
   `../frontend` as static files (a path that only exists relative to the
   server's working directory) and instantiates a real RAGSystem at import
   time, which constructs ChromaDB and an HTTP client to the NVIDIA proxy.
   Both make the module unsafe to import in a test environment.

2. Instead, `api_app` rebuilds an equivalent FastAPI app inline with the
   same routes, request/response models, and dependency wiring — but with
   a mocked RAGSystem injected. This keeps API contract tests honest
   (same shapes, same status codes, same error mapping) without dragging
   in the static-file mount or real services.

3. `mock_rag_system` is the seam we use to control RAGSystem behavior per
   test. It exposes the same surface app.py touches:
   `query()`, `get_course_analytics()`, and a `session_manager` with
   `create_session()` / `delete_session()`.

Note: do NOT add `from __future__ import annotations` here. FastAPI inspects
runtime type hints to decide whether a parameter is a request body or a
query string; with PEP 563 string annotations and Pydantic models defined
inside `_build_test_app`, those forward references can't be resolved and
every POST collapses into 422 ("query missing").
"""
import os
import sys
from typing import List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

# Make the `backend/` directory importable so tests can `from rag_system import ...`
# even when pytest is invoked from the repo root.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_sources():
    """A representative `sources` list as returned by ToolManager.get_last_sources()."""
    return [
        {"text": "MCP Course - Lesson 1", "link": "https://example.com/mcp/1"},
        {"text": "MCP Course - Lesson 2", "link": "https://example.com/mcp/2"},
    ]


@pytest.fixture
def sample_course_analytics():
    """Shape that RAGSystem.get_course_analytics() returns."""
    return {
        "total_courses": 3,
        "course_titles": [
            "MCP: Build Rich-Context AI Apps",
            "Building Toward Computer Use With Anthropic",
            "Advanced Retrieval for AI",
        ],
    }


# ---------------------------------------------------------------------------
# Mocked RAG system
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_rag_system(sample_sources, sample_course_analytics):
    """A MagicMock shaped like RAGSystem with sensible defaults.

    Tests can override return values via standard MagicMock patterns,
    e.g. `mock_rag_system.query.return_value = ("custom", [])`.
    """
    rag = MagicMock()
    rag.query.return_value = ("This is a test answer about MCP.", sample_sources)
    rag.get_course_analytics.return_value = sample_course_analytics
    rag.session_manager.create_session.return_value = "test-session-123"
    rag.session_manager.delete_session.return_value = None
    return rag


# ---------------------------------------------------------------------------
# Test FastAPI app (mirrors backend/app.py without the static mount)
# ---------------------------------------------------------------------------

def _build_test_app(rag_system) -> FastAPI:
    """Construct a FastAPI app with the same API surface as backend/app.py.

    Deliberately omits:
      - The static file mount on `/` (path doesn't exist in tests).
      - The startup hook that ingests `../docs`.
      - CORS / TrustedHost middleware (irrelevant to endpoint behavior).
    """
    app = FastAPI(title="Course Materials RAG System (test)")

    class QueryRequest(BaseModel):
        query: str
        session_id: Optional[str] = None

    class Source(BaseModel):
        text: str
        link: Optional[str] = None

    class QueryResponse(BaseModel):
        answer: str
        sources: List[Source]
        session_id: str

    class CourseStats(BaseModel):
        total_courses: int
        course_titles: List[str]

    class NewSessionRequest(BaseModel):
        session_id: Optional[str] = None

    class NewSessionResponse(BaseModel):
        session_id: str

    @app.post("/api/query", response_model=QueryResponse)
    async def query_documents(request: QueryRequest):
        try:
            session_id = request.session_id
            if not session_id:
                session_id = rag_system.session_manager.create_session()
            answer, sources = rag_system.query(request.query, session_id)
            return QueryResponse(answer=answer, sources=sources, session_id=session_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/session/new", response_model=NewSessionResponse)
    async def new_session(request: NewSessionRequest):
        try:
            if request.session_id:
                rag_system.session_manager.delete_session(request.session_id)
            session_id = rag_system.session_manager.create_session()
            return NewSessionResponse(session_id=session_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/courses", response_model=CourseStats)
    async def get_course_stats():
        try:
            analytics = rag_system.get_course_analytics()
            return CourseStats(
                total_courses=analytics["total_courses"],
                course_titles=analytics["course_titles"],
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/")
    async def root():
        # Stand-in for the static `index.html` mount in production.
        return {"status": "ok", "service": "Course Materials RAG System"}

    return app


@pytest.fixture
def api_app(mock_rag_system):
    """FastAPI test app wired to the mock RAG system."""
    return _build_test_app(mock_rag_system)


@pytest.fixture
def client(api_app):
    """Synchronous TestClient for the FastAPI test app."""
    return TestClient(api_app)
