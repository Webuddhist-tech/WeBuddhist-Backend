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

`EventDTO` gains chat fields (and on `GET /events/{event_id}` a prayer tally):

```json
"chat_enabled": true,
"chat_room_id": "0f5c…",   // null until the room is created on first use
"prayer_request_count": 12 // live PRAYER messages in that room; 0 if no room yet
```

---

## 2. Prayer intentions catalog

```http
GET /intentions
```

Public, unauthenticated. Returns the five configured intention types (slug,
label, hex color, description, display order). The mobile app uses this for the
“Choose an intention” picker when creating a prayer request and to tint request
cards in the prayer-requests list.

Seed data lives in
`pecha_api/prayer_intentions/intentions_seed.json` (`peace`, `healing`,
`abundance`, `love`, `protection`).

---

## 3. Message types

`ChatMessageDTO.message_type` is `TEXT` (the default) or `PRAYER` (a prayer
request). Send it on any room's message endpoint:

```http
POST /chat/events/{event_id}/messages
{
  "body": "Please pray for my mother's health",
  "message_type": "PRAYER",
  "intention": "healing"
}
```

`intention` is **required** when `message_type` is `PRAYER` (a known slug from
`GET /intentions`). During catalog updates the API accepts both slug sets: former slugs
(`compassion`, `gratitude`, `dedication`) and current slugs (`love`, `abundance`,
`peace`) resolve against whichever catalog is in the database, including after a
migration downgrade, so prayer messages keep a nested `intention` on read. It must be **omitted** for `TEXT` messages (400
`INTENTION_NOT_ALLOWED_ON_TEXT` if sent). Prayer request bodies are limited to
**280** characters (400 `PRAYER_BODY_TOO_LONG`); ordinary `TEXT` messages stay
at 4000.

`PRAYER` is accepted in event rooms and group rooms, and rejected in DMs with
400 `PRAYER_NOT_ALLOWED_IN_DM` — a prayer request needs a congregation.

Prayer requests are ordinary messages otherwise: they can be replied to,
reacted to, reported and deleted exactly like any other.

On a `PRAYER` message the DTO carries prayer fields (including
`my_prayer_count`) and a nested `intention` object, **omitted entirely** on a
`TEXT` message:

```json
{
  "id": "…", "body": "Please pray for my mother's health",
  "message_type": "PRAYER",
  "intention": {
    "slug": "healing",
    "label": "Healing",
    "color": "#4A78C2",
    "description": "Recovery from illness, emotional healing, calm after conflict",
    "display_order": 1
  },
  "prayer_count": 12,
  "prayed_by_me": true,
  "my_prayer_count": 30,
  "recent_prayers": [ { "user_id": "…", "name": "Tenzin", "avatar_url": "…" } ]
}
```

`prayer_count` counts **people**; `my_prayer_count` is how many times the
viewer has prayed for it. `recent_prayers` holds at most 3 people, for an
avatar stack; the full roster comes from the who-prayed
endpoint.

**Filter a room to its prayer requests:**

```http
GET /chat/rooms/{room_id}/messages?message_type=PRAYER
```

---

## 4. Praying

### Pray for one or several selected requests

```http
POST /chat/rooms/{room_id}/prayers
{ "message_ids": ["a1…", "b2…", "c3…"], "count": 1 }   // 1-10 ids, count 1-10 (default 1)
```

```json
{ "prayers": [
    { "message_id": "a1…", "prayer_count": 12, "prayed_by_me": true, "my_prayer_count": 1,  "created": true },
    { "message_id": "b2…", "prayer_count": 4,  "prayed_by_me": true, "my_prayer_count": 21, "created": false }
] }
```

This is the multi-select action: send the ids the user ticked. `count` prayers
are added to **each** id. Praying again adds to `my_prayer_count`;
`created: false` means the caller was already praying for that request, so
`prayer_count` (people) did not move. Ids that are no longer live prayer
requests in this room are skipped and simply absent from the response, so a
request deleted between rendering and confirming does not cost the user the
rest of their selection. If none of the ids is prayable, the call 404s with
`NOT_A_PRAYER_REQUEST`.

**Rate limit: 10 prayers per second per user**, counted as
`count × len(message_ids)`. Over it, the call returns `429` with
`Retry-After: 1` and nothing is written. Ids that are skipped (no longer live
prayer requests) and calls that fail with `403`/`404` are not charged. Clients
should batch taps (about
300 ms) into one call with `count`; a "+100" action is 10 calls of `count: 10`,
one per second.

