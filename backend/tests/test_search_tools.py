from config import config
from search_tools import CourseSearchTool, CourseOutlineTool, ToolManager
from conftest import FIXTURE_COURSE_TITLE


MCP = "MCP Course"


class TestCourseSearchToolExecute:
    def test_passes_parameters_to_store(self, mock_store, make_results):
        mock_store.search.return_value = make_results(["doc"], [{"course_title": MCP, "lesson_number": 1}])
        CourseSearchTool(mock_store).execute(query="servers", course_name="MCP", lesson_number=1)
        mock_store.search.assert_called_once_with(query="servers", course_name="MCP", lesson_number=1)

    def test_formats_results_with_headers(self, mock_store, make_results):
        mock_store.search.return_value = make_results(
            ["first chunk", "second chunk"],
            [{"course_title": MCP, "lesson_number": 1}, {"course_title": MCP, "lesson_number": None}],
        )
        out = CourseSearchTool(mock_store).execute(query="q")
        assert out == f"[{MCP} - Lesson 1]\nfirst chunk\n\n[{MCP}]\nsecond chunk"

    def test_returns_store_error(self, mock_store, make_results):
        mock_store.search.return_value = make_results([], [], error="No course found matching 'xyz'")
        out = CourseSearchTool(mock_store).execute(query="q", course_name="xyz")
        assert out == "No course found matching 'xyz'"

    def test_empty_results_message_includes_filters(self, mock_store, make_results):
        mock_store.search.return_value = make_results([], [])
        out = CourseSearchTool(mock_store).execute(query="q", course_name="MCP", lesson_number=3)
        assert out == "No relevant content found in course 'MCP' in lesson 3."

    def test_empty_results_message_without_filters(self, mock_store, make_results):
        mock_store.search.return_value = make_results([], [])
        assert CourseSearchTool(mock_store).execute(query="q") == "No relevant content found."

    def test_sets_deduplicated_sources_with_links(self, mock_store, make_results):
        mock_store.search.return_value = make_results(
            ["a", "b", "c"],
            [
                {"course_title": MCP, "lesson_number": 1},
                {"course_title": MCP, "lesson_number": 1},
                {"course_title": MCP, "lesson_number": None},
            ],
        )
        tool = CourseSearchTool(mock_store)
        tool.execute(query="q")
        assert tool.last_sources == [
            {"label": f"{MCP} - Lesson 1", "link": f"https://example.com/{MCP}/lesson/1"},
            {"label": MCP, "link": f"https://example.com/{MCP}"},
        ]
        mock_store.get_lesson_link.assert_called_once_with(MCP, 1)
        mock_store.get_course_link.assert_called_once_with(MCP)

    def test_error_does_not_set_sources(self, mock_store, make_results):
        mock_store.search.return_value = make_results([], [], error="boom")
        tool = CourseSearchTool(mock_store)
        tool.execute(query="q")
        assert tool.last_sources == []


class TestToolManager:
    def test_registers_and_executes_search_tool(self, mock_store, make_results):
        mock_store.search.return_value = make_results(["doc"], [{"course_title": MCP, "lesson_number": 0}])
        manager = ToolManager()
        manager.register_tool(CourseSearchTool(mock_store))
        assert [d["name"] for d in manager.get_tool_definitions()] == ["search_course_content"]
        assert "doc" in manager.execute_tool("search_course_content", query="q")

    def test_unknown_tool(self):
        assert ToolManager().execute_tool("nope") == "Tool 'nope' not found"

    def test_sources_roundtrip_and_reset(self, mock_store, make_results):
        mock_store.search.return_value = make_results(["doc"], [{"course_title": MCP, "lesson_number": 0}])
        manager = ToolManager()
        manager.register_tool(CourseSearchTool(mock_store))
        manager.execute_tool("search_course_content", query="q")
        assert manager.get_last_sources()[0]["label"] == f"{MCP} - Lesson 0"
        manager.reset_sources()
        assert manager.get_last_sources() == []

    def test_sources_accumulate_across_calls_without_duplicates(self, mock_store, make_results):
        mock_store.search.side_effect = [
            make_results(["a"], [{"course_title": MCP, "lesson_number": 1}]),
            make_results(["b", "c"], [{"course_title": MCP, "lesson_number": 1}, {"course_title": "Other", "lesson_number": 2}]),
        ]
        manager = ToolManager()
        manager.register_tool(CourseSearchTool(mock_store))
        manager.execute_tool("search_course_content", query="first")
        manager.execute_tool("search_course_content", query="second")
        assert [s["label"] for s in manager.get_last_sources()] == [f"{MCP} - Lesson 1", "Other - Lesson 2"]
        manager.reset_sources()
        assert manager.get_last_sources() == []

    def test_sources_from_different_tools_are_combined(self, mock_store, make_results):
        mock_store.search.return_value = make_results(["a"], [{"course_title": MCP, "lesson_number": 4}])
        mock_store.get_course_outline.return_value = {"title": MCP, "course_link": "https://x", "lessons": []}
        manager = ToolManager()
        manager.register_tool(CourseSearchTool(mock_store))
        manager.register_tool(CourseOutlineTool(mock_store))
        manager.execute_tool("get_course_outline", course_title="MCP")
        manager.execute_tool("search_course_content", query="q")
        assert [s["label"] for s in manager.get_last_sources()] == [MCP, f"{MCP} - Lesson 4"]

    def test_failed_search_does_not_reuse_stale_sources(self, mock_store, make_results):
        mock_store.search.side_effect = [
            make_results(["a"], [{"course_title": MCP, "lesson_number": 1}]),
            make_results([], [], error="boom"),
        ]
        manager = ToolManager()
        manager.register_tool(CourseSearchTool(mock_store))
        manager.execute_tool("search_course_content", query="first")
        manager.reset_sources()
        manager.execute_tool("search_course_content", query="second")
        assert manager.get_last_sources() == []


class TestCourseSearchToolAgainstRealStore:
    def test_max_results_is_positive(self):
        assert config.MAX_RESULTS > 0, "MAX_RESULTS <= 0 makes every search return nothing"

    def test_returns_content_without_filter(self, real_store):
        out = CourseSearchTool(real_store).execute(query="What are pytest fixtures?")
        assert "fixture" in out.lower()
        assert not out.startswith("Search error")

    def test_returns_content_with_course_and_lesson_filter(self, real_store):
        tool = CourseSearchTool(real_store)
        out = tool.execute(query="MagicMock", course_name="pytest", lesson_number=2)
        assert f"[{FIXTURE_COURSE_TITLE} - Lesson 2]" in out
        assert "MagicMock" in out
        assert tool.last_sources[0]["link"] == "https://example.com/courses/pytest/lesson/2"
