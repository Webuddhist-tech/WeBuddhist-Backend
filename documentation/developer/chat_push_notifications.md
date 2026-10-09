# Chat Push Notifications

This document describes how the Pecha backend produces chat push-notification
events for the WebBuddhist worker.

## Flow

1. A user sends a direct or group chat message (REST or WebSocket).
2. Backend persists the message in `chat_messages`.
3. Backend enqueues a versioned SQS event to `CHAT_NOTIFICATION_SQS_QUEUE_URL`.
4. Worker consumes the event and fetches recipients/devices from the backend
   internal API.
5. Worker sends FCM notifications and deactivates permanently invalid tokens.

## SQS event contract

```json
{
  "event_type": "CHAT_MESSAGE_CREATED",
  "version": 1,
  "message_id": "d2e3f4a5-b6c7-8901-bcde-f12345678901"
}
```

The event intentionally contains only the message ID. Title, body preview, and
recipient devices are resolved by the backend when the worker asks for targets.

## Prayer queue

Prayer pushes go to `PRAYER_NOTIFICATION_SQS_QUEUE_URL` instead of the chat
queue, so a burst of prayers never delays ordinary chat pushes:

| Push | Event |
|------|-------|
| Prayer request (`message_type=PRAYER`, sent to the whole room) | `CHAT_MESSAGE_CREATED` with `message_id`, same as above |
| Someone prayed for your request | `PRAYER_RECEIVED` with `prayer_id` |

When `PRAYER_NOTIFICATION_SQS_QUEUE_URL` is empty, both fall back to the chat
queue. The worker handles either event on either queue, so the backend and
worker can be deployed in any order.

## Dispatch tracking

`chat_messages` stores:

| Column | Purpose |
|--------|---------|
| `notification_sqs_message_id` | SQS MessageId after successful enqueue |
| `notification_dispatched_at` | UTC timestamp of successful enqueue |

A scheduler job re-enqueues messages that remain undispatched after a grace
period (`CHAT_NOTIFICATION_DISPATCH_RECONCILE_*`). Worker Redis idempotency
makes duplicate events safe.

## Internal endpoints

Auth: `X-Dispatch-Token` (`NOTIFICATION_DISPATCH_SECRET_TOKEN`)

### `GET /api/v1/internal/chat-notification-targets/{message_id}`

Paginated recipient + device list for one chat message.

Query params: `skip`, `limit` (max 500).

**Recipient rules:**

| Chat kind | Recipients |
|-----------|------------|
| Private | The other participant only |
| Group | Users in `author_group_joins` for the room's `group_id`, excluding the sender |
| Event | Event room members; preferences scope to the owning group |

After membership, **PUSH** preferences filter who remains (see
[notification-preferences-api.md](../notification-preferences-api.md) §7):

| Message | `NotificationType` | Scope |
|---------|-------------------|--------|
| `TEXT` (group or event room) | `CHAT_MESSAGE` | Group (+ global) |
| `PRAYER` | `PRAYER_REQUEST` | Group (+ global); independent of chat |
| Private `TEXT` | `CHAT_MESSAGE` | Global only |

Users without active push devices are omitted from `recipients`, but still
counted in `total` for pagination.

### `GET /api/v1/internal/prayer-notification-targets/{prayer_id}`

Targets the **requester** for a `PRAYER_RECEIVED` push. Filtered with
`PRAYER_RECEIVED` (global or per group). `prayer_id` is a
`chat_prayer_notifications.id`.

### `POST /api/v1/internal/push-devices/deactivate`

```json
{ "push_device_id": "..." }
```

Sets `push_device_tokens.is_active = false` for a permanently invalid FCM token.

## Configuration

| Variable | Purpose |
|----------|---------|
| `CHAT_NOTIFICATION_SQS_QUEUE_URL` | Dedicated chat notification queue |
| `PRAYER_NOTIFICATION_SQS_QUEUE_URL` | Prayer requests and "someone prayed" pushes (empty = use the chat queue) |
| `CHAT_NOTIFICATION_DISPATCH_RECONCILE_GRACE_SECONDS` | Wait before re-enqueue |
| `CHAT_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS` | Scheduler interval |
| `CHAT_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE` | Max messages per reconcile pass |
| `CHAT_NOTIFICATION_PREVIEW_MAX_LENGTH` | Max notification body preview length |
| `NOTIFICATION_DISPATCH_SECRET_TOKEN` | Shared secret for worker ↔ backend |

Create the SQS queue with a DLQ for poison messages. Use the same AWS
credentials already used for audio job enqueueing.
