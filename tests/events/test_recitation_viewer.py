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
        assert "frame.text_id !== displayedTextId" in viewer

    def test_both_pages_heartbeat_and_reconnect(self):
        event_id = uuid4()

        for path in (f"/view/events/{event_id}/recitation",
                     f"/view/events/{event_id}/recitation/emitter"):
            page = client.get(path).text
            assert '{ type: "ping" }' in page
            assert "Math.pow(2, retry - 1)" in page

    def test_viewer_guards_against_overlapping_text_loads(self):
        """Two position frames in flight each fetch a text; without a guard the
        slower one wins and puts the earlier liturgy back on screen."""
        page = client.get(f"/view/events/{uuid4()}/recitation").text

        assert "let displayedTextId = null, desiredTextId = null;" in page
        # A superseded load must not render, and a superseded frame must not
        # paint over the text the room actually moved to.
        assert page.count("if (desiredTextId !== textId) return;") == 2
        assert "if (latestPosition !== frame) return;" in page
        assert "if (displayedTextId !== frame.text_id) return;" in page

    def test_every_frame_states_the_desired_text(self):
        """Operator goes T1 -> T2 -> back to T1 while T2 is still downloading.
        Only recording intent when a load starts would let T2 paint on arrival,
        leaving the screen on a text the room already left."""
        page = client.get(f"/view/events/{uuid4()}/recitation").text

        assert "if (frame.text_id) desiredTextId = frame.text_id;" in page

    def test_viewer_never_blanks_the_text_it_is_still_showing(self):
        """Clearing the list before the new text arrived left the page stuck on
        a loading message whenever that load was superseded - and a position for
        the text still notionally loaded had no row to highlight."""
        page = client.get(f"/view/events/{uuid4()}/recitation").text

        assert "Loading text…</div>" not in page
        assert 'Could not load this text.</div>' not in page
        # The list is only replaced once the new text is in hand.
        assert "renderSegments(data.segments || []);" in page
        assert "displayedTextId = textId;" in page

    def test_viewer_fetches_each_text_once_while_in_flight(self):
        page = client.get(f"/view/events/{uuid4()}/recitation").text

        assert "if (inFlightTextId === textId && inFlightRequest) return inFlightRequest;" in page

    def test_reconnecting_cancels_a_queued_reconnect(self):
        """Connect while a backoff timer is pending: the timer would otherwise
        fire later, replace `ws`, and orphan the socket still open server-side."""
        event_id = uuid4()

        for path in (f"/view/events/{event_id}/recitation",
                     f"/view/events/{event_id}/recitation/emitter"):
            page = client.get(path).text
            assert "reconnectTimer = setTimeout(connect," in page
            assert "clearTimeout(reconnectTimer); reconnectTimer = null;" in page
            assert "ws.onclose = null;" in page
            # The old click handler closed the socket itself, which fired
            # onclose and queued the very reconnect this guards against.
            assert "if (ws) ws.close(); connect();" not in page

    def test_viewer_pages_are_hidden_from_the_schema(self):
        paths = api.openapi()["paths"]

        assert "/view/events/{event_id}/recitation" not in paths
        assert "/view/events/{event_id}/recitation/emitter" not in paths
