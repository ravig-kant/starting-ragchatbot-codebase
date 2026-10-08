import os
import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Make backend modules importable as top-level modules (matches how app.py imports them)
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from config import config  # noqa: E402
from vector_store import VectorStore, SearchResults  # noqa: E402


FIXTURE_COURSE_TITLE = "Testing Fundamentals with Pytest"
FIXTURE_COURSE_LINK = "https://example.com/courses/pytest"

FIXTURE_COURSE_TEXT = f"""Course Title: {FIXTURE_COURSE_TITLE}
Course Link: {FIXTURE_COURSE_LINK}
Course Instructor: Ada Tester

Lesson 0: Introduction
Lesson Link: https://example.com/courses/pytest/lesson/0
Welcome to the course. Automated tests give you confidence that your code keeps working as it changes.

Lesson 1: Fixtures
Lesson Link: https://example.com/courses/pytest/lesson/1
Pytest fixtures provide reusable setup for tests. A fixture is a function decorated with pytest.fixture. Tests request fixtures by naming them as parameters.

Lesson 2: Mocking
Lesson Link: https://example.com/courses/pytest/lesson/2
Mocking replaces real collaborators with fake objects. The unittest.mock module provides MagicMock, which records how it was called so tests can make assertions about interactions.
"""


# ---------- Search result helpers ----------

@pytest.fixture
def make_results():
    def _make(docs, metas, error=None):
        return SearchResults(documents=docs, metadata=metas, distances=[0.1] * len(docs), error=error)
    return _make


@pytest.fixture
def mock_store():
    store = MagicMock(spec=VectorStore)
    store.get_lesson_link.side_effect = lambda title, n: f"https://example.com/{title}/lesson/{n}"
    store.get_course_link.side_effect = lambda title: f"https://example.com/{title}"
    return store


# ---------- Fake Anthropic message objects ----------

def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, input, id="toolu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=input, id=id)


def message(content, stop_reason="end_turn"):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


# ---------- Real (temporary) store and RAG system ----------

@pytest.fixture(scope="session")
def course_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("docs") / "test_course.txt"
    path.write_text(FIXTURE_COURSE_TEXT)
    return str(path)


@pytest.fixture(scope="session")
def test_config(tmp_path_factory):
    return replace(
        config,
        CHROMA_PATH=str(tmp_path_factory.mktemp("chroma")),
        ANTHROPIC_API_KEY="test-key",
    )


@pytest.fixture(scope="session")
def _rag_session(test_config, course_file):
    from rag_system import RAGSystem
    rag = RAGSystem(test_config)
    course, n_chunks = rag.add_course_document(course_file)
    assert course is not None and n_chunks > 0, "fixture course failed to ingest"
    return rag


@pytest.fixture
def temp_rag(_rag_session):
    """Real RAG system over a temp Chroma DB, with Claude replaced by a MagicMock"""
    _rag_session.ai_generator.client = MagicMock()
    _rag_session.tool_manager.reset_sources()
    return _rag_session


@pytest.fixture
def real_store(_rag_session):
    return _rag_session.vector_store


# ---------- API test app ----------
# app.py builds a real RAGSystem and mounts ../frontend at import time, so the API tests
# use this mirror of its endpoints with an injectable rag_system and static directory.

FIXTURE_INDEX_HTML = "<!doctype html><html><body><h1>Course Materials Assistant</h1></body></html>"


def build_test_app(rag_system, static_dir=None):
    from typing import List, Optional

    from fastapi import FastAPI, HTTPException
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel

    class QueryRequest(BaseModel):
        query: str
        session_id: Optional[str] = None

    class Source(BaseModel):
        label: str
        link: Optional[str] = None

    class QueryResponse(BaseModel):
        answer: str
        sources: List[Source]
        session_id: str

    class CourseStats(BaseModel):
        total_courses: int
        course_titles: List[str]

    app = FastAPI(title="Course Materials RAG System (test)")

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

    @app.delete("/api/session/{session_id}")
    async def delete_session(session_id: str):
        rag_system.session_manager.delete_session(session_id)
        return {"status": "ok"}

    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


@pytest.fixture
def mock_rag():
    """MagicMock RAGSystem with canned query/analytics responses"""
    rag = MagicMock()
    rag.session_manager.create_session.return_value = "session_1"
    rag.query.return_value = (
        "Fixtures provide reusable setup.",
        [{"label": f"{FIXTURE_COURSE_TITLE} - Lesson 1", "link": "https://example.com/courses/pytest/lesson/1"}],
    )
    rag.get_course_analytics.return_value = {"total_courses": 1, "course_titles": [FIXTURE_COURSE_TITLE]}
    return rag


@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / "index.html").write_text(FIXTURE_INDEX_HTML)
    return str(tmp_path)


@pytest.fixture
def api_client(mock_rag, static_dir):
    from fastapi.testclient import TestClient
    with TestClient(build_test_app(mock_rag, static_dir)) as client:
        yield client
