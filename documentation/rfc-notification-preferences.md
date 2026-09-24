# RFC: Per-User Notification Preferences

| Field | Value |
|-------|-------|
| **Status** | Proposed |
| **Date** | 2026-09-09 |
| **Scope** | WeBuddhist-Backend (schema + internal targets); worker unchanged |

---

## 1. Summary

Add one table, `user_notification_preferences`, with a row per preference the user has actually changed. Each row names a **type**, a **channel** (push / in-app / email), a **scope** (global, or one group), and whether it is **enabled** — plus an optional `muted_until` for temporary silence. No row means allowed — so no backfill, and new users are default-on.

Filtering happens in the recipient SQL behind `/internal/*-notification-targets/*`.

---

## 2. Problem

Every notification type fires at whoever the recipient query returns. A member of a busy group cannot keep event announcements while silencing chat, and cannot mute one group without leaving it.

All group-scoped fan-out already funnels through one function — `list_group_chat_recipient_user_ids` in `chat/notification_repository.py`, called by group posts, events and group chat. That is where the filter lands.

---

## 3. Why not a column per type

A flat table with `chat_enabled`, `event_enabled`, … queries trivially but fails on two counts:

- **Every new type is a migration.** Ten types exist and the list is growing — each costs a migration, a model change and a client contract change, for what should be an enum value.
- **`group_id` cannot share the row.** Muting two groups needs two rows, and the global toggles are then duplicated across them with no rule for which is authoritative.

---

## 4. Schema

```text
notification_type:    CHAT_MESSAGE | GROUP_POST | EVENT | EVENT_REMINDER | ACCUMULATION |
                      SERIES | GROUP_INVITE | GROUP_JOIN_REQUEST | VERSE_OF_DAY | ROUTINE_REMINDER
notification_channel: PUSH | IN_APP | EMAIL
notification_scope:   GLOBAL | GROUP          # extensible — see §7
```

```python
class UserNotificationPreference(Base):
    __tablename__ = "user_notification_preferences"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id           = Column(UUID(as_uuid=True),
                               ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notification_type = Column(NotificationTypeEnum, nullable=False)
    channel           = Column(NotificationChannelEnum, nullable=False, server_default="PUSH")
    scope_type        = Column(NotificationScopeEnum, nullable=False, server_default="GLOBAL")
    scope_id          = Column(UUID(as_uuid=True), nullable=True)   # group id when GROUP
    enabled           = Column(Boolean, nullable=False, default=True)
    muted_until       = Column(DateTime(timezone=True), nullable=True)
    created_at        = Column(DateTime(timezone=True), nullable=False, ...)
    updated_at        = Column(DateTime(timezone=True), nullable=False, ...)

    __table_args__ = (
        # Postgres does not dedupe NULLs, so global and scoped rows need separate indexes
        Index("uq_user_notif_pref_global",
              "user_id", "notification_type", "channel",
              unique=True, postgresql_where=(scope_id.is_(None))),
        Index("uq_user_notif_pref_scoped",
              "user_id", "notification_type", "channel", "scope_type", "scope_id",
              unique=True, postgresql_where=(scope_id.isnot(None))),
        Index("idx_user_notif_pref_lookup", "notification_type", "channel", "user_id"),
        # Written as an equivalence so new scope values need no constraint change
        CheckConstraint(
            "(scope_type = 'GLOBAL') = (scope_id IS NULL)",
            name="ck_user_notif_pref_scope",
        ),
    )
```

The partial-unique-index pattern already exists in `push_devices/push_device_models.py` for the nullable `device_id`.

**Group-scoped types** (accept a `GROUP` row): `CHAT_MESSAGE`, `GROUP_POST`, `EVENT`, `ACCUMULATION`. The rest are global-only.

**v1 toggles:** chat, group post, event, event reminder, accumulation, series — on the `PUSH` channel. `IN_APP` and `EMAIL` are in the schema but not yet read by any dispatcher; wiring them is a service change, not a migration. Verse of day and routine reminders follow in v2. Invites and join requests stay untoggleable — they are transactional; a user who asked to join expects the answer.

---

## 5. Resolution and filtering

`enabled` and `muted_until` resolve differently, and deliberately so:

