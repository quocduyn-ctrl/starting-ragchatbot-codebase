"""API contract tests for the FastAPI endpoints in backend/app.py.

The test app in conftest.py mirrors app.py's routes and request/response
models exactly, but injects a mocked RAGSystem so we exercise:
  - request validation (Pydantic shapes, required fields)
  - response shape and status codes
  - session-id handling (created when missing, echoed when provided)
  - error mapping (RAGSystem exceptions -> HTTP 500)

It does NOT exercise the real RAGSystem — that's covered by
test_rag_system.py and the live integration test there.
"""
import pytest


pytestmark = pytest.mark.api


# ---------------------------------------------------------------------------
# POST /api/query
# ---------------------------------------------------------------------------

class TestQueryEndpoint:

    def test_returns_answer_sources_and_session(self, client, sample_sources):
        resp = client.post(
            "/api/query",
            json={"query": "What is MCP?", "session_id": "existing-session"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "This is a test answer about MCP."
        assert body["session_id"] == "existing-session"
        assert body["sources"] == sample_sources

    def test_creates_session_when_none_provided(self, client, mock_rag_system):
        resp = client.post("/api/query", json={"query": "hello"})

        assert resp.status_code == 200
        body = resp.json()
        # Mock returns "test-session-123" from create_session()
        assert body["session_id"] == "test-session-123"
        mock_rag_system.session_manager.create_session.assert_called_once()

    def test_does_not_create_session_when_provided(self, client, mock_rag_system):
        client.post(
            "/api/query",
            json={"query": "hello", "session_id": "caller-session"},
        )
        mock_rag_system.session_manager.create_session.assert_not_called()

    def test_passes_query_and_session_to_rag(self, client, mock_rag_system):
        client.post(
            "/api/query",
            json={"query": "What is MCP?", "session_id": "s-1"},
        )
        mock_rag_system.query.assert_called_once_with("What is MCP?", "s-1")

    def test_query_field_is_required(self, client):
        resp = client.post("/api/query", json={})
        assert resp.status_code == 422  # Pydantic validation error

    def test_query_must_be_string(self, client):
        resp = client.post("/api/query", json={"query": 123})
        # Pydantic v2 coerces ints to str; if it doesn't, that's also fine — both
        # outcomes are acceptable contract-wise. Just confirm we don't crash 500.
        assert resp.status_code in (200, 422)

    def test_rag_exception_returns_500(self, client, mock_rag_system):
        mock_rag_system.query.side_effect = RuntimeError("upstream blew up")

        resp = client.post("/api/query", json={"query": "anything"})

        assert resp.status_code == 500
        assert "upstream blew up" in resp.json()["detail"]

    def test_empty_sources_list_is_valid(self, client, mock_rag_system):
        mock_rag_system.query.return_value = ("answer with no sources", [])

        resp = client.post("/api/query", json={"query": "trivia"})

        assert resp.status_code == 200
        assert resp.json()["sources"] == []

    def test_source_without_link_is_accepted(self, client, mock_rag_system):
        mock_rag_system.query.return_value = (
            "ans",
            [{"text": "Course - Lesson 1", "link": None}],
        )

        resp = client.post("/api/query", json={"query": "x"})

        assert resp.status_code == 200
        assert resp.json()["sources"] == [
            {"text": "Course - Lesson 1", "link": None}
        ]


# ---------------------------------------------------------------------------
# GET /api/courses
# ---------------------------------------------------------------------------

class TestCoursesEndpoint:

    def test_returns_course_stats(self, client, sample_course_analytics):
        resp = client.get("/api/courses")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total_courses"] == sample_course_analytics["total_courses"]
        assert body["course_titles"] == sample_course_analytics["course_titles"]

    def test_calls_rag_get_course_analytics(self, client, mock_rag_system):
        client.get("/api/courses")
        mock_rag_system.get_course_analytics.assert_called_once()

    def test_handles_empty_catalog(self, client, mock_rag_system):
        mock_rag_system.get_course_analytics.return_value = {
            "total_courses": 0,
            "course_titles": [],
        }

        resp = client.get("/api/courses")

        assert resp.status_code == 200
        assert resp.json() == {"total_courses": 0, "course_titles": []}

    def test_rag_exception_returns_500(self, client, mock_rag_system):
        mock_rag_system.get_course_analytics.side_effect = RuntimeError("chroma down")

        resp = client.get("/api/courses")

        assert resp.status_code == 500
        assert "chroma down" in resp.json()["detail"]

    def test_post_is_not_allowed(self, client):
        resp = client.post("/api/courses")
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# POST /api/session/new
# ---------------------------------------------------------------------------

class TestNewSessionEndpoint:

    def test_returns_new_session_id(self, client):
        resp = client.post("/api/session/new", json={})

        assert resp.status_code == 200
        assert resp.json() == {"session_id": "test-session-123"}

    def test_deletes_previous_session_when_id_provided(self, client, mock_rag_system):
        client.post("/api/session/new", json={"session_id": "old-session"})

        mock_rag_system.session_manager.delete_session.assert_called_once_with(
            "old-session"
        )
        mock_rag_system.session_manager.create_session.assert_called_once()

    def test_does_not_delete_when_no_session_id(self, client, mock_rag_system):
        client.post("/api/session/new", json={})
        mock_rag_system.session_manager.delete_session.assert_not_called()

    def test_accepts_empty_body(self, client):
        # `session_id` is optional, so an empty body should still succeed.
        resp = client.post("/api/session/new", json={})
        assert resp.status_code == 200

    def test_rag_exception_returns_500(self, client, mock_rag_system):
        mock_rag_system.session_manager.create_session.side_effect = RuntimeError(
            "session store unavailable"
        )

        resp = client.post("/api/session/new", json={})

        assert resp.status_code == 500
        assert "session store unavailable" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

class TestRootEndpoint:
    """In production, `/` serves the static frontend. The test app exposes
    a JSON stand-in so we can still verify routing and 200-OK behavior
    without depending on the `frontend/` directory."""

    def test_root_returns_ok(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Cross-endpoint workflow
# ---------------------------------------------------------------------------

class TestQueryWorkflow:
    """Integration-style tests that string multiple endpoints together
    against the same mocked backend, mirroring the frontend's flow."""

    def test_new_session_then_query_uses_returned_id(self, client, mock_rag_system):
        # 1. Caller asks for a fresh session
        new_resp = client.post("/api/session/new", json={})
        sid = new_resp.json()["session_id"]

        # 2. Caller submits a query with that session id
        q_resp = client.post(
            "/api/query", json={"query": "follow-up", "session_id": sid}
        )

        assert q_resp.status_code == 200
        assert q_resp.json()["session_id"] == sid
        mock_rag_system.query.assert_called_once_with("follow-up", sid)

    def test_courses_and_query_can_be_called_independently(self, client):
        c = client.get("/api/courses")
        q = client.post("/api/query", json={"query": "anything"})
        assert c.status_code == 200
        assert q.status_code == 200
