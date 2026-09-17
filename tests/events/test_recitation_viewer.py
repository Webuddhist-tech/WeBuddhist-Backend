from uuid import uuid4

from fastapi.testclient import TestClient

from pecha_api.app import api

client = TestClient(api)


class TestRecitationViewerPages:

    def test_viewer_page_renders_with_the_event_id(self):
        event_id = uuid4()

        response = client.get(f"/view/events/{event_id}/recitation")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert f'const EVENT_ID = "{event_id}"' in response.text
        assert "__EVENT_ID__" not in response.text

    def test_emitter_page_renders_with_the_event_id(self):
        event_id = uuid4()

        response = client.get(f"/view/events/{event_id}/recitation/emitter")

        assert response.status_code == 200
        assert f'const EVENT_ID = "{event_id}"' in response.text
        assert "__EVENT_ID__" not in response.text

    def test_pages_share_one_stylesheet(self):
        """The CSS placeholder is substituted at import time; a miss would ship
        the literal token to the browser."""
        event_id = uuid4()

        viewer = client.get(f"/view/events/{event_id}/recitation").text
        emitter = client.get(f"/view/events/{event_id}/recitation/emitter").text

        assert "__SHARED_CSS__" not in viewer
        assert "__SHARED_CSS__" not in emitter
        assert ".status-dot" in viewer and ".status-dot" in emitter

    def test_rejects_a_non_uuid_event_id(self):
        assert client.get("/view/events/not-a-uuid/recitation").status_code == 422

    def test_emitter_publishes_and_viewer_only_follows(self):
        event_id = uuid4()

        viewer = client.get(f"/view/events/{event_id}/recitation").text
        emitter = client.get(f"/view/events/{event_id}/recitation/emitter").text

        # The emitter is the only page that sends a `set`, and it always names
        # the text - a position without text_id is rejected by the socket.
        assert 'type: "set"' in emitter
        assert "text_id: $(\"textId\").value.trim()" in emitter
        assert 'type: "set"' not in viewer

        # The viewer is the page that follows a text change across liturgies.
        assert "frame.text_id !== loadedTextId" in viewer

    def test_both_pages_heartbeat_and_reconnect(self):
        event_id = uuid4()

        for path in (f"/view/events/{event_id}/recitation",
                     f"/view/events/{event_id}/recitation/emitter"):
            page = client.get(path).text
            assert '{ type: "ping" }' in page
            assert "Math.pow(2, retry - 1)" in page

    def test_viewer_pages_are_hidden_from_the_schema(self):
        paths = api.openapi()["paths"]

        assert "/view/events/{event_id}/recitation" not in paths
        assert "/view/events/{event_id}/recitation/emitter" not in paths
