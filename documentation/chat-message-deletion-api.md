# Chat Message Deletion — API

Client-facing reference for deleting chat messages, in any room kind (`GROUP`,
`EVENT` or `PRIVATE`). Companion to
[event-chat-and-prayers-api.md](./event-chat-and-prayers-api.md).

Deletion is a **soft delete**: the row survives as a tombstone so replies that
quote it still render, and so every connected client can grey it out live
instead of having a message vanish mid-scroll.

| Method | Path | Deletes |
|--------|------|---------|
| `DELETE` | `/chat/rooms/{room_id}/messages/{message_id}` | One message (204) |
| `DELETE` | `/chat/rooms/{room_id}/messages` | Several messages, 1-50 (204) |

Both require an active member of the room, and both let a caller delete **only
their own messages**. There is no admin override here — moderation is a
separate surface.

---

## 1. Delete one message

```http
DELETE /chat/rooms/{room_id}/messages/{message_id}
```

`204 No Content`. 403 if the message is not the caller's, 404 if it is not a
live message in this room (wrong room, already deleted, or never existed).

---

## 2. Delete several messages

The multi-select action: send the ids the user ticked.

```http
DELETE /chat/rooms/{room_id}/messages
{ "message_ids": ["a1…", "b2…", "c3…"] }     // 1-50 ids
```

`204 No Content`. The body carries the ids and nothing else; the room stays in
the path, as on every other message endpoint.

**All or nothing, deliberately.** If *any* id in the selection is not the
caller's, or is not a live message in this room, **nothing is deleted** and the
response names the offending ids:

```json
{ "detail": "message_ids include other users' messages: b2…, c3…" }
```

```json
{ "detail": "Not found: c3…" }
```

This is the opposite of the batch-pray endpoint, which skips bad ids and
proceeds. Praying again is harmless, so leniency costs the user nothing there;
deletion is destructive, so a partial success would leave the user guessing
which messages survived. Show the named ids, let them adjust the selection, and
re-send.

Two conveniences in the request model:

- Duplicate ids are collapsed, so the same message cannot be counted twice.
- The ids are capped at 50 per call (`MAX_MESSAGE_DELETE_BATCH_SIZE`). An empty
  list is rejected with 422.

Every message in one call is deleted in a single transaction and carries the
**same** `deleted_at`, so the batch cannot land half-applied.

---

## 3. What a deleted message looks like

A deleted message stays in history. `GET /chat/rooms/{room_id}/messages`
returns it with an empty `body` and a `deleted_at` stamp:

```json
{ "id": "a1…", "sender_id": "u1…", "sender_name": "Tenzin",
  "body": "", "created_at": "2026-09-14T10:04:00+00:00",
  "deleted_at": "2026-09-14T11:20:00+00:00" }
```

`deleted_at` is **omitted entirely** on a message that is not deleted — treat
its presence, not its value, as the flag.

- **Replies survive.** A reply whose parent was deleted still carries `parent`
  with the parent's `id`, sender and `deleted_at`; only `body` is emptied, so
  the thread still shows who was quoted.
- **The room list skips it.** `ChatRoomDTO.last_message` ignores deleted
  messages, so deleting the newest message in a room rolls the preview back to
  the one before it.

---

## 4. Live event

Both endpoints publish `message_deleted` to the room's WebSocket stream, so
clients grey the message out without refetching history:

```json
{ "type": "message_deleted",
  "message_id": "a1…",
  "deleted_by": { "user_id": "u1…", "email": "…", "name": "Tenzin" },
  "deleted_at": "2026-09-14T11:20:00+00:00" }
```

A bulk delete sends **one event per message**, all sharing the same
`deleted_at` — not a single batched payload. A client that already handles the
single delete therefore needs no change to support bulk.

Broadcasting is best-effort: the deletion is already committed, so a Redis
failure still returns 204 and the messages come back deleted on the next
history fetch.

---

## 5. Errors

| Status | Detail | Meaning |
|--------|--------|---------|
| 403 | `message_ids include other users' messages: <ids>` | Bulk: the selection is not entirely the caller's — nothing was deleted |
| 403 | `You can only delete your own messages` | Single: not the caller's message |
| 403 | — | Not an active member of the room |
| 404 | `Not found: <ids>` | Bulk: those ids are not live messages in this room — nothing was deleted |
| 404 | `Not found` | Single: room or message gone, or already deleted |
| 422 | — | `message_ids` empty, or more than 50 ids |
