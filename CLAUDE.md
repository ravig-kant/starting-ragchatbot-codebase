# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A RAG chatbot that answers questions about course materials. It has a FastAPI backend, ChromaDB for vector storage with sentence-transformers embeddings, Anthropic Claude with tool calling, and a vanilla HTML/JS frontend.

## Commands

Requires Python 3.13+ and `uv`. Put `ANTHROPIC_API_KEY` in a root `.env` file (see `.env.example`).

```bash
uv sync                                             # install deps
./run.sh                                            # start server (http://localhost:8000, API docs at /docs)
cd backend && uv run uvicorn app:app --reload --port 8000   # manual start
```

Code quality (dev deps: black, isort, flake8, pytest; config in `pyproject.toml` and `.flake8`):

```bash
./scripts/format.sh                                 # auto-format: isort + black
./scripts/lint.sh                                   # check only: isort/black --check + flake8
./scripts/quality.sh                                # lint.sh + pytest (run before committing)
cd backend && uv run pytest                         # tests only
```

Black owns line length (88), so flake8 ignores E501 and the black-incompatible rules.

**Always use `uv`; never call `pip` or `python` directly.**
- Run Python files with `uv run python <file>.py` (or `uv run <tool>`).
- Add dependencies with `uv add <package>`, not `pip install`.

## Architecture

**Run from `backend/`.** `app.py` uses relative paths: `../docs` for course files, `../frontend` for static assets, and `./chroma_db` for the persistent vector DB.

**Request flow:** `POST /api/query` → `RAGSystem.query()` (`rag_system.py`) → `AIGenerator.generate_response()` (`ai_generator.py`). Claude is called with the `search_course_content` tool. If it returns `stop_reason == "tool_use"`, `_handle_tool_execution` runs the tool through `ToolManager` and makes a **second API call without tools**. The design therefore allows one round of tool use per query, and the system prompt also says "one search per query maximum". Sources for the UI come from side-channel state: `CourseSearchTool.last_sources` is read by `ToolManager.get_last_sources()` and then cleared by `reset_sources()` after each query.

**Tools** (`search_tools.py`): subclass `Tool` (`get_tool_definition()` returns an Anthropic tool schema, `execute(**kwargs)` returns a string) and register it with `ToolManager` in `RAGSystem.__init__`. To show sources in the UI, a tool should set a `last_sources` attribute.

**Vector store** (`vector_store.py`) has two ChromaDB collections:
- `course_catalog`: one doc per course; the ID is the course title. Lesson metadata is stored as JSON in `lessons_json`. Used to resolve fuzzy `course_name` values to an exact title through semantic search (`_resolve_course_name`).
- `course_content`: text chunks with `course_title` / `lesson_number` metadata. `search()` resolves the course name first, then filters content with a `where` clause.

**Ingestion** (`document_processor.py`): on startup, `.txt/.pdf/.docx` files in `docs/` are parsed. Courses whose title is already in ChromaDB are skipped, so if you edit an existing doc, delete `backend/chroma_db` or use `clear_existing=True` to re-ingest it. Expected file format:
```
Course Title: <title>
Course Link: <url>
Course Instructor: <name>

Lesson 0: <lesson title>
Lesson Link: <url>
<content...>
```
Chunks are built from sentences (`CHUNK_SIZE=800`, `CHUNK_OVERLAP=100` characters) and prefixed with lesson context. The prefix differs by lesson: the last lesson's chunks all get `Course <title> Lesson N content:`, while earlier lessons get `Lesson N content:` on their first chunk only.

**Sessions** (`session_manager.py`): in-memory only, so they are lost on restart. History is capped at `MAX_HISTORY` exchanges and passed to Claude as text in the system prompt, not as message turns.

**Config** lives in `backend/config.py` (a dataclass covering model name, embedding model, chunking, and result limits).

**Frontend** (`frontend/`): static files served by FastAPI at `/`. `script.js` calls `/api/query` and `/api/courses`, and renders answers as markdown with marked.js.
