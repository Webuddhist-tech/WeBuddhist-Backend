# RFC: Prayer request notification interval

| Field | Value |
|-------|-------|
| **Status** | Implemented |
| **Date** | 2026-09-25 |
| **Scope** | WeBuddhist-Backend (dispatch gate + copy + config). Worker, client, and schema unchanged. |

---

## 1. Summary

A room raises at most one prayer-request push per interval. The interval is `PRAYER_REQUEST_NOTIFICATION_INTERVAL_SECONDS`, default **1140** (19 minutes), read from config on every enqueue. Prayer requests posted inside the interval are stored and shown in the room as they are today; they do not raise their own push.

The push that is allowed keeps today's copy, and, when any were held back, ends with `+N other prayer requests`. The first request after the interval sends immediately. There is no clock-aligned job and no empty tick when nobody posted.

`PRAYER_RECEIVED` — the push telling a requester that someone prayed for them — is **not** changed by this RFC. It already coalesces per request, and it was never the flood.

---

## 2. Problem

Two different notifications are involved in prayers, and only one of them is throttled.

| | "Someone prayed for your request" | "A prayer request came up" |
|---|---|---|
| Type | `PRAYER_RECEIVED` | `CHAT_MESSAGE`, `message_type=PRAYER` |
| Audience | the requester alone | every member of the room |
| Enqueued by | `enqueue_prayer_notification` | `enqueue_chat_message_notification` |
| Gate today | self-pray check + 900s per-request coalesce | **none** |

`enqueue_chat_message_notification` sends to SQS unconditionally for every message that lands. A prayer request is an ordinary `chat_messages` row with `message_type = 'PRAYER'`, so every one of them fans out to the whole room the moment it is posted.

The arithmetic is the problem. Ten prayer requests in a 200-member sangha in one afternoon is two thousand pushes, and each member's phone buzzes ten times. The push that is already coalesced — one requester, one request, one push per 15 minutes — is not what wakes anybody up.

The room itself is fine. The "Prayer requests" tab shows every request, backed by `idx_chat_messages_room_prayers`. Only the push needs a gate.

---

## 3. Rule

Applies to a message with `message_type = 'PRAYER'`. A `TEXT` message is untouched and keeps today's behaviour exactly.

Measured from the room's last **sent** prayer-request push (`notification_dispatched_at` on a `PRAYER` row whose `notification_sqs_message_id` is a real SQS id, not `SUPPRESSED`):

1. If this room raised a prayer-request push inside the interval, mark this message `SUPPRESSED` and return. Reconcile ignores it, because `list_undispatched_chat_notification_messages` only selects `notification_sqs_message_id IS NULL`.
2. Otherwise enqueue the chat notification event as today and record the SQS id. This push starts the next interval.

`0` disables the interval: every prayer request sends, which is today's behaviour.

The check uses `now() - interval`, not a stored deadline, so changing the config applies on the next enqueue. A deploy that moves 1140 to 600 starts allowing pushes that the old window would still have held.

The interval is per **room**, which is per group for a group room and per event room for an event. That is the right grain because the flood is a property of the room: a busy sangha is what makes phones buzz, and a member of three sanghas should not have one of them silence the other two. It also means a member cannot be individually spared or individually held — see §6.

The person whose request was suppressed loses nothing they can see. Their request is in the room the instant they post it, the realtime update fires as always, and the next push that goes out carries it in the count.

### 3.1 What the push says

Built at read time in `get_chat_notification_targets`, so the text matches the rows that exist when the worker asks for targets. Title is unchanged. The body is today's copy, then the held count when there is one.

`held_count` is the number of `PRAYER` messages in this room marked `SUPPRESSED` after the previous sent push (`notification_dispatched_at` of the last real SQS id) and before this one. Deleted requests are excluded. The request being sent now is excluded. Zero means the suffix is omitted.

| `held_count` | Body |
|--------------|------|
| 0 | `Please pray for my mother's surgery` |
| 1 | `Please pray for my mother's surgery · +1 other prayer request` |
| n > 1 | `Please pray for my mother's surgery · +3 other prayer requests` |

Title stays `{sender_name} is requesting a prayer 🙏` in every case.

A room whose image could not be signed keeps the `{room_name}: ` prefix it has today, and the suffix goes after it: `Dharma Circle: Please pray for my mother's surgery · +3 other prayer requests`.

The suffix is appended **after** the preview is truncated to `CHAT_NOTIFICATION_PREVIEW_MAX_LENGTH`, so the cap applies to the request text and never to the count. The count is the part that must survive; a long request is what gets the ellipsis.

