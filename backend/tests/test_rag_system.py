import os

import pytest
from conftest import FIXTURE_COURSE_TITLE, message, text_block, tool_use_block


def script_claude(rag, *responses):
    rag.ai_generator.client.messages.create.side_effect = list(responses)


def search_then_answer(tool_input, answer="Fixtures provide reusable setup."):
    return (
        message(
            [tool_use_block("search_course_content", tool_input, id="toolu_1")],
            stop_reason="tool_use",
        ),
        message([text_block(answer)]),
    )


class TestContentQuery:
    def test_content_query_uses_search_results(self, temp_rag):
        script_claude(
            temp_rag,
            *search_then_answer(
                {
                    "query": "pytest fixtures",
                    "course_name": "pytest",
                    "lesson_number": 1,
                }
            ),
        )

        answer, sources = temp_rag.query("What are fixtures in the pytest course?")

        assert answer == "Fixtures provide reusable setup."
        calls = temp_rag.ai_generator.client.messages.create.call_args_list
        tool_names = [t["name"] for t in calls[0].kwargs["tools"]]
        assert "search_course_content" in tool_names
        tool_result = calls[1].kwargs["messages"][2]["content"][0]["content"]
        assert f"[{FIXTURE_COURSE_TITLE} - Lesson 1]" in tool_result
        assert "pytest.fixture" in tool_result
        assert sources == [
            {
                "label": f"{FIXTURE_COURSE_TITLE} - Lesson 1",
                "link": "https://example.com/courses/pytest/lesson/1",
            }
        ]
        assert temp_rag.tool_manager.get_last_sources() == []

    def test_query_wraps_user_question_in_prompt(self, temp_rag):
        script_claude(temp_rag, message([text_block("hi")]))
        temp_rag.query("hello")
        sent = temp_rag.ai_generator.client.messages.create.call_args.kwargs[
            "messages"
        ][0]["content"]
        assert sent == "Answer this question about course materials: hello"

    def test_session_history_passed_to_next_query(self, temp_rag):
        sid = temp_rag.session_manager.create_session()
        script_claude(
            temp_rag,
            *search_then_answer(
                {"query": "mocking"}, answer="Mocking replaces collaborators."
            ),
            message([text_block("Follow-up answer")]),
        )
        temp_rag.query("What is mocking?", sid)
        temp_rag.query("Tell me more", sid)
        system = temp_rag.ai_generator.client.messages.create.call_args.kwargs["system"]
        assert "User: What is mocking?" in system
        assert "Assistant: Mocking replaces collaborators." in system

    def test_no_course_match_is_returned_to_claude_not_raised(self, temp_rag):
        # The only course in the temp DB is matched for any name, so filter by a missing lesson instead
        script_claude(
            temp_rag,
            *search_then_answer(
                {"query": "anything", "lesson_number": 99}, answer="Nothing found."
            ),
        )
        answer, sources = temp_rag.query("What is in lesson 99?")
        tool_result = temp_rag.ai_generator.client.messages.create.call_args_list[
            1
        ].kwargs["messages"][2]["content"][0]["content"]
        assert tool_result == "No relevant content found in lesson 99."
        assert answer == "Nothing found."
        assert sources == []

    def test_empty_final_response_does_not_raise(self, temp_rag):
        script_claude(
            temp_rag,
            message(
                [tool_use_block("search_course_content", {"query": "fixtures"})],
                stop_reason="tool_use",
            ),
            message([]),
        )
        answer, _ = temp_rag.query("What are fixtures?")
        assert isinstance(answer, str) and answer

    def test_bad_tool_arguments_do_not_raise(self, temp_rag):
        script_claude(
            temp_rag,
            message(
                [
                    tool_use_block(
                        "search_course_content", {"query": "fixtures", "lesson": "1"}
                    )
                ],
                stop_reason="tool_use",
            ),
            message([text_block("Recovered")]),
        )
        answer, _ = temp_rag.query("What are fixtures?")
        assert answer == "Recovered"

    def test_outline_then_search_two_rounds(self, temp_rag):
        script_claude(
            temp_rag,
            message(
                [
                    tool_use_block(
                        "get_course_outline", {"course_title": "pytest"}, id="t1"
                    )
                ],
                stop_reason="tool_use",
            ),
            message(
                [
                    tool_use_block(
                        "search_course_content",
                        {"query": "Mocking", "lesson_number": 2},
                        id="t2",
                    )
                ],
                stop_reason="tool_use",
            ),
            message([text_block("Lesson 2 covers mocking with MagicMock.")]),
        )

        answer, sources = temp_rag.query(
            "What is the topic of lesson 2 of the pytest course, and what does it say?"
        )

        assert answer == "Lesson 2 covers mocking with MagicMock."
        calls = temp_rag.ai_generator.client.messages.create.call_args_list
        assert len(calls) == 3
        outline_result = calls[1].kwargs["messages"][2]["content"][0]["content"]
        assert "Lesson 2: Mocking" in outline_result
        search_result = calls[2].kwargs["messages"][4]["content"][0]["content"]
        assert f"[{FIXTURE_COURSE_TITLE} - Lesson 2]" in search_result
        assert "MagicMock" in search_result
        assert sources == [
            {
                "label": FIXTURE_COURSE_TITLE,
                "link": "https://example.com/courses/pytest",
            },
            {
                "label": f"{FIXTURE_COURSE_TITLE} - Lesson 2",
                "link": "https://example.com/courses/pytest/lesson/2",
            },
        ]
        assert temp_rag.tool_manager.get_last_sources() == []


class TestQueryEndpoint:
    @pytest.fixture
    def client(self, monkeypatch):
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        monkeypatch.chdir(backend_dir)  # app.py uses paths relative to backend/
        from fastapi.testclient import TestClient

        import app as app_module

        return app_module, TestClient(app_module.app)

    def test_returns_answer_and_sources(self, client, monkeypatch):
        app_module, http = client
        monkeypatch.setattr(
            app_module.rag_system,
            "query",
            lambda q, sid: (
                "answer",
                [{"label": "Course - Lesson 1", "link": "https://x"}],
            ),
        )
        r = http.post("/api/query", json={"query": "q"})
        assert r.status_code == 200
        body = r.json()
        assert body["answer"] == "answer"
        assert body["sources"] == [{"label": "Course - Lesson 1", "link": "https://x"}]
        assert body["session_id"]

    def test_rag_exception_becomes_500_with_detail(self, client, monkeypatch):
        app_module, http = client

        def boom(q, sid):
            raise IndexError("list index out of range")

        monkeypatch.setattr(app_module.rag_system, "query", boom)
        r = http.post("/api/query", json={"query": "q"})
        assert r.status_code == 500
        assert r.json()["detail"] == "list index out of range"
