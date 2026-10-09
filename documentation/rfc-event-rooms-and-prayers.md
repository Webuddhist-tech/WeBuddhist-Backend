# RFC: Event Chat Rooms & Prayer Requests

| Field | Value |
|-------|-------|
| **Status** | Proposed |
| **Date** | 2026-09-11 |
| **Scope** | WeBuddhist-Backend, webuddhist-worker, WeBuddhist-Studio, mobile client |
| **Related** | Chat (`pecha_api/chat`), Events (`pecha_api/events`), `rfc-notification-preferences.md` |

---

## 1. Summary

Give every **event** its own chat room, alongside the existing group rooms and DMs, and add a second
**message type** to chat: `PRAYER` (a prayer request) next to the default `TEXT`.

Any member of an event room can post a prayer request. Other members can **pray for** one or several
selected requests in a single action (Hallow-style multi-select). Each request carries a **prayer count**
and a **list of who prayed**, and the requester is notified.

---

## 2. Motivation

| Today | Gap |
|-------|-----|
| `chat_rooms` supports exactly two shapes: one per group, or a DM pair | An event (a puja, a retreat, a Losar ceremony) has no space of its own |
| Event participation is only an RSVP row (`group_event_participants`) | Participants cannot talk to each other |
| Every `chat_messages` row is plain text | No way to mark a message as a request for prayer, or to respond to it with anything but an emoji |
| `chat_message_reactions` counts emoji | Cannot answer "how many people prayed for this request, and who?" — an emoji reaction is not an intention record |

---

## 3. Goals

- One chat room per event, auto-resolved like the existing group room.
- A `message_type` discriminator on chat messages: `TEXT` (default) | `PRAYER`.
- Pray for one message, or for N selected messages in one request.
- Per-message prayer count + paginated "who prayed" list + `prayed_by_me` for the caller.
- Live prayer-count updates over the existing WebSocket/Redis fan-out.
- Reuse existing moderation, reporting, reactions, replies, presence and notification-preference plumbing unchanged.

## 4. Non-goals (v1)

- Prayer requests in DMs (rejected).
- Prayer streaks, leaderboards, or "prayers offered" profile stats.
- Anonymous prayer requests or anonymous praying.
- A separate room per **occurrence** of a recurring event (see §5.1).
- A scheduled / answered / closed lifecycle on a request.
- Media attachments on prayer requests.

---

## 5. Data model

### 5.1 `chat_rooms` — third room shape

| Column | Type | Notes |
|--------|------|-------|
| `event_id` | UUID FK → `events.id` ON DELETE CASCADE, NULL | New. Non-null exactly for event rooms |

`ck_chat_rooms_kind_shape` is **dropped and recreated** with three mutually exclusive shapes:

```text
GROUP    group_id NOT NULL, event_id NULL, sender_id NULL, receiver_id NULL
EVENT    event_id NOT NULL, group_id NULL, sender_id NULL, receiver_id NULL
PRIVATE  sender_id NOT NULL, receiver_id NOT NULL, sender_id <> receiver_id, group_id NULL, event_id NULL
```

New partial unique index `uq_chat_rooms_event_id` on `event_id` WHERE `event_id IS NOT NULL AND deleted_at IS NULL`
— mirrors `uq_chat_rooms_group_id`.

**Decision — recurring events:** `events` stores the template and occurrences are *computed*
(`recurrence_service.resolve_next_occurrence`), so there is exactly one room per `events.id`, shared by every
occurrence. A per-occurrence room would require materialised occurrence rows; deferred.

### 5.2 `chat_messages` — message type

| Column | Type | Notes |
|--------|------|-------|
| `message_type` | ENUM `chat_message_type` NOT NULL | New. `TEXT` \| `PRAYER`, `server_default='TEXT'` |

New partial index `idx_chat_messages_room_prayers` on `(room_id, created_at DESC)`
WHERE `message_type = 'PRAYER' AND deleted_at IS NULL` — backs the "Prayer requests" tab.

Prayer requests are ordinary messages: they reply, get reacted to, get reported, get soft-deleted, and count
as unread through the code that already exists.

