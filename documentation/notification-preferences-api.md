# Notification Preferences — API

Client-facing reference for the endpoints in
[notification_preference_views.py](../pecha_api/notification/notification_preference_views.py).
The design rationale — why one table instead of a column per type, how
resolution works — is in [rfc-notification-preferences.md](./rfc-notification-preferences.md).

All five endpoints sit under `/users/me`, are scoped to the bearer token's
user, and take `channel` as a query parameter defaulting to `PUSH`.

---

## 1. The model in one paragraph

A preference is one row per `(user, notification_type, channel, scope)`, where
scope is either **global** or **one group**. Nothing stored means the
notification is **on** — no row is ever written just to say "default". Two
fields resolve differently: `enabled` is **most-specific-wins** (a group row
beats a global row beats the default), while `muted_until` is
**any-row-suppresses** (an unexpired snooze on either row silences, and the
resolved value is the later of the two).

Every `GET` returns the full toggle list with stored rows merged over the
defaults, so a settings screen renders without knowing which rows exist. Each
entry carries `source` — `GROUP`, `GLOBAL` or `DEFAULT` — which is what drives
an "overridden" badge.

---

## 2. Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/users/me/notification-preferences` | Effective global preferences + the groups holding overrides |
| `PATCH` | `/users/me/notification-preferences` | Upsert one or more global preferences |
| `GET` | `/users/me/notification-preferences/groups/{group_id}` | Effective preferences for one group |
| `PATCH` | `/users/me/notification-preferences/groups/{group_id}` | Upsert per-group overrides |
| `DELETE` | `/users/me/notification-preferences/groups/{group_id}` | Clear overrides, falling back to global |

All take `?channel=PUSH|IN_APP|EMAIL` (default `PUSH`). Rows are stored per
channel, but **only `PUSH` is read at dispatch today** — an `IN_APP` or `EMAIL`
row is saved and returned faithfully and silences nothing yet.

---

## 3. Which types are toggleable

Global list, in the order clients should render it:

`CHAT_MESSAGE`, `GROUP_POST`, `EVENT`, `EVENT_REMINDER`, `ACCUMULATION`,
`SERIES`, `PRAYER_RECEIVED`

Group list (the subset that accepts a per-group override), same order:

`CHAT_MESSAGE`, `GROUP_POST`, `EVENT`, `ACCUMULATION`, `PRAYER_RECEIVED`

`GROUP_INVITE` and `GROUP_JOIN_REQUEST` are transactional and rejected on both
endpoints with `422` — someone who asked to join a group expects to hear the
answer. `VERSE_OF_DAY` and `ROUTINE_REMINDER` are rejected on the *group*
endpoints (they have no group scope); a global `PATCH` accepts and enforces
them, but they are not part of the rendered list above, so a client that only
reads `GET` never sees them.

---

## 4. Reading

```http
GET /users/me/notification-preferences?channel=PUSH
```

```json
200 OK
{
  "channel": "PUSH",
  "preferences": [
    { "notification_type": "CHAT_MESSAGE",    "enabled": true,  "muted_until": null, "source": "DEFAULT" },
    { "notification_type": "GROUP_POST",      "enabled": false, "muted_until": null, "source": "GLOBAL" },
    { "notification_type": "EVENT",           "enabled": true,  "muted_until": null, "source": "DEFAULT" },
    { "notification_type": "EVENT_REMINDER",  "enabled": true,  "muted_until": null, "source": "DEFAULT" },
    { "notification_type": "ACCUMULATION",    "enabled": true,  "muted_until": null, "source": "DEFAULT" },
    { "notification_type": "SERIES",          "enabled": true,  "muted_until": null, "source": "DEFAULT" },
    { "notification_type": "PRAYER_RECEIVED", "enabled": true,  "muted_until": null, "source": "DEFAULT" }
  ],
  "group_overrides": [
    { "group_id": "3f2b…c91a", "group_title": "Morning Practice",
      "overridden_types": ["EVENT", "GROUP_POST"], "muted_until": null }
  ]
}
```

