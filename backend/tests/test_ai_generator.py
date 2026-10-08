import os
from unittest.mock import MagicMock, call

import pytest
from conftest import message, text_block, tool_use_block

from ai_generator import AIGenerator

SEARCH_TOOL_DEF = {
    "name": "search_course_content",
    "description": "Search course materials",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}


@pytest.fixture
def generator():
    gen = AIGenerator(api_key="test-key", model="test-model")
    gen.client = MagicMock()
    return gen


@pytest.fixture
def tool_manager():
    tm = MagicMock()
    tm.execute_tool.return_value = (
        "[MCP Course - Lesson 1]\nMCP uses a client-server architecture."
    )
    return tm


def create_calls(gen):
    return [c.kwargs for c in gen.client.messages.create.call_args_list]


class TestDirectAnswer:
    def test_returns_text_and_offers_tools(self, generator, tool_manager):
        generator.client.messages.create.return_value = message([text_block("Hello")])
        out = generator.generate_response(
            "hi", tools=[SEARCH_TOOL_DEF], tool_manager=tool_manager
        )
        assert out == "Hello"
        params = create_calls(generator)[0]
        assert params["tools"] == [SEARCH_TOOL_DEF]
        assert params["tool_choice"] == {"type": "auto"}
        tool_manager.execute_tool.assert_not_called()

    def test_history_in_system_prompt(self, generator):
        generator.client.messages.create.return_value = message([text_block("ok")])
        generator.generate_response(
            "hi", conversation_history="User: earlier\nAssistant: reply"
        )
        assert "User: earlier\nAssistant: reply" in create_calls(generator)[0]["system"]


class TestSearchToolCall:
    def _script(self, generator, first_content, final_content):
        generator.client.messages.create.side_effect = [
            message(first_content, stop_reason="tool_use"),
            message(final_content),
        ]

    def test_executes_search_tool_and_returns_final_answer(
        self, generator, tool_manager
    ):
        block = tool_use_block(
            "search_course_content",
            {"query": "architecture", "course_name": "MCP"},
            id="toolu_abc",
        )
        self._script(generator, [block], [text_block("MCP is client-server.")])

        out = generator.generate_response(
            "q", tools=[SEARCH_TOOL_DEF], tool_manager=tool_manager
        )

        assert out == "MCP is client-server."
        tool_manager.execute_tool.assert_called_once_with(
            "search_course_content", query="architecture", course_name="MCP"
        )

        second = create_calls(generator)[1]
        assert second["tools"] == [SEARCH_TOOL_DEF]  # round 2 may use tools again
        msgs = second["messages"]
        assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
        assert msgs[1]["content"] == [block]
        assert msgs[2]["content"] == [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_abc",
                "content": tool_manager.execute_tool.return_value,
            }
        ]

    def test_multiple_tool_calls_all_executed(self, generator, tool_manager):
        blocks = [
            tool_use_block("search_course_content", {"query": "a"}, id="t1"),
            tool_use_block("search_course_content", {"query": "b"}, id="t2"),
        ]
        self._script(generator, blocks, [text_block("done")])
        generator.generate_response(
            "q", tools=[SEARCH_TOOL_DEF], tool_manager=tool_manager
        )
        assert tool_manager.execute_tool.call_count == 2
        results = create_calls(generator)[1]["messages"][2]["content"]
        assert [r["tool_use_id"] for r in results] == ["t1", "t2"]

    def test_text_before_tool_use(self, generator, tool_manager):
        self._script(
            generator,
            [
                text_block("Let me search."),
                tool_use_block("search_course_content", {"query": "a"}),
            ],
            [text_block("answer")],
        )
        assert (
            generator.generate_response(
                "q", tools=[SEARCH_TOOL_DEF], tool_manager=tool_manager
            )
            == "answer"
        )

    # ----- Robustness: each of these would surface as HTTP 500 / "Query failed" -----

    def test_empty_final_response_does_not_raise(self, generator, tool_manager):
        self._script(
            generator, [tool_use_block("search_course_content", {"query": "a"})], []
        )
        out = generator.generate_response(
            "q", tools=[SEARCH_TOOL_DEF], tool_manager=tool_manager
        )
        assert isinstance(out, str) and out

    def test_final_response_without_leading_text_block(self, generator, tool_manager):
        self._script(
            generator,
            [tool_use_block("search_course_content", {"query": "a"})],
            [
                tool_use_block("search_course_content", {"query": "again"}, id="t9"),
                text_block("answer"),
            ],
        )
        out = generator.generate_response(
            "q", tools=[SEARCH_TOOL_DEF], tool_manager=tool_manager
        )
        assert out == "answer"

    def test_tool_exception_is_reported_to_claude(self, generator, tool_manager):
        tool_manager.execute_tool.side_effect = TypeError(
            "execute() got an unexpected keyword argument 'lesson'"
        )
        self._script(
            generator,
            [tool_use_block("search_course_content", {"query": "a", "lesson": 1})],
            [text_block("sorry")],
        )
        out = generator.generate_response(
            "q", tools=[SEARCH_TOOL_DEF], tool_manager=tool_manager
        )
        assert out == "sorry"
        calls = create_calls(generator)
        assert len(calls) == 2
        assert "tools" not in calls[1]
        result = calls[1]["messages"][2]["content"][0]
        assert result.get("is_error") is True
        assert "unexpected keyword argument" in result["content"]