### 5.3 `chat_message_prayers` (new)

Deliberately **not** a reserved emoji in `chat_message_reactions`: a prayer is an intention record, must be
countable and listable independently of emoji, and must survive any future change to reaction semantics.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | `uuid4` |
| `message_id` | UUID FK → `chat_messages.id` ON DELETE CASCADE | The prayer request |
| `user_id` | UUID FK → `users.id` ON DELETE CASCADE | Who prayed |
| `created_at` | TIMESTAMPTZ NOT NULL | |
| `notification_sqs_message_id` | VARCHAR(128) NULL | Same dispatch/reconcile pattern as `chat_messages` |
| `notification_dispatched_at` | TIMESTAMPTZ NULL | |

**Constraints / indexes**

- `uq_chat_message_prayers_message_user` UNIQUE `(message_id, user_id)` — one prayer per person per request; makes the batch endpoint idempotent.
- `idx_chat_message_prayers_message_id` on `message_id` — count and roster.
- `idx_chat_message_prayers_user_created` on `(user_id, created_at DESC)` — "requests I have prayed for".
- `idx_chat_message_prayers_undispatched` on `created_at` WHERE `notification_sqs_message_id IS NULL`.

**Counting:** the table is the source of truth. Counts are aggregated per page of messages exactly like
`get_reactions_map` (one grouped query per page), so no denormalised counter and no drift. A materialised
`prayer_count` is only needed if we later sort rooms by most-prayed — out of scope.

### 5.4 `events`

| Column | Type | Notes |
|--------|------|-------|
| `chat_enabled` | BOOLEAN NOT NULL | New, `server_default='true'`. CMS kill-switch per event |

---

## 6. Access rules

| Action | Rule |
|--------|------|
| See / join the event room | Caller is a joiner **or** follower of `event.group_id` — reuses `_is_eligible_for_group_chat`, so no new permission concept. RSVP is *not* required |
| Room exists | Lazily created on first message or first WS connect, caller becomes `CREATOR` — identical to `resolve_or_create_group_room` |
| RSVP (`POST /events/{id}/join`) | Also adds the user to the room as `MEMBER` (or clears `left_at`) so the room appears in their inbox before they ever type |
| Un-RSVP (`DELETE /events/{id}/join`) | Leaves the room (`leave_member`), same as the existing group-leave hook |
| Room serves requests | `event.chat_enabled` is true **and** the owning group is published — extends the existing gate in `_get_room_or_404`. Flipping `chat_enabled` off broadcasts `room_closed` with reason `EVENT_CHAT_DISABLED` |
| Post a `PRAYER` | Any active member of an `EVENT` or `GROUP` room. 400 in `PRIVATE` rooms |
| Pray for a message | Any active member of the same room. Praying for your own request is allowed; a deleted message is 404 |

Content moderation (`validate_message_content`) and reporting apply to prayer requests unchanged.

---

## 7. API

### 7.1 Event room

```text
GET    /chat/events/{event_id}/room        -> ChatRoomDTO      (resolve/create)
POST   /chat/events/{event_id}/messages    -> ChatMessageDTO   (201)
WS     /chat/live?event_id=...             (third alternative to group_id / receiver_id)
```

`ChatRoomDTO.kind` gains `"EVENT"`; `ChatRoomDTO` gains `event_id`. `EventDTO` gains
`chat_room_id: UUID | null` and `chat_enabled: bool` so the event screen opens the room in one tap.

`SendChatMessageRequest` gains `message_type: "TEXT" | "PRAYER" = "TEXT"`, accepted on the existing
group/DM send endpoints too.

### 7.2 Prayers

```text
POST   /chat/rooms/{room_id}/prayers            -> PrayerBatchResponse  (200)
       body: { "message_ids": [uuid, ...] }     max 50, single transaction
DELETE /chat/messages/{message_id}/prayers/me   -> 204
GET    /chat/messages/{message_id}/prayers      -> ChatMessagePrayersResponse (paginated: who prayed)
GET    /chat/rooms/{room_id}/messages?message_type=PRAYER   (existing endpoint, new filter)
```

