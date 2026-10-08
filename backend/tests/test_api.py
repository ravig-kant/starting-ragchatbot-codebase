from conftest import FIXTURE_COURSE_TITLE, FIXTURE_INDEX_HTML


class TestQueryEndpoint:
    def test_returns_answer_sources_and_new_session(self, api_client, mock_rag):
        r = api_client.post("/api/query", json={"query": "What are fixtures?"})

        assert r.status_code == 200
        assert r.json() == {
            "answer": "Fixtures provide reusable setup.",
            "sources": [
                {
                    "label": f"{FIXTURE_COURSE_TITLE} - Lesson 1",
                    "link": "https://example.com/courses/pytest/lesson/1",
                }
            ],
            "session_id": "session_1",
        }
        mock_rag.session_manager.create_session.assert_called_once()
        mock_rag.query.assert_called_once_with("What are fixtures?", "session_1")

    def test_reuses_provided_session(self, api_client, mock_rag):
        r = api_client.post("/api/query", json={"query": "q", "session_id": "existing"})

        assert r.status_code == 200
        assert r.json()["session_id"] == "existing"
        mock_rag.session_manager.create_session.assert_not_called()
        mock_rag.query.assert_called_once_with("q", "existing")

    def test_source_link_is_optional(self, api_client, mock_rag):
        mock_rag.query.return_value = ("answer", [{"label": "Course"}])

        r = api_client.post("/api/query", json={"query": "q"})

        assert r.status_code == 200
        assert r.json()["sources"] == [{"label": "Course", "link": None}]

    def test_missing_query_is_422(self, api_client, mock_rag):
        r = api_client.post("/api/query", json={"session_id": "s"})

        assert r.status_code == 422
        mock_rag.query.assert_not_called()

    def test_non_json_body_is_422(self, api_client):
        r = api_client.post(
            "/api/query",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422

    def test_rag_exception_becomes_500_with_detail(self, api_client, mock_rag):
        mock_rag.query.side_effect = IndexError("list index out of range")

        r = api_client.post("/api/query", json={"query": "q"})

        assert r.status_code == 500
        assert r.json()["detail"] == "list index out of range"

    def test_get_falls_through_to_static_mount(self, api_client):
        # The "/" static mount catches unmatched methods, so this is 404 rather than 405
        assert api_client.get("/api/query").status_code == 404


class TestCoursesEndpoint:
    def test_returns_course_stats(self, api_client, mock_rag):
        r = api_client.get("/api/courses")

        assert r.status_code == 200
        assert r.json() == {"total_courses": 1, "course_titles": [FIXTURE_COURSE_TITLE]}
        mock_rag.get_course_analytics.assert_called_once()

    def test_empty_catalog(self, api_client, mock_rag):
        mock_rag.get_course_analytics.return_value = {
            "total_courses": 0,
            "course_titles": [],
        }

        r = api_client.get("/api/courses")

        assert r.status_code == 200
        assert r.json() == {"total_courses": 0, "course_titles": []}

    def test_analytics_exception_becomes_500(self, api_client, mock_rag):
        mock_rag.get_course_analytics.side_effect = RuntimeError("chroma unavailable")

        r = api_client.get("/api/courses")

        assert r.status_code == 500
        assert r.json()["detail"] == "chroma unavailable"


class TestSessionEndpoint:
    def test_delete_session(self, api_client, mock_rag):
        r = api_client.delete("/api/session/abc")

        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        mock_rag.session_manager.delete_session.assert_called_once_with("abc")


class TestStaticRoot:
    def test_root_serves_index_html(self, api_client):
        r = api_client.get("/")

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert r.text == FIXTURE_INDEX_HTML

    def test_unknown_static_path_is_404(self, api_client):
        assert api_client.get("/missing.js").status_code == 404

    def test_api_routes_take_precedence_over_static_mount(self, api_client):
        r = api_client.get("/api/courses")
        assert r.headers["content-type"] == "application/json"
