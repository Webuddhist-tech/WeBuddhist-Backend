# RFC: Repeat prayers and the "Praying together" roster

| Field | Value |
|-------|-------|
| **Status** | Implemented (see §7 for changes made during implementation) |
| **Date** | 2026-09-29 |
| **Scope** | WeBuddhist-Backend, mobile client. Worker and Studio unchanged. |
| **Related** | `rfc-event-rooms-and-prayers.md`, `rfc-prayer-notification-interval.md`, `event-chat-and-prayers-api.md` |

## 1. Summary

- A member can pray for the same request **more than once**, adding `count` prayers per call (default 1, max 10).
- A user can add at most **10 prayers per second**.
- Per-person totals live in a new table, `chat_message_prayer_counts`.
- The roster endpoint returns each person's name, avatar and count, and only to the member who **posted** the request.
- The requester gets at most **one prayer push per request per interval**, which summarises everything since the last push: `Kunsang with 9 others prayed for you 100 times`.
- "N people are praying" still counts **people**.

## 2. Problem

- `chat_message_prayers` is `UNIQUE (message_id, user_id)` and inserts with `ON CONFLICT DO NOTHING`, so a second tap is discarded.
- Once repeats count, nothing stops a held button or a script from inflating them.
- The roster has no count, and any room member can read who is praying for someone else's request.
- `PRAYER_RECEIVED` fires only on a person's first prayer, on a 900s window, and says only "N people are praying". It cannot report repeat prayers or how many there were.

## 3. Data model

### `chat_message_prayer_counts` (new)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `message_id` | UUID FK → `chat_messages.id` ON DELETE CASCADE | |
| `user_id` | UUID FK → `users.id` ON DELETE CASCADE | |
| `prayer_count` | BIGINT NOT NULL | CHECK `>= 1` |
| `unreported_count` | BIGINT NOT NULL DEFAULT 0 | Prayers not yet reported to the requester. Each pray adds to it; a push reads and zeroes it (§7) |
| `first_prayed_at`, `last_prayed_at` | TIMESTAMPTZ NOT NULL | |

- UNIQUE `(message_id, user_id)` is the upsert target.
- The index `(message_id, last_prayed_at DESC)` backs the roster.
- The migration backfills one row (`prayer_count = 1`, `unreported_count = 0`) per existing `chat_message_prayers` row. Those prayers were covered by the old notifications, so they are never reported again.

### `chat_prayer_notifications` (new)

This table holds one row per prayer push sent (or queued) to a requester. It replaces the per-prayer dispatch columns on `chat_message_prayers`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | Sent to the worker (§4) |
| `message_id` | UUID FK → `chat_messages.id` ON DELETE CASCADE | The prayer request |
| `people_count` | INTEGER NOT NULL | Distinct people whose prayers this push reports |
| `prayer_total` | BIGINT NOT NULL | Prayers this push reports |
| `latest_user_id` | UUID FK → `users.id` ON DELETE SET NULL | The name shown in the push |
| `created_at` | TIMESTAMPTZ NOT NULL | Starts the interval |
| `notification_sqs_message_id`, `notification_dispatched_at` | | As on other notification rows; `NULL` means reconcile retries it |

- The index `(message_id, created_at DESC)` finds the last push.

`chat_message_prayers` stays the "is praying" record, written on the first prayer only. `prayed_by_me`, the people count and `prayers_updated` are unchanged. Its `notification_*` columns are no longer written for new prayers.

## 4. Behaviour

### Pray — `POST /chat/rooms/{room_id}/prayers`

The body gains `count`: optional, default `1`, `1–10`, otherwise `422`. It is added to **each** id in `message_ids`, which accepts at most 10 ids (§7).

```json
{ "message_ids": ["7c0e…"], "count": 10 }
```

In one transaction:
1. Insert into `chat_message_prayers` with `ON CONFLICT DO NOTHING`, as today.
2. Upsert the counter:

```sql
INSERT INTO chat_message_prayer_counts (..., prayer_count, first_prayed_at, last_prayed_at)
VALUES (..., :count, now(), now())
ON CONFLICT (message_id, user_id)
DO UPDATE SET prayer_count = chat_message_prayer_counts.prayer_count + EXCLUDED.prayer_count,
              last_prayed_at = now()
RETURNING message_id, prayer_count;
```

After the commit, **every** call runs the notification gate (below), not only a first prayer. The response adds `my_prayer_count`.

### Rate limit — 10 prayers per second per user