### Take prayers back

```http
DELETE /chat/messages/{message_id}/prayers/me
```

Removes all of the caller's prayers for the request. Returns the same shape
with `prayed_by_me: false` and `my_prayer_count: 0`. Idempotent, not
rate-limited, and sends no push.

### Who is praying ("Praying together")

```http
GET /chat/messages/{message_id}/prayers?skip=0&limit=20
```

```json
{ "message_id": "a1…", "total": 12, "skip": 0, "limit": 20,
  "prayers": [
    { "user_id": "…", "email": "…", "name": "Tenzin", "avatar_url": "…",
      "prayer_count": 10,
      "created_at": "2026-09-11T10:04:00+00:00",
      "last_prayed_at": "2026-09-11T10:25:00+00:00" }
] }
```

Any active member of the room may read it. `prayer_count` (how many times
that person prayed) is **only filled in for the member who posted the
request**; for everyone else it is `null`. Ordered by `last_prayed_at`,
most recent first. `created_at` is the person's first prayer. `total` counts
people.

---

## 5. Live events

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
{
  "type": "message",
  "body": "Please pray for…",
  "message_type": "PRAYER",
  "intention": "love"
}
```

---

## 6. Notifications

The requester is notified when someone prays for their request:
`notification_type: "PRAYER_RECEIVED"`, with `message_id`, `room_id`,
`prayer_id`, `prayer_count` and (for an event room) `event_id` in the data
payload, so the tap can deep-link to the request itself.

- Never fires for praying for your own request, and your own prayers are not
  counted in it.
- **One push per request per interval:**
  `PRAYER_REQUEST_NOTIFICATION_INTERVAL_SECONDS` (default 1140). Each push
  stands for every prayer since the previous one for that request.

  The title is always `Someone just prayed for you`: the push never names who
  prayed or how many times. The body is the room's name (the event's name, for
  an event room), and the push carries an image: the event's image for an event
  room, falling back to the room's image, and the room's image otherwise. The
  counts are still in the data payload (`prayer_count`) for the app to use.

- Prayers inside the interval are carried by the next push. The interval does
  not tick by itself: if nobody prays afterwards, no push goes out for them.

Posting a prayer request is the other notification, and a separate rule. It is
an ordinary `CHAT_MESSAGE` with `message_type: "PRAYER"`, so it goes to every
member of the room.

- **One push per room per interval:**
  `PRAYER_REQUEST_NOTIFICATION_INTERVAL_SECONDS` (default 1140, nineteen
  minutes). The first request in a quiet room sends immediately; requests
  posted inside the interval are held, and the next push that does go out ends
  with "+3 other prayer requests". `0` sends a push for every request.
- A held request is in the room the instant it is posted, with the usual
  realtime update — only the push is gated. Its row is marked `SUPPRESSED`, so
  reconcile leaves it alone.
- The interval is per room, not per member: a busy sangha is what makes phones
  buzz, and a member of three sanghas should not have one of them silence the
  other two.
- Ordinary `TEXT` chat is not gated.
- Users can mute it globally or per group, like `CHAT_MESSAGE`
  (`PRAYER_RECEIVED` is a group-scoped notification type) — see
  [notification-preferences-api.md](./notification-preferences-api.md).

---

## 7. Errors

| Status | Detail | Meaning |
|--------|--------|---------|
| 400 | `PRAYER_NOT_ALLOWED_IN_DM` | Prayer requests need a group or event room |
| 400 | `PRAYER_INTENTION_REQUIRED` | `PRAYER` message without `intention` |
| 400 | `INVALID_PRAYER_INTENTION` | Unknown intention slug |
| 400 | `PRAYER_BODY_TOO_LONG` | Prayer request body exceeds 280 characters |
| 400 | `INTENTION_NOT_ALLOWED_ON_TEXT` | `intention` sent with a `TEXT` message |
| 400 | `NOT_A_PRAYER_REQUEST` | The message exists but is a `TEXT` message |
| 403 | — | Not an active member of the room |
| 429 | — | More than 10 prayers in a second; retry after `Retry-After` |
| 404 | `NOT_A_PRAYER_REQUEST` | Nothing in the batch was a live prayer request |
| 404 | — | Room, event or message gone; chat switched off; group unpublished |
