# RFC: Repeat prayers and the "Praying together" roster

| Field | Value |
|-------|-------|
| **Status** | Proposed |
| **Date** | 2026-09-29 |
| **Scope** | WeBuddhist-Backend, mobile client. Worker and Studio unchanged. |
| **Related** | `rfc-event-rooms-and-prayers.md`, `rfc-prayer-notification-interval.md` |

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
| `first_prayed_at`, `last_prayed_at` | TIMESTAMPTZ NOT NULL | |

- UNIQUE `(message_id, user_id)` is the upsert target.
- The index `(message_id, last_prayed_at DESC)` backs the roster.
- The migration backfills one row (`prayer_count = 1`) per existing `chat_message_prayers` row.

### `chat_prayer_notifications` (new)

This table holds one row per prayer push sent (or queued) to a requester. It replaces the per-prayer dispatch columns on `chat_message_prayers`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | Sent to the worker (§4) |
| `message_id` | UUID FK → `chat_messages.id` ON DELETE CASCADE | The prayer request |
| `people_count` | INTEGER NOT NULL | Distinct people who prayed since the previous push |
| `prayer_total` | BIGINT NOT NULL | Prayers added since the previous push |
| `latest_user_id` | UUID FK → `users.id` | The name shown in the push |
| `total_at_push` | BIGINT NOT NULL | `SUM(prayer_count)` for the request at this push, excluding the requester. The next push subtracts it |
| `created_at` | TIMESTAMPTZ NOT NULL | Starts the interval |
| `notification_sqs_message_id`, `notification_dispatched_at` | | As on other notification rows; `NULL` means reconcile retries it |

- The index `(message_id, created_at DESC)` finds the last push.

`chat_message_prayers` stays the "is praying" record, written on the first prayer only. `prayed_by_me`, the people count and `prayers_updated` are unchanged. Its `notification_*` columns are no longer written for new prayers.

## 4. Behaviour

### Pray — `POST /chat/rooms/{room_id}/prayers`

The body gains `count`: optional, default `1`, `1–10`, otherwise `422`. It is added to **each** id in `message_ids`.

```json
{ "message_ids": ["7c0e…"], "count": 10 }
```

In one transaction per id:
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

- **What is counted:** prayers, not calls. A call adds `count × len(message_ids)` to a Redis one-second window on the key `chat:pray-rate:{user_id}`, using an atomic `INCRBY`/`EXPIRE` script. This is the same pattern as `allow_set` in `recitation_websocket.py`.
- **When it is checked:** before any database write.
- **What passes:** a call is allowed only if the window stays at or below **10**. So one call of `count: 10` for one request uses the whole second.
- **Over the limit:** `429`, `Retry-After: 1`, and nothing is written.
- **If Redis is down:** calls are allowed.

To offer 100 prayers, the client sends `count: 10` once a second for 10 seconds.

### Prayer notification — one push per request per interval

- **Interval:** it reuses `PRAYER_REQUEST_NOTIFICATION_INTERVAL_SECONDS`, the prayer-request interval (default 1140s, about 20 min). `PRAYER_NOTIFICATION_COALESCE_SECONDS` (900s) is retired.
- **Gate:** it runs for each prayed-for request after the pray commit, and does nothing if the caller is the requester.
  1. Lock the request's last `chat_prayer_notifications` row (`SELECT … FOR UPDATE`, ordered by `created_at DESC`). The lock stops two concurrent calls from both deciding to push.
  2. If that row's `created_at` is inside the interval, stop. These prayers are counted in the next push.
  3. Otherwise, compute the summary since the previous push, excluding the requester's own prayers:
     - `people_count` = rows in `chat_message_prayer_counts` with `last_prayed_at >` the previous push's `created_at`, or all rows if there was no push yet.
     - `prayer_total` = the current `SUM(prayer_count)` minus the previous row's `total_at_push`, or minus 0 if there was no push yet.
     - `latest_user_id` = the row with the newest `last_prayed_at`.
  4. Insert the new row, commit, and send `PRAYER_RECEIVED` to SQS. Then record the SQS id, as `enqueue_prayer_notification` does today.
