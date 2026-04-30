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
# requires Python >= 3.13
uv sync                        # install dependencies
cp .env.example .env           # then add ANTHROPIC_API_KEY to .env
```

**Always use `uv` for Python operations in this project — never `pip` directly, and never the system Python.** Installs use `uv sync` / `uv add`; ad-hoc scripts use `uv run python ...`; the server uses `uv run uvicorn ...` (or `./run.sh`, which does the same).

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

### Bedrock proxy quirk

The second API call in `AIGenerator._handle_tool_execution` (`backend/ai_generator.py`) appends a plain text block after the tool results telling Claude not to call tools again. This is a workaround: Bedrock-proxied models ignore the "one search per query" rule in the system prompt and will attempt a second tool call otherwise. Preserve this text block when modifying the tool-handling flow — removing it re-introduces unbounded tool loops.

Sessions are stored only in memory (`SessionManager` is a plain dict keyed by session id) — restarting the server clears all conversation history.

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
| `ANTHROPIC_MODEL` | `aws/anthropic/bedrock-claude-sonnet-4-6` | Model ID — this is a Bedrock-routed model served via NVIDIA's proxy, not a native Anthropic model ID |
| `ANTHROPIC_BASE_URL` | `https://inference-api.nvidia.com` | API endpoint — routes Claude calls through NVIDIA's inference proxy (not `api.anthropic.com`) |
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
