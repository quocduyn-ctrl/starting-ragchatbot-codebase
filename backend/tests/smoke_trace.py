"""Live smoke test: traces tool calls during real /api/query equivalents.

Wraps tool_manager.execute_tool to record each invocation, then issues queries
designed to exercise the new 2-round flow. Prints the tool-call sequence and
the final answer.

Run from backend/:  uv run python tests/smoke_trace.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag_system import RAGSystem
from config import config


def trace_query(rag: RAGSystem, query: str, label: str) -> None:
    calls: list[tuple[str, dict]] = []
    original = rag.tool_manager.execute_tool

    def traced(name, **kwargs):
        calls.append((name, kwargs))
        return original(name, **kwargs)

    rag.tool_manager.execute_tool = traced
    try:
        answer, _sources = rag.query(query)
    finally:
        rag.tool_manager.execute_tool = original

    print(f"\n=== {label} ===")
    print(f"Query: {query}")
    print(f"Tool calls made: {len(calls)}")
    for i, (name, kwargs) in enumerate(calls, 1):
        print(f"  [{i}] {name}({kwargs})")
    print(f"Answer (first 400 chars): {answer[:400]}...")


if __name__ == "__main__":
    rag = RAGSystem(config)
    trace_query(
        rag,
        "What is in lesson 4 of the MCP course, and which other course covers a similar topic?",
        "Multi-step (outline + search)",
    )
    trace_query(
        rag,
        "What is retrieval augmented generation?",
        "Single-step (general knowledge / search)",
    )
    trace_query(
        rag,
        "List the lessons of the MCP course",
        "Single-step (outline only)",
    )