- **`enabled`** — most specific wins. A `GROUP` row for `(user, type, channel, group_id)` overrides a `GLOBAL` row for `(user, type, channel)`; absent both, allowed.
- **`muted_until`** — any applicable row suppresses. A global mute is a snooze, not a preference, so it silences a group the user has explicitly enabled. A row is muted while `muted_until > now()`.

Keeping `enabled` a real boolean (rather than storing opt-outs only) buys the useful case: mute group posts everywhere *except* one group. A row may also exist purely to hold a temporary mute (`enabled = true`, `muted_until` in the future); expired rows are inert and can be swept lazily.

One clause expresses the whole rule — the `IS NULL` checks cover the un-matched LEFT JOIN as well as the un-muted row:

```sql
LEFT JOIN user_notification_preferences g
       ON g.user_id = author_group_joins.user_id
      AND g.notification_type = :type AND g.channel = :channel
      AND g.scope_type = 'GROUP' AND g.scope_id = :group_id
LEFT JOIN user_notification_preferences u
       ON u.user_id = author_group_joins.user_id
      AND u.notification_type = :type AND u.channel = :channel
      AND u.scope_id IS NULL
WHERE COALESCE(g.enabled, u.enabled, TRUE) IS TRUE
  AND (g.muted_until IS NULL OR g.muted_until <= NOW())
  AND (u.muted_until IS NULL OR u.muted_until <= NOW())
```

**Apply it before pagination.** The clause goes inside `list_group_chat_recipient_user_ids`, ahead of `OFFSET/LIMIT` and inside the `count()`. The existing push-device check post-filters the list while `total` stays unfiltered; since the worker pages off `total`/`has_more`, doing the same with preferences would yield short pages and a wrong total.

---

## 6. API

All endpoints sit under the existing `/users/me` prefix — same router convention as `/users/me/push-devices` — and are scoped to the bearer token's user. `channel` is a query parameter defaulting to `PUSH`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/users/me/notification-preferences` | Effective global preferences, plus the groups holding overrides |
| `PATCH` | `/users/me/notification-preferences` | Upsert one or more global preferences |
| `GET` | `/users/me/notification-preferences/groups/{group_id}` | Effective preferences for one group |
| `PATCH` | `/users/me/notification-preferences/groups/{group_id}` | Upsert per-group overrides |
| `DELETE` | `/users/me/notification-preferences/groups/{group_id}` | Clear overrides, falling back to global |

`GET` always returns every applicable type with stored rows merged over the defaults, so a client renders the full toggle list without knowing which rows exist. Each entry carries a `source` — `GROUP`, `GLOBAL` or `DEFAULT` — which is what drives an "overridden" badge in the UI.

`PATCH` bodies are sparse: send only the types being changed. Omitted types are untouched; `enabled` and `muted_until` can be sent together or separately.

### 6.1 Mute one group's posts and events

The headline case. One call, no effect on any other group:

```http
PATCH /users/me/notification-preferences/groups/3f2b…c91a
Content-Type: application/json

{
  "preferences": [
    { "notification_type": "GROUP_POST", "enabled": false },
    { "notification_type": "EVENT",      "enabled": false }
  ]
}
```

```json
200 OK
{
  "group_id": "3f2b…c91a",
  "channel": "PUSH",
  "preferences": [
    { "notification_type": "CHAT_MESSAGE", "enabled": true,  "muted_until": null, "source": "DEFAULT" },
    { "notification_type": "GROUP_POST",   "enabled": false, "muted_until": null, "source": "GROUP" },
    { "notification_type": "EVENT",        "enabled": false, "muted_until": null, "source": "GROUP" },
    { "notification_type": "ACCUMULATION", "enabled": true,  "muted_until": null, "source": "DEFAULT" }
  ]
}
```

Chat from that group still arrives. To silence it too, add `CHAT_MESSAGE` to the same array.

**The array is a merge, not a replacement.** To later re-enable events without touching the post setting, send only `EVENT`:

```http
PATCH /users/me/notification-preferences/groups/3f2b…c91a

{
  "preferences": [
    { "notification_type": "EVENT", "enabled": true }
  ]
}
```

`GROUP_POST` stays `false`. Only the types named in the array are upserted; omitting a type never changes or clears it. Clearing a type back to the global default is `DELETE` (§6.5), never an omission from `PATCH`.

The same holds field by field within an entry: sending `{"notification_type": "EVENT", "muted_until": "…"}` sets the snooze and leaves `enabled` as it was. Send both fields to change both. To lift a snooze early, send `"muted_until": null` — an explicit null clears it, where an absent key does not.

