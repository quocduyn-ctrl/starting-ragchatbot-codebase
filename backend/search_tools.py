from typing import Dict, Any, Optional, Protocol
from abc import ABC, abstractmethod
from vector_store import VectorStore, SearchResults


class Tool(ABC):
    """Abstract base class for all tools"""
    
    @abstractmethod
    def get_tool_definition(self) -> Dict[str, Any]:
        """Return Anthropic tool definition for this tool"""
        pass
    
    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Execute the tool with given parameters"""
        pass


class CourseSearchTool(Tool):
    """Tool for searching course content with semantic course name matching"""
    
    def __init__(self, vector_store: VectorStore):
        self.store = vector_store
        self.last_sources = []  # Track sources from last search
    
    def get_tool_definition(self) -> Dict[str, Any]:
        """Return Anthropic tool definition for this tool"""
        return {
            "name": "search_course_content",
            "description": "Search course materials with smart course name matching and lesson filtering",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string", 
                        "description": "What to search for in the course content"
                    },
                    "course_name": {
                        "type": "string",
                        "description": "Course title (partial matches work, e.g. 'MCP', 'Introduction')"
                    },
                    "lesson_number": {
                        "type": "integer",
                        "description": "Specific lesson number to search within (e.g. 1, 2, 3)"
                    }
                },
                "required": ["query"]
            }
        }
    
    def execute(self, query: str, course_name: Optional[str] = None, lesson_number: Optional[int] = None) -> str:
        """
        Execute the search tool with given parameters.
        
        Args:
            query: What to search for
            course_name: Optional course filter
            lesson_number: Optional lesson filter
            
        Returns:
            Formatted search results or error message
        """
        
        # Use the vector store's unified search interface
        results = self.store.search(
            query=query,
            course_name=course_name,
            lesson_number=lesson_number
        )
        
        # Handle errors
        if results.error:
            return results.error
        
        # Handle empty results
        if results.is_empty():
            filter_info = ""
            if course_name:
                filter_info += f" in course '{course_name}'"
            if lesson_number is not None:
                filter_info += f" in lesson {lesson_number}"
            return f"No relevant content found{filter_info}."
        
        # Format and return results
        return self._format_results(results)
    
    def _format_results(self, results: SearchResults) -> str:
        """Format search results with course and lesson context"""
        formatted = []
        sources = []  # Track sources for the UI

        for doc, meta in zip(results.documents, results.metadata):
            course_title = meta.get('course_title', 'unknown')
            lesson_num = meta.get('lesson_number')

            # Build context header (model-facing)
            header = f"[{course_title}"
            if lesson_num is not None:
                header += f" - Lesson {lesson_num}"
            header += "]"

            # Build UI-facing source: visible text + optional link
            text = course_title
            if lesson_num is not None:
                text += f" - Lesson {lesson_num}"
                link = self.store.get_lesson_link(course_title, lesson_num)
            else:
                link = self.store.get_course_link(course_title)

            sources.append({"text": text, "link": link})
            formatted.append(f"{header}\n{doc}")

        # Store sources for retrieval
        self.last_sources = sources

        return "\n\n".join(formatted)


class CourseOutlineTool(Tool):
    """Tool for retrieving a course outline: title, link, and full lesson list."""

    def __init__(self, vector_store: VectorStore):
        self.store = vector_store
        self.last_sources = []

    def get_tool_definition(self) -> Dict[str, Any]:
        return {
            "name": "get_course_outline",
            "description": (
                "Retrieve the outline of a course: course title, course link, and the "
                "complete list of lessons (lesson number and lesson title for each). "
                "Use this for outline / structure / table-of-contents queries, e.g. "
                "'what lessons are in the MCP course', 'show me the outline of X', "
                "'list the lessons of Y'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "course_title": {
                        "type": "string",
                        "description": "Course title (partial matches work, e.g. 'MCP', 'Introduction')"
                    }
                },
                "required": ["course_title"]
            }
        }

    def execute(self, course_title: str) -> str:
        import json

        try:
            results = self.store.course_catalog.query(
                query_texts=[course_title],
                n_results=1
            )
        except Exception as e:
            return f"Error retrieving course outline: {e}"

        metadatas = results.get('metadatas') or []
        if not metadatas or not metadatas[0]:
            return f"No course found matching '{course_title}'."

        metadata = metadatas[0][0]
        resolved_title = metadata.get('title', 'unknown')
        course_link = metadata.get('course_link') or 'N/A'

        lessons = []
        lessons_json = metadata.get('lessons_json')
        if lessons_json:
            try:
                lessons = json.loads(lessons_json)
            except json.JSONDecodeError:
                lessons = []

        # UI source: link the course tile back to its course page
        self.last_sources = [{"text": resolved_title, "link": metadata.get('course_link')}]

        lines = [
            f"Course Title: {resolved_title}",
            f"Course Link: {course_link}",
            f"Lessons ({len(lessons)}):",
        ]
        if not lessons:
            lines.append("  (no lessons found)")
        else:
            lessons_sorted = sorted(lessons, key=lambda l: l.get('lesson_number', 0))
            for lesson in lessons_sorted:
                num = lesson.get('lesson_number', '?')
                title = lesson.get('lesson_title', 'Untitled')
                lines.append(f"  Lesson {num}: {title}")

        return "\n".join(lines)


class ToolManager:
    """Manages available tools for the AI"""
    
    def __init__(self):
        self.tools = {}
    
    def register_tool(self, tool: Tool):
        """Register any tool that implements the Tool interface"""
        tool_def = tool.get_tool_definition()
        tool_name = tool_def.get("name")
        if not tool_name:
            raise ValueError("Tool must have a 'name' in its definition")
        self.tools[tool_name] = tool

    
    def get_tool_definitions(self) -> list:
        """Get all tool definitions for Anthropic tool calling"""
        return [tool.get_tool_definition() for tool in self.tools.values()]
    
    def execute_tool(self, tool_name: str, **kwargs) -> str:
        """Execute a tool by name with given parameters"""
        if tool_name not in self.tools:
            return f"Tool '{tool_name}' not found"
        
        return self.tools[tool_name].execute(**kwargs)
    
    def get_last_sources(self) -> list:
        """Get sources from the last search operation"""
        # Check all tools for last_sources attribute
        for tool in self.tools.values():
            if hasattr(tool, 'last_sources') and tool.last_sources:
                return tool.last_sources
        return []

    def reset_sources(self):
        """Reset sources from all tools that track sources"""
        for tool in self.tools.values():
            if hasattr(tool, 'last_sources'):
                tool.last_sources = []