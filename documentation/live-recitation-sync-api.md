# Live Recitation Sync — API

One WebSocket. The operator publishes a position; every phone and overlay in the room receives it. Design rationale in [rfc-live-recitation-sync.md](rfc-live-recitation-sync.md).

## Connect

```
wss://{host}/api/v1/events/{event_id}/recitation/live?token={auth_token}
```

`token` is the normal bearer token. Anyone joined to or following the event's group may connect; whoever may edit the event in the CMS (group owner / admin / author, or a super admin) also gets `is_operator: true` and may publish.

The server sends two frames on connect:

```json
{"type": "session_info", "event_id": "550e…", "is_operator": false}
{"type": "position", "event_id": "550e…", "text_id": "abc…", "segment_id": "e47b…", "index": 12, "round_number": 3, "server_time": "2026-09-17T09:30:00Z"}
```

The `position` frame is sent **only if the operator has already set one** — that is how a late joiner or a reconnecting phone lands on the live line.

## Client → server

| Frame | Who | Notes |
|-------|-----|-------|
| `{"type": "set", "text_id": "abc…", "segment_id": "e47b…", "index": 12, "round_number": 3}` | operator | `text_id` and `segment_id` required; `index` and `round_number` optional (`index` ≥ 0, `round_number` ≥ 1) |
| `{"type": "end"}` | operator | Ends the puja: clears the position and releases every socket |
| `{"type": "ping"}` | anyone | Replies `{"type": "pong"}`. Send every ~30s so sleeping phones are noticed |

`set` or `end` from a non-operator gets an `error` frame with code `FORBIDDEN`; the socket stays open. Malformed JSON and unknown `type` values are ignored silently. Publishes are throttled to 10/s per event, and anything beyond that is dropped.

## Server → client

| Frame | When |
|-------|------|
| `session_info` | Once, on connect |
| `position` | On connect (if a position exists) and on every operator `set` |
| `session_ended` | Operator sent `end`; the server closes the socket right after |
| `pong` | Reply to `ping` |
| `error` | `UNAUTHORIZED`, `FORBIDDEN`, `VALIDATION_ERROR`, `SERVER_ERROR`, or a 404/403 detail on connect |

## Rendering a `position`

`segment_id` is the key — **not** `index`. Resolve it to the segment in the user's chosen language through the segment's existing `mappings`, scroll that line into focus and highlight it. `index` is advisory, kept so the current OBS overlays keep working; do not key off it in new clients.

`text_id` says which liturgy that segment belongs to. An event's recitation collection holds several texts and the operator works through them in order, so **when `text_id` changes, load that text and carry on** — that is how the second and third recitations of a session reach the room. Everything stays on one socket; there is no reconnect between texts. A `position` whose `text_id` is not the text you have loaded is a cue to switch, not an error.

- Show `round_number` during the 21-Taras loop: the same segments repeat, so the id alone is ambiguous there.
- The operator can jump anywhere, so never assume the position only moves forward.
- If the user scrolls away to read ahead, leave follow mode and show a resync button rather than yanking them back.
- An unknown `segment_id` **within the text you have loaded** (stale content) means hold the last good position and show a quiet "out of sync" hint — do not throw.

## Test pages

Two HTML pages drive the same socket, and double as the reference implementation of everything above:

| Page | URL |
|------|-----|
| Emitter (operator) | `/api/v1/view/events/{event_id}/recitation/emitter` |
| Viewer (attendee) | `/api/v1/view/events/{event_id}/recitation` |

Paste a bearer token into either page. The **emitter** loads a liturgy by `text_id` (via `POST /recitations/{text_id}`), then click a line — or press space / ↓ / ↑ — to publish it; the round counter and an **End session** button sit in the toolbar. It shows `operator` or `viewer (cannot publish)` from the `session_info` frame, so a token without CMS edit rights on the event is obvious before the puja starts.

The **viewer** follows: it loads whatever `text_id` arrives, highlights and scrolls to the segment, shows the round number, drops out of follow mode when you scroll away (with a **Resync** button), and reconnects with backoff. Rows are matched by *any* of their per-language segment ids, so a viewer reading English follows an operator clicking through Tibetan.

## Reconnecting

A deploy drops every socket, so reconnect with exponential backoff; the `position` frame on connect resyncs you. The server keeps the position for 12h of inactivity, so a restart mid-puja loses nothing. Freeze deploys during a live session anyway.

```js
const ws = new WebSocket(`${host}/api/v1/events/${eventId}/recitation/live?token=${token}`);
ws.onmessage = (e) => {
  const frame = JSON.parse(e.data);
  if (frame.type === "position") {
    if (frame.text_id !== loadedTextId) loadText(frame.text_id);
    scrollToSegment(frame.segment_id, frame.round_number);
  }
  if (frame.type === "session_ended") stopFollowing();
};
setInterval(() => ws.readyState === 1 && ws.send(JSON.stringify({ type: "ping" })), 30000);
```

Two recitations running at the *same moment* in one event are not supported: there is one position per event, so two operators would overwrite each other. Sequential texts are the supported shape.

If you run a Node bridge for the overlays, set `perMessageDeflate: false` — per-connection zlib buffers dwarf a 200-byte payload.