The held requests are not listed, and their senders are not named. The count says how many notifications the interval skipped; the room shows each one in full.

No new response field and no worker change: `title` and `body` already travel on `ChatNotificationTargetsResponse`, and the worker sends them as-is.

### 3.2 Example

Interval = 19 minutes. One group room, 200 members.

| Time | What happens | Push |
|------|--------------|------|
| 10:00 | Tenzin posts a prayer request | Yes. `Tenzin is requesting a prayer 🙏` / `Please pray for my mother's surgery` |
| 10:04 | Dolma posts a request | No. Marked `SUPPRESSED`. In the room immediately. |
| 10:11 | Pema posts a request | No. Same room, still inside the interval. |
| 10:20 | Karma posts a request, 20 minutes having elapsed | Yes. `Karma is requesting a prayer 🙏` / `Please pray for my father · +2 other prayer requests` |
| 10:39 | Nobody posts | No push. The interval does not tick by itself. |

The `+2` is Dolma's and Pema's requests, marked `SUPPRESSED` since the 10:00 push. Karma's own request is the body, not part of the count.

---

## 4. Config

```python
# At most one prayer-request push per room per this many seconds.
# 0 sends a push for every prayer request. TEXT messages are unaffected.
PRAYER_REQUEST_NOTIFICATION_INTERVAL_SECONDS=1140
```

Read with `get_int`, then `max(..., 0)`. The default lives in the `Config` dict in `pecha_api/config.py`, so no environment change is required to deploy this; set the variable only to override. `get_int` raises on a key absent from both the environment and that dict, so the dict entry is what makes the default work.

`PRAYER_NOTIFICATION_COALESCE_SECONDS` stays at 900 and keeps its meaning. It governs `PRAYER_RECEIVED`, which this RFC does not touch.

---

## 5. Queries

Both are on `chat_messages` and both are covered by the existing partial index `idx_chat_messages_room_prayers` — `(room_id, created_at DESC) WHERE message_type = 'PRAYER' AND deleted_at IS NULL`. No new index and no migration.

```python
def last_dispatched_prayer_request_at(
    db: Session,
    *,
    room_id: UUID,
    exclude_message_id: UUID,
) -> datetime | None:
    """When this room last actually raised a prayer-request push.

    Suppressed rows do not count: a suppressed request must not extend the
    interval. `exclude_message_id` keeps the message being dispatched from
    answering with its own timestamp.
    """
```

Filter `message_type == 'PRAYER'`, `deleted_at IS NULL`, `notification_dispatched_at IS NOT NULL`, `notification_sqs_message_id IS NOT NULL`, `notification_sqs_message_id != 'SUPPRESSED'`, `id != exclude_message_id`; order by `notification_dispatched_at` descending, take one.

**`exclude_message_id` is not optional, and it is the subtle part.** The gate runs at enqueue time, before this message is marked, so there it changes nothing. The count runs at target-build time, *after* the backend has already stamped this message with its real SQS id. Without the exclusion the "last sent push" resolves to the message being sent, `since` becomes roughly now, and `held_count` is always zero — the suffix would never appear. Worse, whether it resolves that way depends on whether the worker beat the backend's `mark_message_notification_dispatched` commit, so the count would be timing-dependent rather than reliably wrong. The exclusion removes both failure modes.

```python
def count_suppressed_prayer_requests(
    db: Session,
    *,
    room_id: UUID,
    since: datetime | None,
    exclude_message_id: UUID,
) -> int:
    """Prayer requests in this room marked SUPPRESSED after `since`.

    `since` is the previous sent push, or None when this room has never raised
    one. `exclude_message_id` is the request being sent now.
    """
```

Same filters, but `notification_sqs_message_id == 'SUPPRESSED'` and `id != exclude_message_id`. When `since` is set, also `notification_dispatched_at > since`, so an older interval's held requests are not counted twice.

`enqueue_chat_message_notification` does not load the message today. Rather than add a `SELECT` to every chat message send just to learn its type, both callers pass the type they already hold: `_persist_message` has it from `_validate_message_type`, and `reconcile_undispatched_chat_notifications` has the `ChatMessage` rows in hand. A `TEXT` message therefore costs exactly what it costs today.

Volume is one lookup per prayer-request enqueue, and one count per push that passed the gate. Nothing extra runs for ordinary chat.

Two prayer requests posted in the same room at the same instant can both pass the check before either is marked. That race exists today on the prayer path, the worker is idempotent per device, and the result is two pushes instead of one. Accepted; a row lock on the room is a follow-up if it shows up in practice.

---

## 6. Alternatives considered

