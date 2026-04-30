"""Tests for RAGSystem orchestration of content queries.

Two layers:
  - Mocked tests: verify wiring (tool registration, dispatch, source flow) without
    hitting ChromaDB or the network.
  - Live integration test: gated on RUN_LIVE_TESTS=1 — actually instantiates
    RAGSystem against the real config, ChromaDB, and NVIDIA proxy. This is
    the diagnostic that surfaces the original 'query failed' symptom.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from rag_system import RAGSystem
from config import Config


def _silent_config():
    """Config that won't touch real ChromaDB/network when components are mocked."""
    cfg = Config()
    cfg.ANTHROPIC_API_KEY = "test-key"
    cfg.ANTHROPIC_BASE_URL = "https://example.invalid"
    cfg.CHROMA_PATH = "./chroma_db_test_unused"
    return cfg


class TestRAGSystemWiring(unittest.TestCase):

    @patch("rag_system.AIGenerator")
    @patch("rag_system.VectorStore")
    def test_registers_both_tools(self, mock_vs_cls, mock_gen_cls):
        mock_vs_cls.return_value = MagicMock()
        mock_gen_cls.return_value = MagicMock()

        rag = RAGSystem(_silent_config())

        names = {
            t.get_tool_definition()["name"]
            for t in rag.tool_manager.tools.values()
        }
        self.assertEqual(names, {"search_course_content", "get_course_outline"})

    @patch("rag_system.AIGenerator")
    @patch("rag_system.VectorStore")
    def test_search_tool_registered_under_correct_name(self, mock_vs_cls, mock_gen_cls):
        mock_vs_cls.return_value = MagicMock()
        mock_gen_cls.return_value = MagicMock()
        rag = RAGSystem(_silent_config())

        self.assertIn("search_course_content", rag.tool_manager.tools)
        self.assertIs(rag.tool_manager.tools["search_course_content"], rag.search_tool)


class TestRAGSystemContentQuery(unittest.TestCase):

    @patch("rag_system.AIGenerator")
    @patch("rag_system.VectorStore")
    def test_query_passes_tools_and_history_to_generator(self, mock_vs_cls, mock_gen_cls):
        mock_vs_cls.return_value = MagicMock()
        gen = MagicMock()
        gen.generate_response.return_value = "the answer"
        mock_gen_cls.return_value = gen

        rag = RAGSystem(_silent_config())
        sid = rag.session_manager.create_session()
        rag.session_manager.add_exchange(sid, "earlier q", "earlier a")

        ans, _sources = rag.query("What is MCP?", session_id=sid)

        self.assertEqual(ans, "the answer")
        kwargs = gen.generate_response.call_args.kwargs
        self.assertIn(
            "Answer this question about course materials: What is MCP?",
            kwargs["query"],
        )
        self.assertIsNotNone(kwargs["tools"])
        names = {t["name"] for t in kwargs["tools"]}
        self.assertEqual(names, {"search_course_content", "get_course_outline"})
        self.assertIn("earlier q", kwargs["conversation_history"])
        self.assertIs(kwargs["tool_manager"], rag.tool_manager)

    @patch("rag_system.AIGenerator")
    @patch("rag_system.VectorStore")
    def test_query_collects_and_resets_sources(self, mock_vs_cls, mock_gen_cls):
        mock_vs_cls.return_value = MagicMock()
        gen = MagicMock()
        gen.generate_response.return_value = "answer"
        mock_gen_cls.return_value = gen

        rag = RAGSystem(_silent_config())
        rag.search_tool.last_sources = [
            {"text": "Course - Lesson 1", "link": "https://l"}
        ]

        _ans, sources = rag.query("hi")

        self.assertEqual(sources, [{"text": "Course - Lesson 1", "link": "https://l"}])
        self.assertEqual(rag.search_tool.last_sources, [])

    @patch("rag_system.AIGenerator")
    @patch("rag_system.VectorStore")
    def test_query_records_exchange_in_session(self, mock_vs_cls, mock_gen_cls):
        mock_vs_cls.return_value = MagicMock()
        gen = MagicMock()
        gen.generate_response.return_value = "answer text"
        mock_gen_cls.return_value = gen

        rag = RAGSystem(_silent_config())
        sid = rag.session_manager.create_session()

        rag.query("user question", session_id=sid)

        history = rag.session_manager.get_conversation_history(sid)
        self.assertIn("user question", history)
        self.assertIn("answer text", history)

    @patch("rag_system.AIGenerator")
    @patch("rag_system.VectorStore")
    def test_query_without_session_does_not_record(self, mock_vs_cls, mock_gen_cls):
        mock_vs_cls.return_value = MagicMock()
        gen = MagicMock()
        gen.generate_response.return_value = "answer"
        mock_gen_cls.return_value = gen

        rag = RAGSystem(_silent_config())
        rag.query("anonymous question")

        self.assertEqual(rag.session_manager.sessions, {})


@unittest.skipUnless(
    os.environ.get("RUN_LIVE_TESTS") == "1",
    "Live integration disabled — set RUN_LIVE_TESTS=1 to enable "
    "(requires API key + chroma_db; run from backend/ directory).",
)
class TestRAGSystemLive(unittest.TestCase):
    """End-to-end against the real RAGSystem. Surfaces the actual failure mode
    if 'query failed' regresses."""

    @classmethod
    def setUpClass(cls):
        from config import config
        cls.rag = RAGSystem(config)

    def test_content_query_returns_nonempty_answer(self):
        ans, sources = self.rag.query("What is MCP?")
        self.assertIsInstance(ans, str)
        self.assertGreater(len(ans), 0, "expected non-empty answer")
        self.assertGreaterEqual(len(sources), 1, "expected at least one source citation")

    def test_outline_query_returns_lessons(self):
        ans, _sources = self.rag.query(
            "What is the outline of the MCP course?"
        )
        self.assertIn("Lesson", ans)


if __name__ == "__main__":
    unittest.main()
