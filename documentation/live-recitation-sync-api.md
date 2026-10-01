# Live Recitation Sync — API

One WebSocket. The operator publishes a position; every phone and overlay in the room receives it. Design rationale in [rfc-live-recitation-sync.md](rfc-live-recitation-sync.md).

## Connect

```
wss://{host}/api/v1/events/{event_id}/recitation/live?token={auth_token}
```

`token` is the normal bearer token. Anyone joined to or following the event's group may connect. Whoever may edit the event in the CMS (group owner / admin / author, or a super admin) gets `is_operator: true` and may publish — and connects on that basis alone, without having joined or followed the group in the app, since the person driving the puja usually never tapped "join".

The server sends two frames on connect:

```json
{"type": "session_info", "event_id": "550e…", "is_operator": false, "count": 12}
{"type": "position", "event_id": "550e…", "text_id": "abc…", "segment_id": "e47b…", "index": 12, "round_number": 3, "server_time": "2026-09-17T09:30:00Z", "revision": 57}
```

`count` is how many people are joined to this event's socket, including the socket that just connected. It is shared across API instances. Whenever someone joins or leaves, every socket also receives:

```json
{"type": "presence", "event_id": "550e…", "count": 13}
```

The `position` frame is sent **only if the operator has already set one** — that is how a late joiner or a reconnecting phone lands on the live line.

## Client → server

| Frame | Who | Notes |
|-------|-----|-------|
| `{"type": "set", "text_id": "abc…", "segment_id": "e47b…", "index": 12, "round_number": 3}` | operator | `text_id` and `segment_id` required; `index` and `round_number` optional (`index` ≥ 0, `round_number` ≥ 1) |
| `{"type": "end"}` | operator | Ends the puja: clears the position and releases every socket |
| `{"type": "ping"}` | anyone | Replies `{"type": "pong"}`. Send every ~30s so sleeping phones are noticed |

`set` or `end` from a non-operator gets an `error` frame with code `FORBIDDEN`; the socket stays open. Malformed JSON and unknown `type` values are ignored silently. Publishes are throttled to 10/s per event, and anything beyond that is dropped.

## Emitting without a socket (HTTP)

A controller that cannot hold a WebSocket open — a script, a foot-pedal, an OBS action, a cron — publishes over HTTP instead. Same validation, same per-event throttle, same fan-out: a phone cannot tell which route a position arrived by.

These callers are machines with no user session, so they authenticate with the `X-Recitation-Token` shared secret (`RECITATION_EMIT_SECRET_TOKEN`) rather than a bearer token — the same way the worker reaches the internal dispatch endpoints with `X-Dispatch-Token`. **The secret is the whole authorization**: there is no user or Author behind the request, so anything holding it can drive any event's recitation. Keep it in the controller's configuration, not in a browser.

```bash
# dev, matching the convention NOTIFICATION_DISPATCH_SECRET_TOKEN follows
RECITATION_EMIT_SECRET_TOKEN=SecretTokenForNotificationDispatch
```

The code default is empty, which switches both endpoints off (`503`) — an unset secret must never mean "any token works". Every deployment past dev sets its own value.

```http
POST /api/v1/events/{event_id}/recitation/position
X-Recitation-Token: <shared secret>

{ "text_id": "abc…", "segment_id": "e47b…", "index": 12, "round_number": 3 }
```

```json
202 Accepted
{ "event_id": "550e…", "text_id": "abc…", "segment_id": "e47b…", "index": 12,
  "round_number": 3, "server_time": "2026-09-17T09:30:00Z", "revision": 58 }
```

`POST /api/v1/events/{event_id}/recitation/end` (204) is the `end` frame's twin — without it, a session started over HTTP would hold every client in follow mode until the snapshot's 12h TTL ran out. It answers `503` if the snapshot could not be cleared or the notice could not be published; ending is idempotent, so retry.