OUTLINE_TOOL_DEF = {
    "name": "get_course_outline",
    "description": "Get a course outline",
    "input_schema": {
        "type": "object",
        "properties": {"course_title": {"type": "string"}},
        "required": ["course_title"],
    },
}
TOOLS = [SEARCH_TOOL_DEF, OUTLINE_TOOL_DEF]

OUTLINE_RESULT = "Course Title: MCP Course\nCourse Link: https://x\nLessons (5):\n- Lesson 4: Creating An MCP Server"
SEARCH_RESULT = "[Other Course - Lesson 2]\nBuilding servers that expose tools."


def tool_round(*blocks):
    return message(list(blocks), stop_reason="tool_use")


def roles(call_kwargs):
    return [m["role"] for m in call_kwargs["messages"]]


class TestSequentialToolRounds:
    def test_outline_then_search_then_answer(self, generator, tool_manager):
        tool_manager.execute_tool.side_effect = [OUTLINE_RESULT, SEARCH_RESULT]
        outline = tool_use_block("get_course_outline", {"course_title": "MCP"}, id="t1")
        search = tool_use_block(
            "search_course_content", {"query": "Creating An MCP Server"}, id="t2"
        )
        generator.client.messages.create.side_effect = [
            tool_round(outline),
            tool_round(search),
            message([text_block("Other Course covers building MCP servers.")]),
        ]

        out = generator.generate_response(
            "Find a course on the same topic as lesson 4 of MCP",
            tools=TOOLS,
            tool_manager=tool_manager,
        )

        assert out == "Other Course covers building MCP servers."
        assert tool_manager.execute_tool.call_args_list == [
            call("get_course_outline", course_title="MCP"),
            call("search_course_content", query="Creating An MCP Server"),
        ]
        calls = create_calls(generator)
        assert len(calls) == 3
        assert calls[0]["tools"] == TOOLS and calls[1]["tools"] == TOOLS
        assert "tools" not in calls[2]
        # Round 2 sees round 1's outline result
        assert roles(calls[1]) == ["user", "assistant", "user"]
        assert calls[1]["messages"][2]["content"][0] == {
            "type": "tool_result",
            "tool_use_id": "t1",
            "content": OUTLINE_RESULT,
        }
        # Final call carries the full conversation
        assert roles(calls[2]) == ["user", "assistant", "user", "assistant", "user"]
        assert calls[2]["messages"][1]["content"] == [outline]
        assert calls[2]["messages"][3]["content"] == [search]
        assert calls[2]["messages"][4]["content"][0]["tool_use_id"] == "t2"
        assert calls[2]["messages"][4]["content"][0]["content"] == SEARCH_RESULT

    def test_one_round_then_answer(self, generator, tool_manager):
        generator.client.messages.create.side_effect = [
            tool_round(tool_use_block("search_course_content", {"query": "a"})),
            message([text_block("answer")]),
        ]
        out = generator.generate_response("q", tools=TOOLS, tool_manager=tool_manager)
        assert out == "answer"
        calls = create_calls(generator)
        assert len(calls) == 2
        assert all(c["tools"] == TOOLS for c in calls)
        assert tool_manager.execute_tool.call_count == 1

    def test_stops_after_max_rounds_even_if_claude_wants_more(
        self, generator, tool_manager
    ):
        generator.client.messages.create.side_effect = [
            tool_round(
                tool_use_block("search_course_content", {"query": "a"}, id="t1")
            ),
            tool_round(
                tool_use_block("search_course_content", {"query": "b"}, id="t2")
            ),
            tool_round(
                text_block("Best answer so far."),
                tool_use_block("search_course_content", {"query": "c"}, id="t3"),
            ),
        ]
        out = generator.generate_response("q", tools=TOOLS, tool_manager=tool_manager)
        assert out == "Best answer so far."
        assert generator.client.messages.create.call_count == 3
        assert [
            c.kwargs["query"] for c in tool_manager.execute_tool.call_args_list
        ] == ["a", "b"]

    def test_tool_error_in_round_one_stops_tool_use(self, generator, tool_manager):
        tool_manager.execute_tool.side_effect = RuntimeError("db down")
        generator.client.messages.create.side_effect = [
            tool_round(
                tool_use_block("search_course_content", {"query": "a"}, id="t1")
            ),
            message([text_block("Search is unavailable right now.")]),
        ]
        out = generator.generate_response("q", tools=TOOLS, tool_manager=tool_manager)
        assert out == "Search is unavailable right now."
        calls = create_calls(generator)
        assert len(calls) == 2
        assert "tools" not in calls[1]
        assert calls[1]["messages"][2]["content"] == [
            {
                "type": "tool_result",
                "tool_use_id": "t1",
                "content": "Tool error: db down",
                "is_error": True,
            }
        ]
        assert tool_manager.execute_tool.call_count == 1

    def test_tool_error_in_round_two(self, generator, tool_manager):
        tool_manager.execute_tool.side_effect = [OUTLINE_RESULT, RuntimeError("boom")]
        generator.client.messages.create.side_effect = [
            tool_round(
                tool_use_block("get_course_outline", {"course_title": "MCP"}, id="t1")
            ),
            tool_round(
                tool_use_block("search_course_content", {"query": "x"}, id="t2")
            ),
            message([text_block("Partial answer.")]),
        ]
        out = generator.generate_response("q", tools=TOOLS, tool_manager=tool_manager)
        assert out == "Partial answer."
        calls = create_calls(generator)
        assert len(calls) == 3
        assert "tools" not in calls[2]
        assert calls[2]["messages"][4]["content"][0]["is_error"] is True

    def test_success_and_error_in_same_round(self, generator, tool_manager):
        tool_manager.execute_tool.side_effect = ["ok result", ValueError("bad args")]
        generator.client.messages.create.side_effect = [
            tool_round(
                tool_use_block("search_course_content", {"query": "a"}, id="t1"),
                tool_use_block("search_course_content", {"query": "b"}, id="t2"),
            ),
            message([text_block("done")]),
        ]
        assert (
            generator.generate_response("q", tools=TOOLS, tool_manager=tool_manager)
            == "done"
        )
        calls = create_calls(generator)
        assert len(calls) == 2
        assert "tools" not in calls[1]
        results = calls[1]["messages"][2]["content"]
        assert [(r["tool_use_id"], r.get("is_error", False)) for r in results] == [
            ("t1", False),
            ("t2", True),
        ]
        assert results[0]["content"] == "ok result"

    def test_tool_use_without_tool_manager_returns_text(self, generator):
        generator.client.messages.create.side_effect = [
            tool_round(
                text_block("Let me look."),
                tool_use_block("search_course_content", {"query": "a"}),
            ),
        ]
        out = generator.generate_response("q", tools=TOOLS)
        assert out == "Let me look."
        assert generator.client.messages.create.call_count == 1

    def test_max_tool_rounds_is_configurable(self, tool_manager):
        gen = AIGenerator(api_key="test-key", model="test-model", max_tool_rounds=1)
        gen.client = MagicMock()
        gen.client.messages.create.side_effect = [
            tool_round(tool_use_block("search_course_content", {"query": "a"})),
            message([text_block("answer")]),
        ]
        assert (
            gen.generate_response("q", tools=TOOLS, tool_manager=tool_manager)
            == "answer"
        )
        calls = create_calls(gen)
        assert len(calls) == 2
        assert "tools" not in calls[1]

    def test_system_prompt_and_history_sent_every_round(self, generator, tool_manager):
        generator.client.messages.create.side_effect = [
            tool_round(
                tool_use_block("search_course_content", {"query": "a"}, id="t1")
            ),
            tool_round(
                tool_use_block("search_course_content", {"query": "b"}, id="t2")
            ),
            message([text_block("answer")]),
        ]
        generator.generate_response(
            "q",
            conversation_history="User: hi\nAssistant: hello",
            tools=TOOLS,
            tool_manager=tool_manager,
        )
        systems = [c["system"] for c in create_calls(generator)]
        assert len(systems) == 3
        assert len(set(systems)) == 1
        assert "User: hi\nAssistant: hello" in systems[0]


