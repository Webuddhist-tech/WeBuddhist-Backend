# Event Chat Rooms & Prayer Requests — API

Client-facing reference for the feature described in
[rfc-event-rooms-and-prayers.md](./rfc-event-rooms-and-prayers.md).

Everything here is additive: no existing endpoint changed shape, and a client
that knows nothing about prayer requests keeps working unchanged.

---

## 1. Event chat rooms

An event now has its own chat room, a third room kind alongside a group's room
and a DM. `ChatRoomDTO.kind` is `GROUP`, `EVENT` or `PRIVATE`, and an event
room carries `event_id` instead of `group_id`.

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/chat/events/{event_id}/room` | Resolve the room, creating it and joining the caller on first use |
| `POST` | `/chat/events/{event_id}/messages` | Send a message (201 → `ChatMessageDTO`) |
| `WS` | `/chat/live?event_id=...&token=...` | Live stream; exactly one of `group_id`, `event_id`, `receiver_id` |

**Who can take part:** anyone who joins or follows the event's group. RSVPing to
the event is *not* required — but RSVPing does add you to the room (and
un-RSVPing removes you), so the room shows up in `/chat/rooms` before you ever
type.

**When the room stops serving:** the event is deleted, the owning group is
unpublished, or an admin switches `chat_enabled` off in the CMS. Requests then
404 and live sockets receive `{"type": "room_closed", "reason": "EVENT_CHAT_DISABLED"}`.

**Recurring events** compute their occurrences rather than storing them, so one
room per event serves every occurrence.

`EventDTO` gains two fields:

```json
"chat_enabled": true,
"chat_room_id": "0f5c…"   // null until the room is created on first use
```

---

## 2. Message types

`ChatMessageDTO.message_type` is `TEXT` (the default) or `PRAYER` (a prayer
request). Send it on any room's message endpoint:

```http
POST /chat/events/{event_id}/messages
{ "body": "Please pray for my mother's health", "message_type": "PRAYER" }
```

`PRAYER` is accepted in event rooms and group rooms, and rejected in DMs with
400 `PRAYER_NOT_ALLOWED_IN_DM` — a prayer request needs a congregation.

Prayer requests are ordinary messages otherwise: they can be replied to,
reacted to, reported and deleted exactly like any other.

On a `PRAYER` message the DTO carries three extra fields, **omitted entirely**
on a `TEXT` message:

```json
{
  "id": "…", "body": "Please pray for my mother's health",
  "message_type": "PRAYER",
  "prayer_count": 12,
  "prayed_by_me": false,
  "recent_prayers": [ { "user_id": "…", "name": "Tenzin", "avatar_url": "…" } ]
}
```

`recent_prayers` holds at most 3 people, for an avatar stack; the full roster
comes from the who-prayed endpoint.

**Filter a room to its prayer requests:**

```http
GET /chat/rooms/{room_id}/messages?message_type=PRAYER
```

---

## 3. Praying

### Pray for one or several selected requests

```http
POST /chat/rooms/{room_id}/prayers
{ "message_ids": ["a1…", "b2…", "c3…"] }     // 1-50 ids
```

```json
{ "prayers": [
    { "message_id": "a1…", "prayer_count": 12, "prayed_by_me": true, "created": true },
    { "message_id": "b2…", "prayer_count": 4,  "prayed_by_me": true, "created": false }
] }
```

This is the multi-select action: send the ids the user ticked. It is
**idempotent** — `created: false` means the caller had already prayed for that
request, and nothing changed. Ids that are no longer live prayer requests in
this room are skipped and simply absent from the response, so a request deleted
between rendering and confirming does not cost the user the rest of their
selection. If none of the ids is prayable, the call 404s with
`NOT_A_PRAYER_REQUEST`.

### Take a prayer back

```http
DELETE /chat/messages/{message_id}/prayers/me
```

Returns the same shape with `prayed_by_me: false`. Idempotent.

### Who prayed

```http
GET /chat/messages/{message_id}/prayers?skip=0&limit=20
```

```json
{ "message_id": "a1…", "total": 12, "skip": 0, "limit": 20,
  "prayers": [
    { "user_id": "…", "email": "…", "name": "Tenzin", "avatar_url": "…",
      "created_at": "2026-09-11T10:04:00+00:00" }
] }
```

Newest first. Active room members only.

---

## 4. Live events

The WebSocket stream gains one server event, published to the room when anyone
prays or un-prays:

```json
{ "type": "prayers_updated",
  "prayers": [
    { "message_id": "a1…", "prayer_count": 12, "user_ids": ["u1…", "u2…"] }
  ] }
```

A batch pray sends **one** payload covering every selected message. Like
`reactions_updated`, it carries no viewer-specific state: derive `prayed_by_me`
by looking for your own id in `user_ids`.

To post a prayer request over the socket, add `message_type`:

```json
{ "type": "message", "body": "Please pray for…", "message_type": "PRAYER" }
```

---

## 5. Notifications

The requester is notified when someone prays for their request:
`notification_type: "PRAYER_RECEIVED"`, with `message_id`, `room_id`,
`prayer_id`, `prayer_count` and (for an event room) `event_id` in the data
payload, so the tap can deep-link to the request itself.

- Never fires for praying for your own request.
- **Coalesced:** prayers for the same request inside
  `PRAYER_NOTIFICATION_COALESCE_SECONDS` (default 900) raise one notification,
  whose copy reads from the live count — "12 people are praying for your
  request" — rather than one push per prayer.
- Users can mute it globally or per group, like `CHAT_MESSAGE`
  (`PRAYER_RECEIVED` is a group-scoped notification type).

---

## 6. Errors

| Status | Detail | Meaning |
|--------|--------|---------|
| 400 | `PRAYER_NOT_ALLOWED_IN_DM` | Prayer requests need a group or event room |
| 400 | `NOT_A_PRAYER_REQUEST` | The message exists but is a `TEXT` message |
| 403 | — | Not an active member of the room |
| 404 | `NOT_A_PRAYER_REQUEST` | Nothing in the batch was a live prayer request |
| 404 | — | Room, event or message gone; chat switched off; group unpublished |
