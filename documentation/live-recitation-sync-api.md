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
{"type": "position", "event_id": "550e…", "segment_id": "e47b…", "index": 12, "round_number": 3, "server_time": "2026-09-17T09:30:00Z"}
```

The `position` frame is sent **only if the operator has already set one** — that is how a late joiner or a reconnecting phone lands on the live line.

## Client → server

| Frame | Who | Notes |
|-------|-----|-------|
| `{"type": "set", "segment_id": "e47b…", "index": 12, "round_number": 3}` | operator | `index` and `round_number` optional; `index` ≥ 0, `round_number` ≥ 1 |
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

- Show `round_number` during the 21-Taras loop: the same segments repeat, so the id alone is ambiguous there.
- The operator can jump anywhere, so never assume the position only moves forward.
- If the user scrolls away to read ahead, leave follow mode and show a resync button rather than yanking them back.
- An unknown `segment_id` (stale content) means hold the last good position and show a quiet "out of sync" hint — do not throw.

## Reconnecting

A deploy drops every socket, so reconnect with exponential backoff; the `position` frame on connect resyncs you. The server keeps the position for 12h of inactivity, so a restart mid-puja loses nothing. Freeze deploys during a live session anyway.

```js
const ws = new WebSocket(`${host}/api/v1/events/${eventId}/recitation/live?token=${token}`);
ws.onmessage = (e) => {
  const frame = JSON.parse(e.data);
  if (frame.type === "position") scrollToSegment(frame.segment_id, frame.round_number);
  if (frame.type === "session_ended") stopFollowing();
};
setInterval(() => ws.readyState === 1 && ws.send(JSON.stringify({ type: "ping" })), 30000);
```

If you run a Node bridge for the overlays, set `perMessageDeflate: false` — per-connection zlib buffers dwarf a 200-byte payload.
