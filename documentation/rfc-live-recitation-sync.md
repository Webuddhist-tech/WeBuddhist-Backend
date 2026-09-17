# RFC: Live Recitation Sync (segment-keyed auto-scroll)

| Field | Value |
|-------|-------|
| **Status** | Implemented (backend); app + overlay pending |
| **Date** | 2026-09-14 |
| **Scope** | WeBuddhist-Backend, mobile client, OBS overlay repo |
| **Related** | `live-recitation-sync-api.md` (client guide), `segments.md`, `rfc-event-rooms-and-prayers.md` |

---

## 1. Summary

One operator advances a puja on a controller. The position is broadcast to every subscriber of that event: the OBS overlays (bo / en / zh) burn it into the livestream, and the app scrolls the liturgy on each attendee's phone, lyrics-style. The payload is **one segment id plus a round counter** — the service never sends text.

## 2. Core decision: `segment_id` is the wire key

The prototype broadcasts a bare array `index` into a flattened `content.json`. That breaks the moment the liturgy is edited, and it gives the app no way to know which line to highlight in the reader's own language.

Per `segments.md`, every segment already has a stable UUID and a `mappings` list linking it to its translations. So we broadcast `segment_id`; the app resolves it to the segment in the user's language and scrolls there. Three languages, one message, no new id scheme.

`index` stays in the payload as an **advisory** ordinal so existing OBS overlays keep working during migration. New clients key off `segment_id`.

**Naming:** the prototype's loop counter `pass` is a Python keyword and cannot be a field name. Use `round_number` (not `round` — a builtin), renamed here before clients bake it in.

## 3. Architecture

Mirrors the chat stack exactly: operator → FastAPI WS endpoint → Redis pub/sub → every instance → its local sockets. Render assigns sockets to random instances with no sticky sessions, so in-process state alone would desync half the room past one instance. `ChatBroadcaster` already solves this; we copy it.

## 4. Endpoint and protocol

```
wss://{host}/api/v1/events/{event_id}/recitation/live?token={auth_token}
```

Operator → server:

```json
{ "type": "set", "segment_id": "e47b3b6a-…", "index": 12, "round_number": 3 }
```

Server → all subscribers, on every change **and once on connect** so late joiners land on the live line:

```json
{ "type": "position", "event_id": "550e8400-…", "segment_id": "e47b3b6a-…",
  "index": 12, "round_number": 3, "server_time": "2026-09-14T09:30:00Z" }
```

Also: `ping`/`pong` (30s heartbeat — phones sleep), `error` (`VALIDATION_ERROR`, `FORBIDDEN`, `SERVER_ERROR`, as in the comments WS), and `session_ended` when the operator closes the puja. Malformed JSON and unknown types are ignored; a `set` from a non-operator gets a `FORBIDDEN` error frame but keeps its socket.

## 5. `RecitationBroadcaster`

New `pecha_api/events/recitation_websocket.py`, structured like `ChatBroadcaster`: local map `{event_id: {user_id: ws}}`, channel `recitation:event:{event_id}:position`, `broadcast_position(...)` publishes and each instance relays locally.

**The one addition over chat: a position snapshot.** Chat is a stream; this is a current value. Every `set` also writes a Redis hash `recitation:event:{event_id}:state` (`segment_id`, `index`, `round_number`, `updated_at`; 12h TTL, refreshed on write), and the connect handler sends its `position` frame from that key. One extra `HSET` per operator click is what makes reconnects and redeploys survivable.

## 6. App behavior on `position`

- Scroll `segment_id` into focus, smooth-animated; highlight it, dim the rest.
- Show `round_number` during the 21-Taras loop — the segments repeat there, so the id alone is ambiguous.
- Operator jumps arrive as an ordinary `position`; never assume position advances monotonically.
- **Follow toggle:** if the user scrolls away to read ahead, leave follow mode and show a resync button. Auto-scrolling someone deliberately reading ahead is the worst failure mode here.
- Unknown `segment_id` (stale content) holds the last good position and shows a quiet "out of sync" hint — never throws.
- Reconnect with exponential backoff; the connect-time `position` frame resyncs.

## 7. Permissions and hosting

Subscribe: caller is joined to or following the event's group (the same rule the event's chat room uses). Publish `set`: whoever may edit the event in the CMS — group owner, admin or author, plus super admins — so there is no second permission model to keep in step. Publishes throttled ~10/s per event, excess dropped. An unknown or unpublished `event_id` closes the socket.

Render imposes no connection limit; a few hundred phones at ~200 bytes a few times a minute sits far below Standard (`1c-2g`). Two operational facts matter more: **a deploy drops every socket**, so freeze deploys during a live puja and treat client reconnect as mandatory; and set `perMessageDeflate: false` on any Node overlay bridge, since per-connection zlib buffers dwarf our payload.

## 8. Non-goals (v1)

Audio/word-level karaoke timing; multiple or handed-off operators; persisting or replaying a past puja; per-user position; serving liturgy text over the socket (the app loads it through the existing segment APIs).

## 9. Acceptance criteria

- **Backend** — the endpoint accepts subscribers and sends `position` on connect; non-operator `set` is ignored while operator `set` fans out across instances; position survives an instance restart and expires after 12h; `ping`/`pong` holds sockets through a multi-hour puja.
- **App** — auto-scrolls and highlights by `segment_id` in the user's language; shows `round_number` during the Taras loop; follow toggle, resync button, and reconnect-without-reload all work.
- **Overlay** — existing OBS overlays keep rendering from `index`, unchanged.

## 10. Open questions

(The operator question is settled: CMS edit rights on the event.) Does the controller stay a standalone page or move into Studio? One puja at a time per group, or concurrent (the design supports concurrent by `event_id`; the question is the UI)? Is venue wifi assumed flaky — the design tolerates it — or guaranteed?
