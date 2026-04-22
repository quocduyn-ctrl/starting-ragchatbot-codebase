# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

Requires Git Bash on Windows. Run from the project root:

```bash
./run.sh
```

Or manually:

```bash
cd backend
uv run uvicorn app:app --reload --port 8000
```

App is served at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.

**First-time setup:**
```bash
uv sync                        # install dependencies
cp .env.example .env           # then add ANTHROPIC_API_KEY to .env
```

There is no test suite and no linter configured.

## Architecture

This is a RAG chatbot where the backend serves both the API and the frontend static files. There is no separate frontend build step — the `frontend/` directory is mounted directly by FastAPI.

### Request flow for a user query

1. `frontend/script.js` — POSTs `{ query, session_id }` to `/api/query`
2. `backend/app.py` — validates request, creates a session if needed, delegates to `RAGSystem.query()`
3. `backend/rag_system.py` — fetches conversation history, calls `AIGenerator.generate_response()`
4. `backend/ai_generator.py` — makes a first Claude API call with the `search_course_content` tool available
5. If Claude invokes the tool → `backend/search_tools.py` → `backend/vector_store.py` performs semantic search in ChromaDB and returns formatted chunks
6. A second Claude API call synthesizes the chunks into a final answer
7. Sources and session history are updated; `{ answer, sources, session_id }` is returned to the browser

### Document ingestion (on startup)

`app.py` startup event → `RAGSystem.add_course_folder("../docs")` → `DocumentProcessor.process_course_document()` parses each `.txt` file → `VectorStore` stores results in two ChromaDB collections:

- **`course_catalog`** — one document per course (title, instructor, link); used for semantic course-name resolution
- **`course_content`** — chunked lesson text with `course_title` and `lesson_number` metadata; used for content search

Courses already present in ChromaDB are skipped (deduplication by title).

### Course document format

Files in `docs/` must follow this structure:

```
Course Title: <title>
Course Link: <url>
Course Instructor: <name>

Lesson 0: <lesson title>
Lesson Link: <url>
<lesson content...>

Lesson 1: <lesson title>
...
```

### Key configuration (`backend/config.py`)

| Setting | Default | Effect |
|---|---|---|
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Claude model used for generation |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model for ChromaDB |
| `CHUNK_SIZE` | `800` | Max chars per content chunk |
| `CHUNK_OVERLAP` | `100` | Overlap between consecutive chunks |
| `MAX_RESULTS` | `5` | Top-k chunks returned per search |
| `MAX_HISTORY` | `2` | Conversation turns kept in session memory |
| `CHROMA_PATH` | `./chroma_db` | Where ChromaDB persists data on disk |

All values can be overridden via `.env`.

### Adding a new tool for Claude

1. Create a class extending `Tool` in `backend/search_tools.py` implementing `get_tool_definition()` and `execute()`
2. Register it in `RAGSystem.__init__()` via `self.tool_manager.register_tool(your_tool)`

Claude receives all registered tool definitions on every query and decides autonomously whether to call them. Currently limited to one search call per query by the system prompt.