`POST .../prayers` is the multi-select action: the client sends the ids the user ticked, the server inserts
with `ON CONFLICT DO NOTHING` and returns the fresh state of each:

```json
{ "prayers": [ { "message_id": "...", "prayer_count": 12, "prayed_by_me": true, "created": true } ] }
```

`ChatMessageDTO` gains, for `PRAYER` messages only:

```json
"message_type": "PRAYER",
"prayer_count": 12,
"prayed_by_me": false,
"recent_prayers": [ { "user_id": "...", "name": "...", "avatar_url": "..." } ]
```

`recent_prayers` is capped at 3 (avatar stack); the full roster comes from the dedicated endpoint.
Like `ChatMessageReactionDTO`, `prayed_by_me` is viewer-specific and is forced `false` on broadcast payloads.

### 7.3 Realtime

New event on the existing `chat:room:{room_id}:messages` channel, published by a
`ChatBroadcaster.broadcast_prayers` that mirrors `broadcast_reactions`:

```json
{ "type": "prayers_updated",
  "prayers": [ { "message_id": "...", "prayer_count": 12, "user_ids": ["..."] } ] }
```

A batch pray publishes **one** payload for all selected messages, so a 20-request "pray for all" is one
Redis publish, not twenty.

---

## 8. Notifications

New `NotificationType.PRAYER_RECEIVED`, added to `GROUP_SCOPED_TYPES` so users can mute it per group like
`CHAT_MESSAGE`. Delivery reuses the chat pipeline end to end:

- Backend enqueues a `PRAYER_RECEIVED` event on the chat notification queue keyed by `prayer_id`, with the
  same commit-then-send + reconcile-undispatched safety net as `enqueue_chat_message_notification`.
- New internal endpoint `GET /internal/prayer-notification-targets/{prayer_id}` returns targets and copy,
  built server-side like `get_chat_notification_targets`.
- Single recipient: the request's `sender_id`. Never notify a self-pray.
- **Coalescing:** suppress the push if one was already sent for that message within
  `PRAYER_NOTIFICATION_COALESCE_SECONDS` (default 900); copy then reads "12 people are praying for your
  request" from the live count instead of firing once per prayer.

---

## 9. Files to update

### WeBuddhist-Backend

| File | Change |
|------|--------|
| `migrations/versions/<rev>_add_event_rooms_and_prayers.py` | New. `chat_message_type` enum; `chat_rooms.event_id` + recreated `ck_chat_rooms_kind_shape` + `uq_chat_rooms_event_id`; `chat_messages.message_type` + prayer index; `chat_message_prayers`; `events.chat_enabled`. Separate migration for `ALTER TYPE notification_type ADD VALUE 'PRAYER_RECEIVED'` (non-transactional — must commit before the value is used) |
| `pecha_api/chat/enums.py` | `ChatMessageType`, `ChatMessageTypeEnum`, `ChatRoomKind` |
| `pecha_api/chat/models.py` | `ChatRoom.event_id` + constraint/index; `ChatMessage.message_type` + `prayers` relationship; new `ChatMessagePrayer` |
| `pecha_api/chat/repository.py` | `get_room_by_event_id`, `add_prayer`, `remove_prayer`, `get_prayer`, `get_prayers_map`, `list_message_prayers`, `count_message_prayers`, `list_undispatched_prayer_notifications`, `message_type` filter in `get_room_messages` |
| `pecha_api/chat/service.py` | `resolve_or_create_event_room`, `_is_eligible_for_event_chat`, `leave_event_chat_room`, `close_event_chat_sockets`, `kind` in `build_room_dto`, event/`chat_enabled` gate in `_get_room_or_404` |
| `pecha_api/chat/message_service.py` | `send_event_message_service`; `message_type` threaded through `_persist_message` (reject `PRAYER` in DMs); `pray_for_messages_service`, `unpray_message_service`, `list_message_prayers_service` |
| `pecha_api/chat/response_models.py` | `event_id` / `kind` on `ChatRoomDTO`; `message_type`, `prayer_count`, `prayed_by_me`, `recent_prayers` on `ChatMessageDTO`; `message_type` on `SendChatMessageRequest`; `PrayerBatchRequest/Response`, `ChatMessagePrayersResponse` |
| `pecha_api/chat/views.py` | Event room + message routes, three prayer routes, `event_id` on `/chat/live` (the "exactly one of" guard becomes three-way) |
| `pecha_api/chat/chat_websocket.py` | `broadcast_prayers` |
| `pecha_api/chat/notification_service.py`, `notification_dispatch_service.py`, `sqs_client.py`, `internal_views.py`, `notification_response_models.py` | `PRAYER_RECEIVED` event, targets endpoint, copy builder, coalescing |
| `pecha_api/notification/notification_preference_enums.py` | `PRAYER_RECEIVED` + add to `GROUP_SCOPED_TYPES` |
| `pecha_api/events/event_participant_service.py` | Join/leave hooks into the event room |
| `pecha_api/events/event_model.py`, `event_response_models.py`, `event_service.py` | `chat_enabled` column; `chat_room_id` + `chat_enabled` on `EventDTO`; `chat_enabled` on create/update requests |
| `pecha_api/events/cms_event_views.py` | Accept `chat_enabled`; close sockets when it flips off |
| `tests/chat/`, `tests/events/` | Room-shape constraint, eligibility, prayer idempotency, batch pray, DM rejection, broadcast payloads, notification coalescing |
| `documentation/API_CHANGES.md` | New endpoints + DTO fields |