**Per-recipient intervals.** Track the last prayer-request push per `(user_id, group_id)` and hold per member rather than per room. Strictly better targeting: a member who joined mid-interval, or whose device was off, is handled on their own clock. The cost is where it dies for now — a new table with its own migration, bookkeeping that has to stay idempotent across the target endpoint's pagination and across duplicate SQS deliveries, and `body` moving from the top of `ChatNotificationTargetsResponse` onto each `ChatNotificationRecipientDTO`, because `+3` for one member and no suffix for another cannot both live in one shared string. That last part forces a worker change. The room-level gate solves the flood — which is a property of the room, not of the member — at no schema cost, and can be refined into the per-recipient version later without changing the copy.

**Putting the interval on `PRAYER_RECEIVED` instead.** The first draft of this RFC did exactly that: a per-requester interval replacing the per-request coalesce. It aimed at the wrong notification. `PRAYER_RECEIVED` already folds twelve people praying into one push and already caps at one push per request per 15 minutes; the unbounded fanout was always the prayer-request side.

**Raising 900 to 1140 on the existing coalesce.** Changes the wrong number on the wrong path, and leaves every prayer request still pushing to every member.

**A scheduler that wakes every 19 minutes and fans out.** The first request would wait up to a full interval, every room's push would land on the same tick, and delivery would depend on the reconcile job, which today only retries rows that never recorded an SQS id (`CHAT_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS`, default 60). Silence when nobody posted is not a notification.

---

## 7. What does not change

- `PRAYER_RECEIVED` in full: the self-pray rule, `PRAYER_NOTIFICATION_COALESCE_SECONDS`, `has_dispatched_prayer_since`, `_build_prayer_notification_copy`, and `get_prayer_notification_targets`. Praying for a request is not the same event as posting one.
- `TEXT` chat notifications. No gate, no extra query, no copy change.
- Worker consumer and FCM payload. The held count is words in `body`, which the worker already forwards.
- `GET /internal/chat-notification-targets/{message_id}` keeps every field, including `image_url` and `message_type`. Only `body` gains the suffix.
- Notification preference filtering, including per-group mute, and the `PRAYER` message's use of the room image in place of the room name.
- Realtime message delivery. The room updates on every request; only the push is gated.
- Reconcile of rows that never got an SQS id. A prayer request that failed enqueue is retried and re-checked against the interval, so a retry inside the window becomes `SUPPRESSED` instead of a second push.
- Prayer requests remain rejected in DMs (`_validate_message_type`), so the gate only ever sees group and event rooms.

---

## 8. Files to update

| File | Change |
|------|--------|
| `pecha_api/config.py` | Add `PRAYER_REQUEST_NOTIFICATION_INTERVAL_SECONDS=1140`. Leave `PRAYER_NOTIFICATION_COALESCE_SECONDS` alone. |
| `pecha_api/chat/notification_dispatch_service.py` | `enqueue_chat_message_notification` takes `message_type`, gates `PRAYER` on the interval, marks held requests `SUPPRESSED`. `reconcile_undispatched_chat_notifications` passes the type it already has. |
| `pecha_api/chat/message_service.py` | `_persist_message` passes `message_type` to the enqueue call. |
| `pecha_api/chat/repository.py` | `last_dispatched_prayer_request_at` and `count_suppressed_prayer_requests`. |
| `pecha_api/chat/notification_service.py` | `_build_notification_copy` takes `held_count: int = 0` and appends the suffix for `PRAYER`. `get_chat_notification_targets` computes it for a `PRAYER` message only. |
| `tests/chat/test_chat_notification_service.py` | `TestPrayerRequestNotificationInterval` for the gate, `TestCountHeldPrayerRequests` for the two-query wiring, `TestHeldPrayerRequestCopy` for the suffix. The three existing assertions on the enqueue call signature gain `message_type` and `room_id`. |
| `tests/chat/test_chat_repository.py` | `TestLastDispatchedPrayerRequestAt` and `TestCountSuppressedPrayerRequests`. |
| `documentation/event-chat-and-prayers-api.md` | §5 gains the prayer-request interval. The `PRAYER_RECEIVED` coalesce paragraph stays as written. |
| `documentation/rfc-event-rooms-and-prayers.md` | Leave as historical. |

`tests/chat/test_chat_prayers.py` needs no change. Its `TestPrayerNotificationCoalescing` class covers `PRAYER_RECEIVED`, which this RFC leaves alone.

---

## 9. Rollout

Config, the dispatch gate for one message type, and the body built for a push that passes the gate. No migration, no new index, no worker deploy, no client change, no response-schema change. Rollback is removing the gate and the suffix; rows already marked `SUPPRESSED` stay ignored by reconcile and need no cleanup.