@pytest.mark.skipif(
    not (os.getenv("RUN_LIVE_TESTS") == "1" and os.getenv("ANTHROPIC_API_KEY")),
    reason="set RUN_LIVE_TESTS=1 and ANTHROPIC_API_KEY to call the real API",
)
def test_live_tool_round_trip(tool_manager):
    from config import config

    gen = AIGenerator(config.ANTHROPIC_API_KEY, config.ANTHROPIC_MODEL)
    out = gen.generate_response(
        "Answer this question about course materials: What does lesson 1 of the MCP course say about architecture?",
        tools=[SEARCH_TOOL_DEF],
        tool_manager=tool_manager,
    )
    tool_manager.execute_tool.assert_called()
    assert isinstance(out, str) and out


@pytest.mark.skipif(
    not (os.getenv("RUN_LIVE_TESTS") == "1" and os.getenv("ANTHROPIC_API_KEY")),
    reason="set RUN_LIVE_TESTS=1 and ANTHROPIC_API_KEY to call the real API",
)
def test_live_two_round_tool_use():
    from config import config

    tm = MagicMock()
    tm.execute_tool.side_effect = lambda name, **kw: (
        OUTLINE_RESULT if name == "get_course_outline" else SEARCH_RESULT
    )
    gen = AIGenerator(config.ANTHROPIC_API_KEY, config.ANTHROPIC_MODEL)
    out = gen.generate_response(
        "Answer this question about course materials: "
        "Search for a course that discusses the same topic as lesson 4 of the MCP course",
        tools=TOOLS,
        tool_manager=tm,
    )
    names = [c.args[0] for c in tm.execute_tool.call_args_list]
    assert names[0] == "get_course_outline"
    assert "search_course_content" in names
    assert isinstance(out, str) and out