| Status | Meaning |
|--------|---------|
| `202` | Published; the body is the position as the room received it |
| `401` | Wrong `X-Recitation-Token` |
| `404` | No such event, or its group is unpublished |
| `422` | Header missing, or `text_id`/`segment_id` missing or blank |
| `429` | Past the 10/s per-event ceiling — the socket drops these silently, HTTP tells you |
| `503` | `RECITATION_EMIT_SECRET_TOKEN` unset (the endpoints are off), or Redis unavailable; nothing was published. On `/end` it also means the session may still be live for the room — retry |

The throttle budget is shared with the socket, so alternating routes does not double it.

## Autoplay: correcting it, and keeping phones level with the stage

`POST .../recitation/autoplay` hands the backend a plan (each step a line in every edition, with how long the room holds it), and the backend moves the room on by itself. Phones cannot be changed for this, so everything below is the operator's side; a phone still just applies each `position` the moment it lands.

**Correcting a running plan.** A hand move is a step of the plan already running, not a new plan, so it reaches the room in one hop. Each command takes over the plan wherever it runs and is answered with `autoplay_ack` (socket) or the new state (HTTP). Commands are operator-only; `seek` and `hold` share the move throttle.

| Socket frame | HTTP twin (`X-Recitation-Token`) | Does |
|--------------|----------------------------------|------|
| `{"type": "autoplay_seek", "command_id": "c1", "plan_id": "…", "step": 5, "expected_step": 4}` | `POST .../recitation/autoplay/seek` | Sends step 5 now and carries on from there. If the plan already reached `step` by itself, does nothing (a press racing the plan is not applied twice). |
| `{"type": "autoplay_hold", "plan_id": "…"}` | `POST .../recitation/autoplay/hold` | Keeps the room on its line past its time. |
| `{"type": "autoplay_resume", "plan_id": "…"}` | `POST .../recitation/autoplay/resume` | Goes on; the line keeps what was left of its time. |
| `{"type": "autoplay_settings", "lead_ms": 300, "tempo": 1.0}` | `POST .../recitation/autoplay/settings` | Sets the phone lead and/or the pace (both optional). |

`plan_id` must still be the plan running, or the command is refused (`NOT_RUNNING` / `409`).

**Phone lead (`lead_ms`, default 300, max 2000).** The next line is published to the room `lead_ms` before its time, so after network and render delay it lands on phones as the stage moves on. The operator's `autoplay` state still changes at the line's real time. A lead is never more than half the line. Holding (or pausing) after the next line already went early puts the room back on the held line.

**Room pace (`tempo`, 0.6–1.6).** Every recorded time is multiplied by it. A `seek` to `expected_step + 1` is the operator ending that line; the time it actually took moves the pace 35% of the way toward what that line says, so autoplay settles on today's pace within a few presses. Setting `tempo: 1.0` resets it. Lead and pace are per event and outlive any one plan.

The `autoplay` state frame carries `held`, `held_at_ms`, `tempo`, `lead_ms`, and `step_duration_ms` with the pace applied.

## Server → client

| Frame | When |
|-------|------|
| `session_info` | Once, on connect. `count` is people joined, including this socket |
| `presence` | Whenever someone joins or leaves. `count` is the new total |
| `position` | On connect (if a position exists) and on every operator `set` |
| `session_ended` | Operator sent `end`; the server closes the socket right after |
| `autoplay` | Operator only: on connect, then whenever autoplay moves on, holds, stops or changes settings |
| `move_ack` / `autoplay_ack` | Operator only: the answer to a `move` / `autoplay_*` frame |
| `pong` | Reply to `ping` |
| `error` | `UNAUTHORIZED`, `FORBIDDEN`, `VALIDATION_ERROR`, `SERVER_ERROR`, or a 404/403 detail on connect |

## Rendering a `position`

`segment_id` is the key — **not** `index`. Resolve it to the segment in the user's chosen language through the segment's existing `mappings`, scroll that line into focus and highlight it. `index` is advisory, kept so the current OBS overlays keep working; do not key off it in new clients.

`revision` is a counter from Redis that increases with every position in the event, and it — not `server_time` — is what orders frames: the timestamp is stamped by whichever instance served the operator, and two instances' clocks need not agree. The server already drops frames older than what it sent you; a client that buffers can use it to do the same.

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