- **What is counted:** prayers, not calls. A call adds `count × len(message_ids)` to a Redis one-second window on the key `chat:pray-rate:{user_id}`, using an atomic Lua script modelled on `allow_set` in `recitation_websocket.py`.
- **When it is checked:** before any database write.
- **What passes:** a call is allowed only if the window stays at or below **10**. So one call of `count: 10` for one request uses the whole second.
- **Over the limit:** `429`, `Retry-After: 1`, and nothing is written — neither the prayers nor the rate counter.
- **Only written prayers are kept:** after the call, the charge for ids that were skipped (no longer live prayer requests) is released back to the window, and a call the service refuses (`403`, `404`) releases its whole charge (§7).
- **If Redis is down:** calls are allowed.

To offer 100 prayers, the client sends `count: 10` once a second for 10 seconds.

### Prayer notification — one push per request per interval

- **Interval:** it reuses `PRAYER_REQUEST_NOTIFICATION_INTERVAL_SECONDS`, the prayer-request interval (default 1140s, about 20 min). `PRAYER_NOTIFICATION_COALESCE_SECONDS` (900s) is retired.
- **Gate:** it runs for each prayed-for request after the pray commit, and does nothing if the caller is the requester.
  1. Lock the prayer request's `chat_messages` row (`SELECT … FOR UPDATE`). The lock stops two concurrent calls from both deciding to push (§7).
  2. Read the request's last `chat_prayer_notifications` row. If its `created_at` is inside the interval, stop. These prayers are counted in the next push.
  3. Otherwise, work out what is new, leaving out the requester's own prayers:
     - Claim the request's unreported prayers: in one statement, lock every counts row with `unreported_count > 0`, read the counts and set them to 0.
     - `people_count` = claimed rows, `prayer_total` = the sum of their counts, `latest_user_id` = the one with the newest `last_prayed_at`. If there are none, stop and roll back.
  4. Insert the new row and commit it together with the zeroed counts. Then send `PRAYER_RECEIVED` to SQS and record the SQS id.
- **Copy:** the title is the room name, as today. The body depends on the numbers:

| People | Prayers | Body |
|--------|---------|------|
| 1 | 1 | `Kunsang prayed for you` |
| 1 | > 1 | `Kunsang prayed for you 10 times` |
| > 1 | any | `Kunsang with 9 others prayed for you 100 times` |

- **Worker:** unchanged. The event keeps `event_type: PRAYER_RECEIVED` and its `prayer_id` field, which now carries the `chat_prayer_notifications.id`. `GET /internal/prayer-notification-targets/{id}` resolves that id from the new table and builds the copy from the stored row. An id from an event queued before deploy is still a `chat_message_prayers` id; it is read as one person praying once (§7). The response keeps every existing field and adds `people_count` and `prayer_total`.
- **Reconcile:** `reconcile_undispatched_prayer_notifications` now reads `chat_prayer_notifications` rows with no SQS id and resends them without re-running the gate.
- **No queue configured:** no row is written, so the interval does not tick without a push.
- **Unchanged:** the notification preference check (`PRAYER_RECEIVED`, per group).

**Example** (interval 20 min):

| Time | What happens | Push? |
|------|--------------|-------|
| 10:00 | Kunsang prays once | `Kunsang prayed for you` |
| 10:05–10:19 | 9 others pray, and Kunsang taps again; 100 prayers in all | No, still inside the interval |
| 10:25 | Dolma prays 10 | `Dolma with 10 others prayed for you 110 times` |
| 10:30 | Nobody prays | No push. The interval does not tick by itself |

### Unpray — `DELETE /chat/messages/{message_id}/prayers/me`

Deletes both rows. The response returns `my_prayer_count: 0`. This call is not rate-limited and sends no push.

### Who sees what

| | Your own request | Someone else's request |
|---|---|---|
| "N people are praying" (`prayer_count` on the message) | Yes | Yes (unchanged) |
| Whether you pray (`prayed_by_me`), your own count (`my_prayer_count`) | Yes | Yes |
| Who is praying, and how many times each person prayed (roster) | Yes | No, `403` |

`my_prayer_count` is on the pray/unpray responses and on every `PRAYER` message in `GET /chat/rooms/{room_id}/messages`.

### Roster — `GET /chat/messages/{message_id}/prayers`

- **Only the requester can read it.** If the caller is not the request's author (`message.sender_id != caller`), return `403` ("Only the requester can see who is praying") and no roster data. The membership check still runs first.
- It reads from the counts table joined to `users`, ordered by `last_prayed_at DESC`.
- `ChatMessagePrayerDTO` adds `prayer_count` and `last_prayed_at`; `created_at` is the first prayer.
- `total` still counts people.

