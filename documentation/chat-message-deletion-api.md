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
their own messages**. There is no admin override on these two; moderation is a
separate, CMS-only surface — see [§6](#6-cms-moderation-delete-anyones-message).

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

A moderator deletion ([§6](#6-cms-moderation-delete-anyones-message)) publishes
the same event, with three differences in `deleted_by`:

```json
{ "type": "message_deleted",
  "message_id": "a1…",
  "deleted_by": { "user_id": "a9…", "name": "Tenzin", "source": "CMS" },
  "deleted_at": "2026-09-14T11:20:00+00:00" }
```

- `source` is `"CMS"` — key off it to say "removed by a moderator" rather than
  "deleted".
- `user_id` is the moderator's **author** id, not a chat user id. Don't look it
  up against room members.
- **`email` is absent.** A sender's own deletion carries their email because
  the room already shows it on every message they sent; a moderator is not a
  member of the room, so their CMS address is not disclosed to it. An author
  with no name on file shows as `"Moderator"` rather than falling back to the
  address. Read `name` for display and never expect `email` here.

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

These are the member-facing endpoints only; the CMS endpoint below has its own
error table.

---

## 6. CMS moderation — delete anyone's message

```http
DELETE /cms/author/groups/{group_id}/chat/messages/{message_id}
Authorization: Bearer <CMS author token>
```

`204 No Content`. This is the moderation counterpart to §1: it deletes the
message **whoever sent it**, in the chat room belonging to `group_id`.

**Who may call it.** An author whose role in that group lets them update the
group's content — `OWNER`, `ADMIN` or `AUTHOR`, the same set that gates every
other group content write (posts, events, plans). A platform `SUPER_ADMIN`
passes for any group; a `REVIEWER` is read-only across the CMS and is refused.

Two deliberate differences from the member endpoints:

- **The group, not the room, is in the path.** A group has exactly one chat
  room, so the moderator never has to look up a room id; authorisation is a
  property of the group anyway.
- **Room membership is not required.** A moderator moderates from the CMS
  without joining the chat. The member endpoints still demand active
  membership.

Otherwise it behaves exactly like §1: the same soft delete, the same tombstone
in history (§3), and the same `message_deleted` broadcast (§4) — so a client
already handling member deletions greys the message out with no change.

Only `GROUP` rooms are reachable this way. Event and private rooms have no
`group_id`, so they have no CMS moderation endpoint.

### Errors

| Status | Detail | Meaning |
|--------|--------|---------|
| 403 | `NO_GROUP_MEMBERSHIP` | The author has no role in this group, or only `VIEWER` |
| 403 | `FORBIDDEN` | Platform reviewer — the CMS is read-only for them |
| 404 | `Not found` | No such group, the group has no chat room, or the message is not a live message in it |

An unpublished group is still moderatable — its backlog is exactly what may
need cleaning up — so the publication check the member endpoints apply does not
apply here.