### webuddhist-worker

| File | Change |
|------|--------|
| `worker_api/notifications/chat_sqs_client.py` | `PRAYER_RECEIVED` event constant + parse |
| `worker_api/notifications/services/chat_notification_consumer.py` | Branch on event type; idempotency key becomes `(prayer_id, push_device_id)` |
| `worker_api/notifications/services/backend_client.py` | Call `/internal/prayer-notification-targets/{prayer_id}` |
| `worker_api/notifications/schemas.py`, `enums.py` | Prayer target schema; `SessionType.PRAYER` if deep-linking needs it |

### WeBuddhist-Studio (CMS)

| File | Change |
|------|--------|
| `components/routes/groups/api/eventsApi.ts`, `schema/EventSchema.ts` | `chat_enabled` field |
| `components/routes/groups/GroupEventFormPage.tsx` | "Enable event chat" toggle |
| `components/routes/groups/GroupEventDetailPage.tsx` | Room summary: member count, message count, link to reports |
| `components/routes/chat-reports/ChatReportsPage.tsx`, `api/chatReportsApi.ts` | `message_type` badge and event room name on reported messages |

### Mobile client

Not in these repos — the group-chat UI lives in the app (`WeBuddhist/src/routes/chat` is the AI assistant,
unrelated). Client work: event detail → "Event chat" entry point; a composer type switch (Message / Prayer
request); a prayer-request bubble with count + avatar stack; multi-select "pray" mode with a batch confirm;
a "Prayer requests" filter tab; handling of `prayers_updated` and `room_closed`.

---

## 10. Rollout

1. **Migrations + models** — additive; `message_type` defaults to `TEXT`, so every existing row and client keeps working.
2. **Event rooms** — room resolution, RSVP hooks, WS `event_id`, `chat_enabled`. Shippable alone as a text-only event chat.
3. **Prayers** — table, endpoints, DTO fields, `prayers_updated` broadcast.
4. **Notifications** — backend enqueue + worker consumer + preference toggle.
5. **Studio + client** — CMS toggle, then the app UI.

Backwards compatible throughout: no existing endpoint changes shape, and `ck_chat_rooms_kind_shape` still
admits every row that satisfies it today.

## 11. Open questions

- Are prayer requests allowed in **group** rooms in v1, or events only? (The RFC allows both; it is one line either way.)
- Does un-praying need UI, or is `DELETE .../prayers/me` only a mis-tap undo?
- Does the requester see *who* prayed, or only a count — with the roster reserved for a future "gratitude" screen?
