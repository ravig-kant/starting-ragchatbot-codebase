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
from vector_store import SearchResults, VectorStore  # noqa: E402

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
        return SearchResults(
            documents=docs, metadata=metas, distances=[0.1] * len(docs), error=error
        )

    return _make


@pytest.fixture
def mock_store():
    store = MagicMock(spec=VectorStore)
    store.get_lesson_link.side_effect = (
        lambda title, n: f"https://example.com/{title}/lesson/{n}"
    )
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