## 5. Files

| File | Change |
|------|--------|
| `migrations/versions/pc1a2b3c4d5e_add_prayer_counts_and_notifications.py` | Both tables, the counts backfill, and dropping `idx_chat_message_prayers_undispatched` |
| `pecha_api/chat/models.py` | `ChatMessagePrayerCount`, `ChatPrayerNotification` |
| `pecha_api/chat/repository.py` | `add_prayers` (prayer insert + counter upsert, one commit); `remove_prayer_and_count`; `get_my_prayer_counts_map`; roster query; `lock_prayer_request`, `get_last_prayer_notification`, `claim_unreported_prayers`, `create_prayer_notification` and the dispatch helpers |
| `pecha_api/chat/message_service.py` | Pass `count`, return `my_prayer_count`, map roster fields; roster `403` unless the caller is the author; run the gate on every pray |
| `pecha_api/chat/notification_dispatch_service.py` | `notify_prayers_for_request` gate keyed on the request; reconcile reads the new table |
| `pecha_api/chat/notification_service.py` | `get_prayer_notification_targets` resolves a `chat_prayer_notifications` id; new `_build_prayer_notification_copy` |
| `pecha_api/chat/prayer_rate_limit.py` | New: `allow_pray(user_id, prayers)` |
| `pecha_api/chat/response_models.py` | `count` on the request (`1–10`); batch cap 10; new DTO fields |
| `pecha_api/chat/views.py` | `429` check; docstrings |
| `pecha_api/config.py` | Remove `PRAYER_NOTIFICATION_COALESCE_SECONDS` |

**Mobile client changes:**
- Batch taps for about 300 ms and send them as one call with `count` (at most 10).
- A "+100" action sends 10 calls, one per second.
- On `429`, retry after `Retry-After`.
- Multi-select pray is capped at 10 requests.
- Show the "Praying together" screen only on the user's own requests.

## 6. Open questions

- Prayers that land inside the interval with nobody praying afterwards never get a push. This matches the prayer-request interval. Should a delayed "trailing" push cover them?
- Should the interval be per requester (one push across all of a user's requests) rather than per request?
- Should one person's total per request have a lifetime cap?
- Should the request card show total prayers as well as people?
- `recent_prayers` (the avatar stack on each message) still shows who is praying to every member. Should it also be limited to the requester?

## 7. Changes made during implementation

1. **Batch cap lowered from 50 to 10.** A call charges `count × len(message_ids)`, so a multi-select of 11 or more requests could never pass the 10-per-second limit even at `count: 1`. The cap now matches the limit, and larger selections get a `422` instead of a permanent `429`.
2. **The gate locks the request row, not the last push.** Before a request's first push there is no `chat_prayer_notifications` row to lock, so locking it would let two concurrent first prayers both push.
3. **A rejected call writes nothing to Redis either.** The script only increments when the new total fits, so a rejected `count: 10` does not use up the second for a `count: 1` right behind it. It also repairs a key that has lost its TTL.
4. **Pushes count unreported prayers, not the difference between totals.** The RFC's `total_at_push` design subtracted the previous total from the current one. An unpray lowers that total, so new prayers were undercounted, and on a request with no push yet every backfilled prayer looked new. Each counts row now carries `unreported_count`, which a push claims under row locks and commits together with its own row. It reports exactly the prayers added since the last push, a pray racing a push waits for its lock and is reported by the next push, and backfilled rows start at 0.
5. **`idx_chat_message_prayers_undispatched` is dropped.** New prayer rows never record a dispatch, so every one of them would land in that partial index, and nothing reads it once reconcile moves to the new table.
6. **One transaction for all ids** rather than one per id, matching the existing batch insert. The ids are already de-duplicated.
7. **Events queued at deploy still resolve.** They carry old `chat_message_prayers` ids, so the targets endpoint falls back to that table and reads one as one person praying once. The fallback can be removed one release later. Old prayer rows that never reached the queue (the commit-before-send crash window) are no longer retried.
8. **Unused allowance is released.** A call is still charged `count × len(message_ids)` before any write, so the limit holds without a database read in front of it. Afterwards the charge for skipped ids is given back, and a call the service refuses gives back all of it, so a just-deleted request in a selection or a `404` does not use up the second. The release never takes the window below zero and never recreates an expired window.
