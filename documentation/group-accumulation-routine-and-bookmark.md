# Group accumulation: routine sessions & bookmarks

Group accumulations (`group_accumulators`) can now be added to a practice
routine and bookmarked, alongside personal accumulators.

Two new enum values, one per domain:

| Enum | New value |
| --- | --- |
| `SessionType` (routines) | `GROUP_ACCUMULATOR` |
| `BookmarkType` (bookmarks) | `GROUP_ACCUMULATOR` |

Each needs its own Postgres enum migration — `sessiontype` and `bookmark_type`
are separate types:

- `ga1b2c3d4e5f_add_group_accumulator_session_type.py`
- `gb1c2d3e4f5a_add_group_accumulator_bookmark_type.py`

---

## 1. Routine sessions

### Endpoints

Any endpoint that accepts a `sessions` array:

| Method | Path |
| --- | --- |
| POST | `/routines` |
| POST | `/routines/{routine_id}/time-blocks` |
| PUT | `/routines/{routine_id}/time-blocks/{time_block_id}` |

### Request

Send `group_accumulator_id` (or `source_id` — they resolve to each other, the
same way `accumulator_id` does):

```json
{
  "time": "08:00",
  "time_int": 800,
  "sessions": [
    {
      "session_type": "GROUP_ACCUMULATOR",
      "group_accumulator_id": "8f1c...",
      "display_order": 0
    }
  ]
}
```

### Response

`SessionDTO` returns `group_accumulator_id`, `title`, and `image`. `source_id`
and `accumulator_id` are omitted for this session type.

```json
{
  "id": "3ab9...",
  "session_type": "GROUP_ACCUMULATOR",
  "group_accumulator_id": "8f1c...",
  "title": "Group Mani",
  "image": { "thumbnail": "...", "medium": "...", "original": "..." },
  "display_order": 0
}
```

### Rules

| Condition | Status | Message |
| --- | --- | --- |
| No `group_accumulator_id`/`source_id` | 422 | `group_accumulator_id is required for GROUP_ACCUMULATOR sessions` |
| Same id twice in one time block | 422 | `A group accumulation can only appear once in a time block` |
| Unknown or soft-deleted id | 404 | `Group accumulator not found` |
| User has not joined it | 403 | `Join this group accumulation before adding it to your routine` |

**The user must join first — the routine does not auto-join.** Unlike `PLAN` and
`SERIES` sessions (which auto-enroll), joining a group accumulation runs its own
authorization in `join_group_accumulator_service`: the group must be published,
must allow joining, and a **private** group requires the join-request flow. Auto-
joining from the routine would bypass all three. Clients should send the user
through `POST /group-accumulators/{id}/join` first.

Dedup is **per time block**, matching `ACCUMULATOR` — not per routine, which is
the stricter rule used for the two recitation-collection types.

---

## 2. Bookmarks

### Create

```
POST /users/me/bookmarks
{ "type": "GROUP_ACCUMULATOR", "source_id": "<group_accumulator_id>" }
```

`source_id` must be a valid UUID.

### List

`GROUP_ACCUMULATOR` is **not** a `BookmarkFilterType` value. Group accumulations
list under the existing accumulation filter, and each bookmark's own `type`
tells them apart:

```
GET /users/me/bookmarks?type=ACCUMULATOR
```

returns both `ACCUMULATOR` and `GROUP_ACCUMULATOR` bookmarks. This mirrors the
existing `type=TEXT` filter, which returns both `TEXT` and `VERSE`.

Payload arrives under its own `group_accumulator` key (as
`group_recitation_collection` does), so a client renders one accumulation list
by reading whichever key `type` points at:

```json
{
  "id": "b12e...",
  "type": "GROUP_ACCUMULATOR",
  "source_id": "8f1c...",
  "group_accumulator": {
    "id": "8f1c...",
    "group_id": "44de...",
    "title": "Group Mani",
    "image": "https://..."
  }
}
```

### Visibility

Enrichment mirrors group-content read access: the group must be published, and
either public or the user is currently a member. Otherwise the enrichment
returns `{}` and the bookmark renders without a payload rather than leaking the
title.

Note this is *visibility*, not the join requirement the routine imposes — a user
can bookmark a group accumulation they have not joined.

---

## Not included

- No `GROUP_ACCUMULATOR` in `BookmarkFilterType` (deliberate — see above).
- Counts/progress are not returned on either the session or the bookmark DTO;
  clients read those from `/group-accumulators/{id}`.
- `documentation/routines-openapi.yaml` is stale and was not updated — its
  `SessionType` enum still lists only `PLAN` and `RECITATION`, missing the six
  types added since.
