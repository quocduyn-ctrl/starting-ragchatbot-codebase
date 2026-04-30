"""Unit tests for CourseSearchTool.execute().

Strategy: mock the VectorStore so we exercise the tool's logic in isolation:
result formatting, empty-result handling, error propagation, source tracking.
"""
import unittest
from unittest.mock import MagicMock

from search_tools import CourseSearchTool, ToolManager
from vector_store import SearchResults


class TestCourseSearchToolExecute(unittest.TestCase):

    def setUp(self):
        self.store = MagicMock()
        self.tool = CourseSearchTool(self.store)

    def test_passes_query_filters_to_vector_store(self):
        self.store.search.return_value = SearchResults(
            documents=[], metadata=[], distances=[]
        )
        self.tool.execute(query="rag", course_name="MCP", lesson_number=2)
        self.store.search.assert_called_once_with(
            query="rag", course_name="MCP", lesson_number=2
        )

    def test_returns_formatted_results_with_context_headers(self):
        self.store.search.return_value = SearchResults(
            documents=["Chunk one body."],
            metadata=[{"course_title": "MCP Course", "lesson_number": 3}],
            distances=[0.1],
        )
        self.store.get_lesson_link.return_value = "https://x/lesson3"

        result = self.tool.execute(query="anything")

        self.assertIn("[MCP Course - Lesson 3]", result)
        self.assertIn("Chunk one body.", result)

    def test_handles_chunks_with_no_lesson_number(self):
        self.store.search.return_value = SearchResults(
            documents=["course-level chunk"],
            metadata=[{"course_title": "Intro Course"}],
            distances=[0.2],
        )
        self.store.get_course_link.return_value = "https://intro"

        result = self.tool.execute(query="anything")

        self.assertIn("[Intro Course]", result)
        self.assertNotIn("Lesson", result)

    def test_returns_no_results_message_when_empty(self):
        self.store.search.return_value = SearchResults(
            documents=[], metadata=[], distances=[]
        )
        result = self.tool.execute(query="x", course_name="Foo", lesson_number=1)

        self.assertIn("No relevant content found", result)
        self.assertIn("Foo", result)
        self.assertIn("1", result)

    def test_propagates_vector_store_error_string(self):
        self.store.search.return_value = SearchResults.empty(
            "No course found matching 'gibberish'"
        )
        result = self.tool.execute(query="x", course_name="gibberish")
        self.assertEqual(result, "No course found matching 'gibberish'")

    def test_populates_last_sources_with_text_and_link(self):
        self.store.search.return_value = SearchResults(
            documents=["c"],
            metadata=[{"course_title": "MCP", "lesson_number": 1}],
            distances=[0.1],
        )
        self.store.get_lesson_link.return_value = "https://lesson"

        self.tool.execute(query="anything")

        self.assertEqual(len(self.tool.last_sources), 1)
        self.assertEqual(self.tool.last_sources[0]["text"], "MCP - Lesson 1")
        self.assertEqual(self.tool.last_sources[0]["link"], "https://lesson")

    def test_lesson_zero_is_mentioned_in_empty_results_message(self):
        """Edge case: with lesson_number=0, the empty-results message currently
        omits the lesson because of `if lesson_number:` (0 is falsy). This test
        documents the intended behavior and will surface the bug if present."""
        self.store.search.return_value = SearchResults(
            documents=[], metadata=[], distances=[]
        )
        result = self.tool.execute(query="x", course_name="MCP", lesson_number=0)
        self.assertIn("lesson 0", result.lower())


class TestToolManagerDispatch(unittest.TestCase):

    def test_executes_registered_tool_by_name(self):
        manager = ToolManager()
        store = MagicMock()
        store.search.return_value = SearchResults(
            documents=[], metadata=[], distances=[]
        )
        manager.register_tool(CourseSearchTool(store))

        out = manager.execute_tool("search_course_content", query="hi")

        self.assertIsInstance(out, str)
        store.search.assert_called_once_with(
            query="hi", course_name=None, lesson_number=None
        )

    def test_unknown_tool_returns_error_string(self):
        manager = ToolManager()
        out = manager.execute_tool("nonexistent")
        self.assertIn("not found", out)

    def test_get_last_sources_returns_first_nonempty(self):
        manager = ToolManager()
        store = MagicMock()
        tool = CourseSearchTool(store)
        manager.register_tool(tool)
        tool.last_sources = [{"text": "x", "link": None}]

        self.assertEqual(manager.get_last_sources(), [{"text": "x", "link": None}])

    def test_reset_sources_clears_all_tools(self):
        manager = ToolManager()
        tool = CourseSearchTool(MagicMock())
        manager.register_tool(tool)
        tool.last_sources = [{"text": "x", "link": None}]

        manager.reset_sources()
        self.assertEqual(tool.last_sources, [])


if __name__ == "__main__":
    unittest.main()