- **Copy:** the title is the room name, as today. The body depends on the numbers:

| People | Prayers | Body |
|--------|---------|------|
| 1 | 1 | `Kunsang prayed for you` |
| 1 | > 1 | `Kunsang prayed for you 10 times` |
| > 1 | any | `Kunsang with 9 others prayed for you 100 times` |

- **Worker:** unchanged. The event keeps `event_type: PRAYER_RECEIVED` and its `prayer_id` field, which now carries the `chat_prayer_notifications.id`. `GET /internal/prayer-notification-targets/{id}` resolves that id from the new table and builds the copy from the stored row.
- **Reconcile:** `reconcile_undispatched_prayer_notifications` now reads `chat_prayer_notifications` rows with no SQS id.
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

### Roster — `GET /chat/messages/{message_id}/prayers`

- **Only the requester can read it.** If the caller is not the request's author (`message.sender_id != caller`), return `403` ("Only the requester can see who is praying") and no roster data. The membership check still runs first.
- It reads from the counts table joined to `users`, ordered by `last_prayed_at DESC`.
- `ChatMessagePrayerDTO` adds `prayer_count` and `last_prayed_at`.
- `total` still counts people.

## 5. Files

| File | Change |
|------|--------|
| `migrations/versions/<rev>_add_prayer_counts_and_notifications.py` | Both tables and the counts backfill |
| `pecha_api/chat/models.py` | `ChatMessagePrayerCount`, `ChatPrayerNotification` |
| `pecha_api/chat/repository.py` | Counter upsert in the same commit as the prayer insert; unpray deletes both rows; roster query; last-push lookup with a lock, the summary query, and a notification insert |
| `pecha_api/chat/message_service.py` | Pass `count`, return `my_prayer_count`, map roster fields; roster `403` unless the caller is the author; run the gate on every pray |
| `pecha_api/chat/notification_dispatch_service.py` | Gate and enqueue keyed on the request, not on a prayer row; reconcile reads the new table |
| `pecha_api/chat/notification_service.py` | `get_prayer_notification_targets` resolves a `chat_prayer_notifications` id; new `_build_prayer_notification_copy` |
| `pecha_api/chat/prayer_rate_limit.py` | New: `allow_pray(user_id, prayers)` |
| `pecha_api/chat/response_models.py` | `count` on the request (`1–10`); new DTO fields |
| `pecha_api/chat/views.py` | `429` check; docstrings |
| `pecha_api/config.py` | Remove `PRAYER_NOTIFICATION_COALESCE_SECONDS` |
| `tests/chat/…` | See the test list below |

**Tests** in `tests/chat/…`:
- Repeat taps; `count` of 1, 10, and out of range.
- An 11th prayer in a second gets `429` and writes nothing; Redis down lets calls through.
- One push per interval.
- The copy for 1 person × 1 prayer, 1 person × N prayers, and N people × M prayers.
- The requester's own prayers are excluded from counts; concurrent calls produce a single push; reconcile retries unsent pushes.
- Unpray, roster order, and roster `403` for a member who isn't the author.

**Mobile client changes:**
- Batch taps for about 300 ms and send them as one call with `count` (at most 10).
- A "+100" action sends 10 calls, one per second.
- On `429`, retry after `Retry-After`.
- Show the "Praying together" screen only on the user's own requests.

## 6. Open questions

- Prayers that land inside the interval with nobody praying afterwards never get a push. This matches the prayer-request interval. Should a delayed "trailing" push cover them?
- Should the interval be per requester (one push across all of a user's requests) rather than per request?
- Should one person's total per request have a lifetime cap?
- Should the request card show total prayers as well as people?
- `recent_prayers` (the avatar stack on each message) still shows who is praying to every member. Should it also be limited to the requester?