### 6.2 Snooze a whole group for eight hours

```http
PATCH /users/me/notification-preferences/groups/3f2b…c91a

{
  "preferences": [
    { "notification_type": "ALL", "muted_until": "2026-09-09T22:00:00Z" }
  ]
}
```

`ALL` is service-level sugar, not a stored enum value — the service fans it out into one row per group-scoped type (`CHAT_MESSAGE`, `GROUP_POST`, `EVENT`, `ACCUMULATION`). It exists because "Mute this group" is one button in the UI and should not require the client to enumerate types. The rows expire on their own; nothing needs to clear them.

### 6.3 Turn a type off everywhere

```http
PATCH /users/me/notification-preferences

{
  "preferences": [
    { "notification_type": "GROUP_POST", "enabled": false }
  ]
}
```

Combined with §6.1 in reverse — a `GLOBAL` row `false` plus a `GROUP` row `true` — this gives "no post notifications except from this one group", which is the case §5 keeps `enabled` a real boolean for.

### 6.4 Read what is in effect

```http
GET /users/me/notification-preferences?channel=PUSH
```

```json
200 OK
{
  "channel": "PUSH",
  "preferences": [
    { "notification_type": "CHAT_MESSAGE",   "enabled": true,  "muted_until": null, "source": "DEFAULT" },
    { "notification_type": "GROUP_POST",     "enabled": false, "muted_until": null, "source": "GLOBAL" },
    { "notification_type": "EVENT",          "enabled": true,  "muted_until": null, "source": "DEFAULT" },
    { "notification_type": "EVENT_REMINDER", "enabled": true,  "muted_until": null, "source": "DEFAULT" },
    { "notification_type": "ACCUMULATION",   "enabled": true,  "muted_until": null, "source": "DEFAULT" },
    { "notification_type": "SERIES",         "enabled": true,  "muted_until": null, "source": "DEFAULT" }
  ],
  "group_overrides": [
    { "group_id": "3f2b…c91a", "group_title": "Morning Practice", "overridden_types": ["GROUP_POST", "EVENT"], "muted_until": null }
  ]
}
```

`group_overrides` is a summary, not the full resolution — it exists so a settings screen can list "Groups with custom settings" without fetching each group. The per-group `GET` gives the resolved detail.

### 6.5 Reset a group to defaults

```http
DELETE /users/me/notification-preferences/groups/3f2b…c91a          # all types
DELETE /users/me/notification-preferences/groups/3f2b…c91a?notification_type=EVENT
```

Deletes the `GROUP` rows so resolution falls back to global. `204 No Content`; deleting rows that do not exist is not an error.

### 6.6 Validation

- A `notification_type` that is not group-scoped (`VERSE_OF_DAY`, `ROUTINE_REMINDER`, …) is rejected with `422` on the group endpoints.
- `GROUP_INVITE` and `GROUP_JOIN_REQUEST` are rejected on both endpoints in v1 — they are transactional and have no toggle.
- `muted_until` in the past is rejected with `422` rather than silently stored as an expired row.
- `group_id` the user is not a member of returns `404`, consistent with the other group endpoints.
- Because an absent field and an explicit `null` mean different things (§6.1), the request model must read `model_fields_set` — or serialise with `exclude_unset=True` — rather than treating a `None` default as "not sent".

---

## 7. Growing the scope enum

`scope_type` is expected to gain values — `SERIES`, `EVENT` — rather than spawning a second table. Two things keep that cheap:

- `ALTER TYPE … ADD VALUE` is non-blocking in Postgres 12+, so a new scope is a one-line migration with no table rewrite.
- The check constraint is written as `(scope_type = 'GLOBAL') = (scope_id IS NULL)`, which holds for any future scope without being rewritten.

When a second non-global scope goes live, the resolver picks the single most specific matching row and the SQL gains one more `LEFT JOIN` in the `COALESCE` chain, ordered narrowest first. Only one non-global scope applies per dispatch today.

---

## 8. Rollout

Additive alembic migration (table + three enum types, no backfill) → preference repository/service with an effective-value resolver → the five `/users/me/notification-preferences` endpoints in §6 → filter wired into the group-scoped queries on the `PUSH` channel. Rollback is dropping the table; nothing else reads it.