`group_overrides` is a flat index, not a resolution: it exists so a settings
screen can list "Groups with custom settings" without one request per group.
Sorted by `group_title`; `overridden_types` is sorted alphabetically; its
`muted_until` is the group's latest unexpired snooze, or null.

```http
GET /users/me/notification-preferences/groups/{group_id}?channel=PUSH
```

```json
200 OK
{ "group_id": "3f2b…c91a", "channel": "PUSH",
  "preferences": [ { "notification_type": "CHAT_MESSAGE", "enabled": true, "muted_until": null, "source": "DEFAULT" } ] }
```

Resolved *through* global, so a type turned off globally reads back
`enabled: false, source: "GLOBAL"` here until the group overrides it.

---

## 5. Writing

`PATCH` bodies are **sparse and merging**: only the types named in the array
are written, and within an entry only the fields actually sent. Both `PATCH`
endpoints return the same body their `GET` counterpart returns, freshly
resolved — no follow-up read needed.

### Mute one group's posts and events

```http
PATCH /users/me/notification-preferences/groups/3f2b…c91a
{ "preferences": [
    { "notification_type": "GROUP_POST", "enabled": false },
    { "notification_type": "EVENT",      "enabled": false }
] }
```

Chat and prayers from that group still arrive. Re-enabling events later means
sending `EVENT` alone — `GROUP_POST` is untouched by omission.

### Absent key is not an explicit null

`{"notification_type": "EVENT", "muted_until": "…"}` sets the snooze and leaves
`enabled` as it was. `"muted_until": null` **lifts** a snooze; leaving the key
out does not. An entry that sends neither field is `422` — it names no change.

### Snooze a whole group

```http
PATCH /users/me/notification-preferences/groups/3f2b…c91a
{ "preferences": [ { "notification_type": "ALL", "muted_until": "2026-09-15T22:00:00Z" } ] }
```

`ALL` is sugar so a "Mute this group" button need not enumerate types; it is
never stored. It fans out to the group list (§3) on a group endpoint and to the
global list on the global endpoint. Snoozes expire on their own — nothing needs
to clear them.

One body may name the same type twice (`ALL` to mute everything, then one type
to keep on): entries are folded to one write per type, later entry winning
field by field.

### Turn a type off everywhere

```http
PATCH /users/me/notification-preferences
{ "preferences": [ { "notification_type": "PRAYER_RECEIVED", "enabled": false } ] }
```

A global `false` plus a group `true` gives "none of these except from this one
group" — which is why `enabled` stays a real boolean rather than a tri-state.

### Reset a group to defaults

```http
DELETE /users/me/notification-preferences/groups/3f2b…c91a                          # all types
DELETE /users/me/notification-preferences/groups/3f2b…c91a?notification_type=EVENT  # one type
```

`204 No Content`. Deletes the group rows so resolution falls back to global;
deleting rows that do not exist is not an error.

---

## 6. Errors

| Status | Detail | Cause |
|--------|--------|-------|
| 401 | — | Missing or invalid bearer token |
| 404 | `You are not a member of this group` | Any group-scoped call for a group the caller has not joined |
| 422 | `unknown notification_type: …` | Not a member of the `NotificationType` enum (and not `ALL`) |
| 422 | `… is transactional and cannot be toggled` | `GROUP_INVITE` / `GROUP_JOIN_REQUEST` |
| 422 | `… has no per-group setting; set it globally instead` | A non-group-scoped type on a group endpoint |
| 422 | `muted_until must be in the future` | A snooze in the past, rather than a silently expired row |
| 422 | `… names no change; send enabled, muted_until, or both` | An entry with neither field |

`preferences` must hold at least one entry.

---

## 7. Where it is enforced

On the `PUSH` channel, before any push target is built:

- **Chat and prayer requests** resolve group-aware (a `GROUP` row beats the
  `GLOBAL` one) in `filter_users_by_notification_preference`.
- **Event, reminder, series and routine** fan-outs apply the global rows as a
  SQL predicate (`global_preference_blocks`) inside the recipient query.

A user whose preference is off, or whose snooze has not expired, is dropped
from the recipient list — the notification is never enqueued for them.
