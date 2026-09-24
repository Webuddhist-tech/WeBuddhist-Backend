# Accumulator System API Documentation

Complete API reference for the Accumulator system, enabling individual and group-based counting/tracking functionality (e.g., mantra recitations, practice sessions).

---

## Table of Contents

1. [Conceptual Overview](#conceptual-overview)
2. [Data Models](#data-models)
3. [Individual Accumulator APIs](#individual-accumulator-apis)
4. [Group Accumulator APIs (User)](#group-accumulator-apis-user)
5. [App Integration Guide: Group Accumulation](#app-integration-guide-group-accumulation)
6. [CMS Accumulator Preset APIs](#cms-accumulator-preset-apis)
7. [CMS Group Accumulator APIs](#cms-group-accumulator-apis)
8. [Request/Response Schemas](#requestresponse-schemas)
9. [Common Workflows](#common-workflows)
10. [Error Handling](#error-handling)

---

## Conceptual Overview

### What is an Accumulator?

An **Accumulator** is a counter that tracks cumulative counts (e.g., mantra recitations, prostrations). The system supports two main use cases:

1. **Individual Accumulators** - Personal counters for a user's own practice
2. **Group Accumulators** - Shared counters where multiple group members contribute toward a collective goal

### Key Concepts

#### Presets vs User Accumulators

| Type | Description | Created By |
|------|-------------|------------|
| `PRESET` | Template accumulators available to all users. Users "tap" a preset to create their own copy. | CMS/Admin |
| `USER` | Personal accumulator created from a preset. Tracks individual progress. | User (from preset) |

#### Accumulator Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                        PRESET                                │
│  (Public template with mantra, target, mala image)          │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ User taps preset
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    USER ACCUMULATOR                          │
│  (Personal copy with own current_count, history)            │
│  - parent_id → links back to PRESET                         │
│  - user_id → owner                                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ Each count update
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  ACCUMULATOR HISTORY                         │
│  (Individual session records with count deltas)             │
└─────────────────────────────────────────────────────────────┘
```

#### Group Accumulator Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                      AUTHOR GROUP                            │
│  (Community/organization with members)                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ Group creates accumulator
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   GROUP ACCUMULATOR                          │
│  (Shared counter for group practice)                        │
│  - group_id → owning group                                  │
│  - accumulator_id → optional link to preset                 │
│  - target_count, start_date, end_date                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ Members contribute
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              GROUP ACCUMULATOR HISTORY                       │
│  (Per-user contribution records)                            │
│  - user_id → contributor                                    │
│  - count → delta contributed                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ User explicitly joins
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              GROUP ACCUMULATOR JOIN                          │
│  (Tracks who opted in to a group accumulator)               │
│  - user_id → participant                                    │
│  - created_at → join timestamp                              │
└─────────────────────────────────────────────────────────────┘
```

### Mala Images

A **Mala Image** is a visual representation (bead counter image) that can be associated with an accumulator. Users can customize their accumulator's mala image from a catalog.

### Metadata

Accumulators support **multi-language metadata** with `name` and `description` fields per language code (e.g., `EN`, `BO`, `ZH`).

---

## Data Models

### Accumulator

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `user_id` | UUID? | Owner (null for presets) |
| `group_id` | UUID? | Associated group (if any) |
| `parent_id` | UUID? | Preset this was created from (null for presets) |
| `type` | enum | `preset` or `user_created` |
| `target_count` | int? | Goal count (optional) |
| `current_count` | int | Current accumulated count |
| `text_id` | UUID? | Associated text (optional) |
| `mantra_id` | UUID? | Associated mantra (optional) |
| `mala_image` | UUID? | Chosen mala image ID |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last update timestamp |
| `deleted_at` | datetime? | Soft delete timestamp |

### AccumulatorHistory

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `accumulator_id` | UUID | Parent accumulator |
| `user_id` | UUID | User who made this entry |
| `count` | int | Count delta (always positive) |
| `created_at` | datetime | Session timestamp |

### GroupAccumulator

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `accumulator_id` | UUID? | Linked preset (optional) |
| `group_id` | UUID | Owning group |
| `title` | string? | Display title |
| `image_key` | string? | S3 key for cover image |
| `target_count` | int? | Group goal |
| `start_date` | datetime? | Practice period start |
| `end_date` | datetime? | Practice period end |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last update timestamp |
| `deleted_at` | datetime? | Soft delete timestamp |

### GroupAccumulatorMetadata

Per-language About text for a group accumulator. Unlike [AccumulatorMetadata](#metadata) there is no `name` — the group accumulator carries its own `title`.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `group_accumulator_id` | UUID | Owning group accumulator (cascade delete) |
| `description` | string? | About text for this language |
| `language` | enum | `EN`/`BO`/`ZH`/`HI`/`NE`/`MN`/`LA`, unique per accumulator |

### GroupAccumulatorLink

Links a group shares on its accumulator page. `link_type` and `video_id` are derived server-side from the URL and are never sent by the client.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `group_accumulator_id` | UUID | Owning group accumulator (cascade delete) |
| `url` | string | Any valid http/https URL |
| `link_type` | enum | `YOUTUBE` when a YouTube video id can be extracted, else `LINK` |
| `video_id` | string? | YouTube video id; null when `link_type` is `LINK` |
| `title` | string? | Display title |
| `display_order` | int | Ordering, assigned from the request array index |
| `created_at` / `created_by` / `updated_at` / `updated_by` | | Audit fields |

> **Rendering note**: only `YOUTUBE` links play inline (the app already ships `youtube_player_flutter`). `LINK` entries — Vimeo, Instagram Reels, Facebook video, articles — have no mobile-embeddable player and are rendered as cards that open externally.

> **`text_id` note**: `GroupAccumulator` does not store `text_id` directly. When `accumulator_id` is set, it points at a preset `Accumulator` row, and presets now carry their own `text_id` (UUID, added alongside `mantra_id` — see [Accumulator](#accumulator) below) linking the practice to a recitation text. To resolve which text a group accumulator practices, read `accumulator_id` off the group accumulator response, then fetch `GET /accumulators/{accumulator_id}` (or `GET /accumulators/presets`) and read `text_id` off that preset. See [Resolving `text_id` for a group accumulator](#resolving-text_id-for-a-group-accumulator) for the full flow.

### GroupAccumulatorJoin

| Field | Type | Description |
|-------|------|-------------|
| `group_accumulator_id` | UUID | Group accumulator the user joined |
| `user_id` | UUID | Joined user |
| `created_at` | datetime | When the user joined |

### GroupAccumulatorHistory

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `group_accumulator_id` | UUID | Parent group accumulator |
| `user_id` | UUID | Contributing user |
| `count` | int | Count delta contributed |
| `created_at` | datetime | Contribution timestamp |

---

## Individual Accumulator APIs

Base path: `/accumulators`

### GET /accumulators/presets

List all public preset accumulators available for users to add.

**Authentication**: Not required

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 20 | Max records (1-100) |
| `language` | string? | - | Language code for mantra content (e.g., `en`, `bo`) |
| `search` | string? | - | Filter by mantra text, title, or pronunciation |
| `show_recitations` | bool | `false` | When `false`, exclude presets that have a `text_id`. When `true`, include text-linked (recitation) presets |

There is no separate preset “type” for recitations — a preset is recitation-linked when `text_id` is set. Default listing preserves the previous mantra-only catalog behavior.

**Response**: `PublicAccumulatorsResponse`

```json
{
  "accumulators": [
    {
      "id": "uuid",
      "group_id": null,
      "type": "preset",
      "target_count": 100000,
      "current_count": 0,
      "text_id": null,
      "mantra": {
        "id": "uuid",
        "mantra": "ཨོཾ་མ་ཎི་པདྨེ་ཧཱུྃ།",
        "title": "Six-Syllable Mantra",
        "pronunciation": "Om Mani Padme Hum",
        "audio_url": "https://...",
        "mala_image_id": "uuid",
        "mala_image_url": "https://presigned-s3-url..."
      },
      "mala_image_id": "uuid",
      "mala_image_url": "https://presigned-s3-url...",
      "metadata": [
        {
          "language": "EN",
          "name": "Chenrezig Mantra",
          "description": "The mantra of compassion"
        }
      ],
      "created_at": "2024-01-15T10:00:00Z",
      "updated_at": "2024-01-15T10:00:00Z"
    }
  ],
  "total": 50,
  "skip": 0,
  "limit": 20
}
```

---

### GET /accumulators/user

List the authenticated user's personal accumulators.

**Authentication**: Required (Bearer token)

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 20 | Max records (1-100) |

**Response**: `AccumulatorsResponse`

```json
{
  "accumulators": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "group_id": null,
      "parent_id": "preset-uuid",
      "type": "user_created",
      "target_count": 100000,
      "current_count": 1250,
      "text_id": null,
      "mantra_id": "uuid",
      "mala_image_id": "uuid",
      "mala_image_url": "https://presigned-s3-url...",
      "metadata": [...],
      "created_at": "2024-01-20T08:00:00Z",
      "updated_at": "2024-01-25T14:30:00Z"
    }
  ],
  "total": 5,
  "skip": 0,
  "limit": 20
}
```

---

### POST /accumulators/user

Create a personal accumulator from a preset. The preset's fields are copied to the new user accumulator.

**Authentication**: Required (Bearer token)

**Request Body**: `CreateAccumulatorRequest`

```json
{
  "parent_id": "preset-uuid"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `parent_id` | UUID | Yes | ID of the preset to create from |

**Response**: `201 Created` - `AccumulatorDTO`

```json
{
  "id": "new-uuid",
  "user_id": "user-uuid",
  "group_id": null,
  "parent_id": "preset-uuid",
  "type": "user_created",
  "target_count": 100000,
  "current_count": 0,
  "text_id": null,
  "mantra_id": "uuid",
  "mala_image_id": "uuid",
  "mala_image_url": "https://presigned-s3-url...",
  "metadata": [...],
  "created_at": "2024-01-25T10:00:00Z",
  "updated_at": "2024-01-25T10:00:00Z"
}
```

**Errors**:
- `404 NOT_FOUND` - Preset not found
- `409 CONFLICT` - User already has an accumulator from this preset

---

### PUT /accumulators/user/{accumulator_id}

Update a user's accumulator. When `current_count` increases, a history entry is automatically created.

**Authentication**: Required (Bearer token)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `accumulator_id` | UUID | Accumulator to update |

**Request Body**: `UpdateAccumulatorRequest`

```json
{
  "current_count": 1350,
  "target_count": 200000,
  "text_id": "uuid",
  "mantra_id": "uuid"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `current_count` | int | No | New absolute count (must be >= 0) |
| `target_count` | int | No | New target goal |
| `text_id` | UUID | No | Associated text |
| `mantra_id` | UUID | No | Associated mantra |

**Response**: `AccumulatorDTO`

**Behavior**:
- If `current_count` increases, a history row is created with the delta
- If `current_count` decreases or stays same, no history is created
- User's daily stats cache is invalidated on count increase

**Errors**:
- `404 NOT_FOUND` - Accumulator not found
- `403 FORBIDDEN` - Not owner or not a user-created accumulator

---

### DELETE /accumulators/user/{accumulator_id}

Soft-delete a user's accumulator. History is preserved for the user's history page.

**Authentication**: Required (Bearer token)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `accumulator_id` | UUID | Accumulator to delete |

**Response**: `204 No Content`

**Errors**:
- `404 NOT_FOUND` - Accumulator not found
- `403 FORBIDDEN` - Not owner or not a user-created accumulator

---

### PUT /accumulators/user/{accumulator_id}/mala-image

Update the mala image for an accumulator.

**Authentication**: Required (Bearer token)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `accumulator_id` | UUID | Accumulator to update |

**Request Body**: `UpdateMalaImageRequest`

```json
{
  "mala_image_id": "mala-image-uuid"
}
```

**Response**: `AccumulatorDTO`

**Errors**:
- `404 NOT_FOUND` - Accumulator or mala image not found
- `403 FORBIDDEN` - Not owner

---

### GET /accumulators/user/history

Get the authenticated user's accumulator history across all their accumulators.

**Authentication**: Required (Bearer token)

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 20 | Max records (1-100) |

**Response**: `AccumulatorHistoryResponse`

```json
{
  "accumulators": [
    {
      "accumulator_id": "uuid",
      "parent_id": "preset-uuid",
      "target_count": 100000,
      "current_count": 1350,
      "total_counted": 1350,
      "mala_image_id": "uuid",
      "mala_image_url": "https://presigned-s3-url...",
      "metadata": [...],
      "sessions": [
        {
          "count": 108,
          "created_at": "2024-01-25T14:30:00Z"
        },
        {
          "count": 108,
          "created_at": "2024-01-24T09:15:00Z"
        }
      ]
    }
  ],
  "total": 5,
  "skip": 0,
  "limit": 20
}
```

---

### GET /accumulators/{parent_id}

Get the user's accumulator for a specific preset, with full session history. **Creates the accumulator if it doesn't exist.**

**Authentication**: Required (Bearer token)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `parent_id` | UUID | Preset ID |

**Response**: `AccumulatorHistoryDTO`

```json
{
  "accumulator_id": "uuid",
  "parent_id": "preset-uuid",
  "target_count": 100000,
  "current_count": 1350,
  "total_counted": 1350,
  "mala_image_id": "uuid",
  "mala_image_url": "https://presigned-s3-url...",
  "metadata": [...],
  "sessions": [
    {
      "count": 108,
      "created_at": "2024-01-25T14:30:00Z"
    }
  ]
}
```

**Behavior**:
- If user has no accumulator for this preset, one is automatically created
- Returns the accumulator with all session history

**Errors**:
- `404 NOT_FOUND` - Preset not found

---

### GET /accumulators/{accumulator_id}/groups

Get all active group accumulators linked to a preset accumulator, with the authenticated user's **lifetime** contribution count for each.

**Authentication**: Required (Bearer token)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `accumulator_id` | UUID | Accumulator (preset) ID |

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 20 | Max records (1-100) |
| `joined_only` | bool | `false` | When `true`, return only group accumulators in groups the authenticated user has joined |

**Response**: `AccumulatorGroupsResponse`

```json
{
  "groups": [
    {
      "group_accumulator_id": "uuid",
      "group_id": "uuid",
      "title": "100 Million Mani Retreat",
      "image_key": "groups/abc123/cover.jpg",
      "target_count": 100000000,
      "user_total_count": 5400,
      "start_date": "2024-01-01T00:00:00Z",
      "end_date": "2024-12-31T23:59:59Z",
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "total": 3,
  "skip": 0,
  "limit": 20
}
```

**Notes**:
- By default returns every active group accumulator that uses this preset.
- Pass `joined_only=true` to return only group accumulators in groups the user has joined (single call — no need to fetch `/users/me/joined/author/groups` separately).
- `user_total_count` is the sum of that user's history rows for each group accumulator (0 if they never contributed).

**Example — user's joined group practices only**:

```
GET /accumulators/{accumulator_id}/groups?joined_only=true
Authorization: Bearer {token}
```

---

## Group Accumulator APIs (User)

Base path: `/group-accumulators`

These endpoints are for regular users participating in group practices.

### GET /group-accumulators/{group_id}/accumulators

List all active group accumulators for a specific group.

**Authentication**: Not required

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_id` | UUID | Group ID |

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 20 | Max records (1-100) |

**Response**: `GroupAccumulatorsResponse`

```json
{
  "accumulators": [
    {
      "id": "uuid",
      "accumulator_id": "preset-uuid",
      "group_id": "uuid",
      "title": "100 Million Mani Retreat",
      "image": {
        "thumbnail": "https://presigned-s3-url.../thumb.jpg",
        "medium": "https://presigned-s3-url.../medium.jpg",
        "original": "https://presigned-s3-url.../original.jpg"
      },
      "image_key": "groups/abc123/cover.jpg",
      "target_count": 100000000,
      "start_date": "2024-01-01T00:00:00Z",
      "end_date": "2024-12-31T23:59:59Z",
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-15T10:00:00Z"
    }
  ],
  "total": 2,
  "skip": 0,
  "limit": 20
}
```

**App usage**: Call this when opening a group page to populate the list of group accumulations/practices available in that group.

**Note**: `accumulator_id` (renamed `preset_accumulator_id` in some responses — see [GroupAccumulatorDTO](#groupaccumulatordto)) is the only pointer back to the preset. It does not itself carry `text_id`; fetch the preset (`GET /accumulators/{accumulator_id}`) to read `text_id` if the client needs to deep-link into the practiced text.

---

### GET /group-accumulators/{group_accumulator_id}

Get details of a specific group accumulator, including lifetime and today totals.

**Authentication**: Optional (Bearer token — when provided, includes `user_total_count` and `user_today_count`)

**Headers**:
| Header | Required | Description |
|--------|----------|-------------|
| `X-Timezone` | No | IANA timezone for today counts (e.g. `Asia/Kathmandu`). Defaults to UTC. |

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_accumulator_id` | UUID | Group accumulator ID |

**Query Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `language` | string? | Language code for the About `description`. Falls back to `EN`, then `null`. |

**Response**: `GroupAccumulatorDetailDTO`

```json
{
  "id": "uuid",
  "accumulator_id": "preset-uuid",
  "group_id": "uuid",
  "title": "100 Million Mani Retreat",
  "image": {
    "thumbnail": "https://presigned-s3-url.../thumb.jpg",
    "medium": "https://presigned-s3-url.../medium.jpg",
    "original": "https://presigned-s3-url.../original.jpg"
  },
  "image_key": "groups/abc123/cover.jpg",
  "target_count": 100000000,
  "start_date": "2024-01-01T00:00:00Z",
  "end_date": "2024-12-31T23:59:59Z",
  "description": "We are holding this accumulation for the benefit of all beings...",
  "links": [
    {
      "id": "uuid",
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "link_type": "YOUTUBE",
      "video_id": "dQw4w9WgXcQ",
      "title": "Beyond the verse of today's practice",
      "display_order": 0
    }
  ],
  "total_count": 45678900,
  "total_today_count": 5400,
  "user_total_count": 1080,
  "user_today_count": 216,
  "member_count": 128,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-06-15T10:00:00Z"
}
```

| Field | Description |
|-------|-------------|
| `total_count` | Overall **lifetime** count — sum of all history deltas from every user |
| `total_today_count` | Overall **today** count in the request timezone |
| `user_total_count` | Authenticated user's lifetime count (`null` when unauthenticated) |
| `user_today_count` | Authenticated user's today count (`null` when unauthenticated) |
| `member_count` | Number of users who joined this group accumulator |
| `image` | Presigned URLs for thumbnail, medium, and original sizes (`null` when no image) |
| `description` | About text resolved for the requested `language`, falling back to `EN` then `null` |
| `links` | Ordered links for the About tab, sorted by `display_order`; `[]` when none |

---

### POST /group-accumulators/{group_accumulator_id}/join

Join a group accumulator. Also joins the parent community group automatically if the user is not already a member.

**Authentication**: Required (Bearer token)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_accumulator_id` | UUID | Group accumulator ID |

**Response**: `204 No Content`

**Behavior**:
- Creates a row in `group_accumulator_joins` (idempotent — safe to call again).
- Calls `upsert_group_join` on the parent group so the user becomes a group member.
- Only allowed for **public community groups** (`group_type = COMMUNITY`).

**Errors**:
- `404 NOT_FOUND` - Group accumulator or group not found
- `403 FORBIDDEN` - Group does not support joining (non-community group)

**App usage**: Call this before submitting counts. Users must join the group accumulator first.

---

### POST /group-accumulators/{group_accumulator_id}

Submit a count contribution to a group accumulator. User must have **joined the group accumulator** first.

**Authentication**: Required (Bearer token)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_accumulator_id` | UUID | Group accumulator ID |

**Request Body**: `SubmitGroupCountRequest`

```json
{
  "current_count": 5508
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `current_count` | int | Yes | User's new absolute total count for this group accumulator (>= 0) |

**Response**: `GroupAccumulatorHistoryItemDTO`

**Status Codes**:
- `201 Created` - New history entry created (count increased)
- `200 OK` - No change (count stayed same or decreased)

```json
{
  "id": "history-uuid",
  "user_id": "user-uuid",
  "count": 108,
  "created_at": "2024-01-25T14:30:00Z"
}
```

**Behavior**:
- Calculates delta from the user's previous lifetime total for this group accumulator.
- Only creates a history entry if delta > 0.
- Returns `id: null` and `count: 0` if no history was created.
- Send the user's **absolute** running total (same pattern as personal accumulators), not the delta.

**Errors**:
- `404 NOT_FOUND` - Group accumulator not found
- `403 FORBIDDEN` - User has not joined this group accumulator (`"You must join this group accumulator first"`)

**App usage**: After each counting session, POST the user's new absolute total. The backend records only the positive delta.

---

### GET /group-accumulators/{group_accumulator_id}/history

Get paginated contribution history for a group accumulator.

**Authentication**: Not required

**Headers**:
| Header | Required | Description |
|--------|----------|-------------|
| `X-Timezone` | No | IANA timezone used for `today_only` filtering and `total_today_count`. Defaults to UTC. |

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_accumulator_id` | UUID | Group accumulator ID |

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 20 | Max records (1-100) |
| `today_only` | bool | `false` | When `true`, return only history entries from today in the request timezone |

**Response**: `GroupAccumulatorHistoryResponse`

```json
{
  "group_accumulator": {
    "id": "uuid",
    "accumulator_id": "preset-uuid",
    "group_id": "uuid",
    "title": "100 Million Mani Retreat",
    "image": {
      "thumbnail": "https://presigned-s3-url.../thumb.jpg",
      "medium": "https://presigned-s3-url.../medium.jpg",
      "original": "https://presigned-s3-url.../original.jpg"
    },
    "image_key": "groups/abc123/cover.jpg",
    "target_count": 100000000,
    "start_date": "2024-01-01T00:00:00Z",
    "end_date": "2024-12-31T23:59:59Z",
    "total_count": 45678900,
    "total_today_count": 5400,
    "member_count": 128,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-06-15T10:00:00Z"
  },
  "history": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "count": 108,
      "created_at": "2024-01-25T14:30:00Z"
    }
  ],
  "total": 42,
  "skip": 0,
  "limit": 20
}
```

**Example — today's history only**:

```
GET /group-accumulators/{group_accumulator_id}/history?today_only=true
X-Timezone: Asia/Kathmandu
```

When `today_only=true`:
- `history` contains only entries from the current calendar day in `X-Timezone`
- `total` is the count of today's history rows (for pagination)
- `group_accumulator.total_today_count` is the full sum of today's contributions (not limited by pagination)
- `group_accumulator.total_count` remains the lifetime total

**App usage**: Use `today_only=true` instead of client-side date filtering. Use the detail endpoint for today totals without fetching history.

---

### GET /group-accumulators/{group_accumulator_id}/members

List users who joined this group accumulator, including each member's lifetime and today contribution counts.

**Authentication**: Not required

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_accumulator_id` | UUID | Group accumulator ID |

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 20 | Max records (1-100) |

**Headers**:
| Header | Required | Description |
|--------|----------|-------------|
| `X-Timezone` | No | IANA timezone for `today_count` (e.g. `Asia/Kathmandu`). Defaults to UTC. |

**Response**: `GroupAccumulatorMembersResponse`

```json
{
  "members": [
    {
      "user_id": "uuid",
      "username": "practitioner",
      "fullname": "Jane Doe",
      "avatar_url": "https://presigned-s3-url...",
      "joined_at": "2024-01-10T08:00:00Z",
      "total_count": 5000,
      "today_count": 108
    }
  ],
  "member_count": 128,
  "total": 128,
  "skip": 0,
  "limit": 20
}
```

| Field | Description |
|-------|-------------|
| `members[].total_count` | Member's lifetime contribution total |
| `members[].today_count` | Member's contribution total for today in `X-Timezone` |
| `member_count` | Total number of users who joined this group accumulator |
| `total` | Pagination total (same as `member_count` for this endpoint) |

Members who joined but have not contributed yet appear with `total_count: 0` and `today_count: 0`.

---

### DELETE /group-accumulators/{group_accumulator_id}

Soft-delete (reset) a group accumulator. Requires the user to be a member of the parent group.

**Authentication**: Required (Bearer token)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_accumulator_id` | UUID | Group accumulator ID |

**Response**: `204 No Content`

**Behavior**:
- Sets `deleted_at` on the group accumulator — it disappears from active lists.
- **History rows are preserved** in the database so per-user and overall lifetime totals can still be calculated from history when needed.
- This is a reset/hide of the active practice, not a hard delete of contribution data.

**Errors**:
- `404 NOT_FOUND` - Group accumulator not found
- `403 FORBIDDEN` - User is not a member of the group

---

## App Integration Guide: Group Accumulation

Step-by-step guide for mobile/web clients implementing group accumulation features.

All paths below are relative to `/api/v1`.

### 1. Load group accumulations for a group page

When the user opens a group, fetch its active practices:

```
GET /group-accumulators/{group_id}/accumulators
```

Use each item's `id`, `title`, `image`, `target_count`, `start_date`, and `end_date` to render the list.

---

### 2. Display a single group accumulator detail page

The detail page should show **image**, **title**, user counts, and overall counts in a single authenticated call:

```
GET /group-accumulators/{group_accumulator_id}
Authorization: Bearer {token}
X-Timezone: Asia/Kathmandu
```

| UI label | Response field |
|----------|----------------|
| Cover image | `image.medium` |
| Title | `title` |
| My count today | `user_today_count` |
| My count lifetime | `user_total_count` |
| Group count today | `total_today_count` |
| Group count lifetime | `total_count` |
| Participants | `member_count` |

Send `X-Timezone` with the user's IANA timezone so today counts match their local calendar day. Omit the auth header for public view (user counts will be `null`).

To list today's individual contributions:

```
GET /group-accumulators/{group_accumulator_id}/history?today_only=true
X-Timezone: Asia/Kathmandu
```

---

### 3. List groups for a preset — show only joined groups

When viewing a personal accumulator/preset, show which group practices the user participates in with a single call:

```
GET /accumulators/{accumulator_id}/groups?joined_only=true
Authorization: Bearer {token}
```

Returns only group accumulators whose parent group the user has joined, each with `user_total_count` (lifetime).

Each item includes `group_accumulator_id`, `group_id`, `title`, `image_key`, and `user_total_count`.

To list **all** groups using the preset (including ones the user has not joined), omit the parameter or pass `joined_only=false`.

---

### 4. Join a group accumulation

Before a user can push counts, they must join the group accumulator:

```
POST /group-accumulators/{group_accumulator_id}/join
Authorization: Bearer {token}
```

- Returns `204 No Content` on success.
- Idempotent — safe to call if already joined.
- Automatically joins the parent community group when needed.
- After joining, enable the counting UI and call `POST /group-accumulators/{id}` to submit counts.

**Suggested UX flow**

1. User taps "Join practice" → `POST .../join`
2. On `204`, show counting screen
3. On `403`, show "This group does not support joining"

---

### 5. Push a user's count to the group

After each counting session, send the user's new **absolute** total:

```
POST /group-accumulators/{group_accumulator_id}
Authorization: Bearer {token}
Content-Type: application/json

{ "current_count": 5508 }
```

| Response | Meaning |
|----------|---------|
| `201 Created` | Delta recorded; response includes the new history row |
| `200 OK` | No increase (`id: null`, `count: 0`) — count unchanged or decreased |
| `403 Forbidden` | User has not joined — call `POST .../join` first |

**Example session flow**

```
User's previous group total: 5400
User completes 108 more:       5508

POST { "current_count": 5508 }
→ 201 { "count": 108, ... }     // backend stored delta = 108
```

Keep the running total locally and always POST the absolute value, same as personal accumulators.

---

### 6. Reset a group accumulation (soft delete)

To reset/hide an active group practice while **keeping contribution history** for totals:

```
DELETE /group-accumulators/{group_accumulator_id}
Authorization: Bearer {token}
```

| Effect | Detail |
|--------|--------|
| Active list | Accumulator removed from `GET /group-accumulators/{group_id}/accumulators` |
| History | All `group_accumulator_history` rows remain in the database |
| Totals | Lifetime totals can still be computed by summing history rows |
| Re-create | CMS authors can create a new group accumulator for the same group/preset |

Requires the caller to be a member of the parent group. CMS authors can also reset via `DELETE /cms/groups/{group_id}/accumulators/{group_accumulator_id}`.

---

## CMS Accumulator Preset APIs

Base path: `/cms/accumulators/presets`

These endpoints let CMS authors manage the public preset catalog. Auth matches mantra create: any active CMS author (`validate_cms_author_details`).

Presets may optionally link a recitation text (`text_id`) and/or a mantra (`mantra_id`). At least one metadata entry with a name is required.

CMS list always includes text-linked presets (equivalent to public `show_recitations=true`). The public `GET /accumulators/presets` defaults to excluding them.

### GET /cms/accumulators/presets

List presets (CMS).

**Authentication**: Required (Bearer token - CMS author)

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 20 | Max records (1-100) |
| `search` | string | — | Filter by preset name/description or mantra text/title/pronunciation |
| `language` | string | — | Language for nested mantra content |

**Response**: `200 OK` - `PublicAccumulatorsResponse`

---

### GET /cms/accumulators/presets/{preset_id}

Get a single preset for editing.

**Authentication**: Required (Bearer token - CMS author)

**Response**: `200 OK` - `PublicAccumulatorDTO`

**Errors**:
- `404 NOT_FOUND` - Preset not found

---

### POST /cms/accumulators/presets

Create a public preset accumulator.

**Authentication**: Required (Bearer token - CMS author)

**Request Body**: `CreatePresetAccumulatorRequest`

```json
{
  "target_count": 100000,
  "text_id": "text-uuid",
  "mantra_id": "mantra-uuid",
  "mala_image_id": null,
  "metadata": [
    {
      "language": "EN",
      "name": "Chenrezig Practice",
      "description": "Compassion practice"
    }
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `target_count` | int | No | Suggested target (>= 1) |
| `text_id` | UUID | No | Linked OpenPecha text |
| `mantra_id` | UUID | No | Linked mantra |
| `mala_image_id` | UUID | No | Mala image from catalog |
| `metadata` | array | Yes | At least one entry; languages must be unique |

**Response**: `201 Created` - `PublicAccumulatorDTO`

**Errors**:
- `404 NOT_FOUND` - Invalid `text_id`, `mantra_id`, or `mala_image_id`
- `422` - Empty metadata or duplicate languages

---

### PUT /cms/accumulators/presets/{preset_id}

Update a public preset. Only provided fields are applied. When `metadata` is sent, it replaces all existing metadata rows.

**Authentication**: Required (Bearer token - CMS author)

**Request Body**: `UpdatePresetAccumulatorRequest` (all fields optional)

**Response**: `200 OK` - `PublicAccumulatorDTO`

**Errors**:
- `404 NOT_FOUND` - Preset not found, or invalid linked ids
- `403 FORBIDDEN` - Target is not a preset

---

### DELETE /cms/accumulators/presets/{preset_id}

Soft-delete a preset (`deleted_at`). Soft-deleted presets drop out of public and CMS lists.

**Authentication**: Required (Bearer token - CMS author)

**Response**: `204 No Content`

**Errors**:
- `404 NOT_FOUND` - Preset not found

---

## CMS Group Accumulator APIs

Base path: `/cms/groups`

These endpoints are for CMS authors/admins to manage group accumulators. Requires appropriate permissions.

### POST /cms/groups/{group_id}/accumulators

Create a new group accumulator.

**Authentication**: Required (Bearer token - CMS author with create permission)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_id` | UUID | Group ID |

**Request Body**: `CreateGroupAccumulatorRequest`

```json
{
  "accumulator_id": "preset-uuid",
  "title": "100 Million Mani Retreat 2024",
  "image_key": "groups/abc123/cover.jpg",
  "target_count": 100000000,
  "start_date": "2024-01-01T00:00:00Z",
  "end_date": "2024-12-31T23:59:59Z",
  "metadata": [
    { "language": "EN", "description": "We are holding this accumulation..." },
    { "language": "BO", "description": "..." }
  ],
  "links": [
    { "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Beyond the verse of today's practice" }
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `accumulator_id` | UUID | No | Link to a preset accumulator |
| `title` | string | No | Display title |
| `image_key` | string | No | S3 key for cover image (upload via CMS media flow) |
| `target_count` | int | No | Group goal (>= 1) |
| `start_date` | datetime | No | Practice period start |
| `end_date` | datetime | No | Practice period end |
| `metadata` | array | No | Per-language About text. Languages must be unique. |
| `links` | array | No | Ordered links; each entry takes `url` and optional `title`. Array index becomes `display_order`. |

> **Replace semantics**: `metadata` and `links` each replace the full set. Omitting a field (or sending `null`) leaves existing rows untouched; sending `[]` clears them. Row ids are regenerated on every save, so nothing should reference a metadata or link row by id.

**Response**: `201 Created` - `GroupAccumulatorDTO` (includes `metadata` and `links`)

**Errors**:
- `404 NOT_FOUND` - Group not found
- `403 FORBIDDEN` - Insufficient permissions
- `400 BAD_REQUEST` - A link URL is not a valid http/https URL
- `422 UNPROCESSABLE_ENTITY` - Duplicate `metadata` languages

---

### GET /cms/groups/{group_id}/accumulators

List all accumulators for a group (CMS view).

**Authentication**: Required (Bearer token - CMS author with read permission)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_id` | UUID | Group ID |

**Query Parameters**:
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip` | int | 0 | Pagination offset |
| `limit` | int | 20 | Max records (1-100) |

**Response**: `GroupAccumulatorsResponse`

---

### GET /cms/groups/{group_id}/accumulators/{group_accumulator_id}

Get a single group accumulator with total count.

**Authentication**: Required (Bearer token - CMS author with read permission)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_id` | UUID | Group ID |
| `group_accumulator_id` | UUID | Group accumulator ID |

**Response**: `GroupAccumulatorDetailDTO`

**Errors**:
- `404 NOT_FOUND` - Group accumulator not found
- `403 FORBIDDEN` - Accumulator doesn't belong to this group or insufficient permissions

---

### PUT /cms/groups/{group_id}/accumulators/{group_accumulator_id}

Update a group accumulator.

**Authentication**: Required (Bearer token - CMS author with status change permission)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_id` | UUID | Group ID |
| `group_accumulator_id` | UUID | Group accumulator ID |

**Request Body**: `UpdateGroupAccumulatorRequest`

```json
{
  "title": "Updated Title",
  "image_key": "groups/abc123/new-cover.jpg",
  "target_count": 200000000,
  "end_date": "2025-12-31T23:59:59Z",
  "metadata": [
    { "language": "EN", "description": "Updated about text..." }
  ],
  "links": [
    { "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Beyond the verse" },
    { "url": "https://vimeo.com/12345678", "title": "Teaching from the retreat" }
  ]
}
```

Same `metadata` / `links` replace semantics as the create endpoint above: omit to leave unchanged, `[]` to clear, otherwise the full set is replaced.

**Response**: `GroupAccumulatorDTO` (includes `metadata` and `links`)

**Errors**:
- `404 NOT_FOUND` - Group accumulator not found
- `403 FORBIDDEN` - Accumulator doesn't belong to this group or insufficient permissions
- `400 BAD_REQUEST` - A link URL is not a valid http/https URL
- `422 UNPROCESSABLE_ENTITY` - Duplicate `metadata` languages

---

### DELETE /cms/groups/{group_id}/accumulators/{group_accumulator_id}

Delete a group accumulator (soft delete).

**Authentication**: Required (Bearer token - CMS author with status change permission)

**Path Parameters**:
| Parameter | Type | Description |
|-----------|------|-------------|
| `group_id` | UUID | Group ID |
| `group_accumulator_id` | UUID | Group accumulator ID |

**Response**: `204 No Content`

**Errors**:
- `404 NOT_FOUND` - Group accumulator not found
- `403 FORBIDDEN` - Accumulator doesn't belong to this group or insufficient permissions

---

## Request/Response Schemas

### AccumulatorDTO

```typescript
interface AccumulatorDTO {
  id: string;                    // UUID
  user_id: string | null;        // UUID - owner (null for presets)
  group_id: string | null;       // UUID - associated group
  parent_id: string | null;      // UUID - preset this was created from
  type: "preset" | "user_created";
  target_count: number | null;   // Goal count
  current_count: number;         // Current accumulated count
  text_id: string | null;        // UUID - associated text
  mantra_id: string | null;      // UUID - associated mantra
  mala_image_id: string | null;  // UUID - chosen mala image
  mala_image_url: string | null; // Presigned S3 URL
  metadata: AccumulatorMetadataDTO[];
  created_at: string;            // ISO datetime
  updated_at: string | null;     // ISO datetime
}
```

### PublicAccumulatorDTO

```typescript
interface PublicAccumulatorDTO {
  id: string;                    // UUID - use as parent_id when creating
  group_id: string | null;       // UUID
  type: "preset" | "user_created";
  target_count: number | null;
  current_count: number;
  text_id: string | null;        // UUID
  mantra: PresetMantraDTO | null;
  mala_image_id: string | null;  // UUID
  mala_image_url: string | null; // Presigned S3 URL
  metadata: AccumulatorMetadataDTO[];
  created_at: string;            // ISO datetime
  updated_at: string | null;     // ISO datetime
}
```

### PresetMantraDTO

```typescript
interface PresetMantraDTO {
  id: string;                    // UUID
  mantra: string;                // Mantra text
  title: string | null;          // Display title
  pronunciation: string | null;  // Phonetic pronunciation
  audio_url: string | null;      // Audio file URL
  mala_image_id: string | null;  // UUID
  mala_image_url: string | null; // Presigned S3 URL
}
```

### AccumulatorMetadataDTO

```typescript
interface AccumulatorMetadataDTO {
  language: "EN" | "BO" | "ZH" | string;  // Language code
  name: string;                            // Display name
  description: string | null;              // Description
}
```

### AccumulatorHistoryDTO

```typescript
interface AccumulatorHistoryDTO {
  accumulator_id: string;        // UUID
  parent_id: string | null;      // UUID - preset reference
  target_count: number | null;
  current_count: number;
  total_counted: number;         // Sum of all history entries
  mala_image_id: string | null;  // UUID
  mala_image_url: string | null; // Presigned S3 URL
  metadata: AccumulatorMetadataDTO[];
  sessions: AccumulatorSessionDTO[];
}
```

### AccumulatorSessionDTO

```typescript
interface AccumulatorSessionDTO {
  count: number;                 // Count delta for this session
  created_at: string;            // ISO datetime
}
```

### GroupAccumulatorDTO

```typescript
interface ImageUrlModel {
  thumbnail: string;
  medium: string;
  original: string;
}

interface GroupAccumulatorDTO {
  id: string;                    // UUID
  accumulator_id: string | null; // UUID - linked preset
  group_id: string;              // UUID - owning group
  title: string | null;          // Display title
  image: ImageUrlModel | null;   // Presigned cover image URLs
  image_key: string | null;      // S3 key for cover image
  target_count: number | null;   // Group goal
  start_date: string | null;     // ISO datetime
  end_date: string | null;       // ISO datetime
  created_at: string;            // ISO datetime
  updated_at: string | null;     // ISO datetime
}
```

### GroupAccumulatorDetailDTO

```typescript
interface GroupAccumulatorDetailDTO extends GroupAccumulatorDTO {
  total_count: number;           // Overall lifetime sum of all contributions
  total_today_count: number;     // Overall today sum in request timezone
  user_total_count: number | null; // Authenticated user's lifetime count
  user_today_count: number | null; // Authenticated user's today count
  member_count: number;          // Users who joined this group accumulator
}
```

### GroupAccumulatorHistoryItemDTO

```typescript
interface GroupAccumulatorHistoryItemDTO {
  id: string | null;             // UUID - null if no history created
  user_id: string;               // UUID - contributor
  count: number;                 // Count delta
  created_at: string;            // ISO datetime
}
```

### GroupAccumulatorMemberDTO

```typescript
interface GroupAccumulatorMemberDTO {
  user_id: string;               // UUID
  username: string | null;
  fullname: string;
  avatar_url: string | null;     // Presigned S3 URL
  joined_at: string;             // ISO datetime
  total_count: number;           // Lifetime contribution count
  today_count: number;           // Today's contribution count in request timezone
}
```

### GroupAccumulatorMembersResponse

```typescript
interface GroupAccumulatorMembersResponse {
  members: GroupAccumulatorMemberDTO[];
  member_count: number;          // Total users who joined
  total: number;                 // Pagination total (same as member_count)
  skip: number;
  limit: number;
}
```

### AccumulatorGroupDTO

```typescript
interface AccumulatorGroupDTO {
  group_accumulator_id: string;  // UUID
  group_id: string;              // UUID
  title: string | null;
  image_key: string | null;      // S3 key for cover image
  target_count: number | null;
  user_total_count: number;      // Authenticated user's lifetime contribution
  start_date: string | null;     // ISO datetime
  end_date: string | null;       // ISO datetime
  created_at: string;            // ISO datetime
}
```

---

## Common Workflows

### Workflow 1: User Starts Personal Practice

```
1. App displays preset list
   GET /accumulators/presets?language=en

2. User taps a preset to start practicing
   GET /accumulators/{preset_id}
   → Auto-creates user accumulator if needed
   → Returns accumulator with session history

3. User completes a counting session (e.g., 108 recitations)
   PUT /accumulators/user/{accumulator_id}
   Body: { "current_count": 108 }
   → History entry created with count=108

4. User continues practicing over time
   PUT /accumulators/user/{accumulator_id}
   Body: { "current_count": 216 }
   → History entry created with count=108 (delta)

5. User views their practice history
   GET /accumulators/user/history
```

### Workflow 2: User Joins and Contributes to Group Practice

```
1. App displays group's accumulators
   GET /group-accumulators/{group_id}/accumulators

2. User joins a group accumulator
   POST /group-accumulators/{group_accumulator_id}/join
   → Also joins parent community group if needed

3. User views detail page (authenticated)
   GET /group-accumulators/{group_accumulator_id}
   GET /accumulators/{accumulator_id}/groups
   GET /group-accumulators/{group_accumulator_id}/history
   → Show title, image, user lifetime/today, overall lifetime/today

4. User contributes their count
   POST /group-accumulators/{group_accumulator_id}
   Body: { "current_count": 5400 }
   → Creates history entry with delta
   → Returns 201 if new entry, 200 if no change

5. User views contribution history
   GET /group-accumulators/{group_accumulator_id}/history
```

### Workflow 3: CMS Author Creates Group Accumulator

```
1. Author authenticates via CMS

2. Author creates group accumulator for community practice
   POST /cms/groups/{group_id}/accumulators
   Body: {
     "accumulator_id": "preset-uuid",
     "title": "100 Million Mani Retreat 2024",
     "target_count": 100000000,
     "start_date": "2024-01-01T00:00:00Z",
     "end_date": "2024-12-31T23:59:59Z"
   }

3. Author monitors progress
   GET /cms/groups/{group_id}/accumulators/{id}
   → Shows total_count from all members

4. Author updates target or dates as needed
   PUT /cms/groups/{group_id}/accumulators/{id}
   Body: { "target_count": 200000000 }
```

### Workflow 4: User Checks Groups Using Their Preset

```
1. User has been practicing a specific mantra/preset

2. Fetch group practices linked to this preset (joined groups only)
   GET /accumulators/{accumulator_id}/groups?joined_only=true
   → Includes user_total_count (lifetime) per group

3. Optionally open a group accumulator detail
   GET /group-accumulators/{group_accumulator_id}
```

### Workflow 5: Reset a Group Accumulator

```
1. User (group member) or CMS author resets the practice
   DELETE /group-accumulators/{group_accumulator_id}
   — or —
   DELETE /cms/groups/{group_id}/accumulators/{group_accumulator_id}

2. Accumulator disappears from active lists

3. History rows remain — lifetime totals can still be calculated from history
```

---

## Error Handling

### Error Response Format

All errors follow this structure:

```json
{
  "detail": {
    "error": "ERROR_CODE",
    "message": "Human-readable message"
  }
}
```

### Common Error Codes

| HTTP Status | Error Code | Description |
|-------------|------------|-------------|
| 400 | `BAD_REQUEST` | Invalid request data |
| 403 | `FORBIDDEN` | Insufficient permissions |
| 404 | `NOT_FOUND` | Resource not found |
| 409 | `CONFLICT` | Resource already exists |

### Specific Error Messages

| Context | Message |
|---------|---------|
| Accumulator not found | "Accumulator not found" |
| Preset not found | "Preset not found" |
| Mantra not found | "Mantra not found" |
| Mala image not found | "Mala image not found" |
| Group not found | "Group not found" |
| Group accumulator not found | "Group accumulator not found" |
| Not owner | "You are not allowed to update this accumulator" |
| Not user accumulator | "Only user-created accumulators can be updated" |
| Duplicate accumulator | "Accumulator already exists for this preset" |
| Not group member | "You must be a member of this group" |
| Not joined group accumulator | "You must join this group accumulator first" |
| Group join not allowed | "This group does not support joining" |
| Wrong group | "Group accumulator does not belong to this group" |

---

## Notes for Frontend Developers

1. **Presigned URLs**: `mala_image_url`, `image`, and `avatar_url` fields contain presigned S3 URLs that expire. Cache images locally but be prepared to refetch if loading fails.

2. **Count Updates**: Always send the absolute `current_count`, not the delta. The backend calculates the delta and creates history entries automatically.

3. **Auto-creation**: `GET /accumulators/{parent_id}` auto-creates a user accumulator if none exists. Use this for the "tap to start" flow.

4. **Group Accumulator Join**: Submitting counts (`POST /group-accumulators/{id}`) requires the user to join the group accumulator first (`POST /group-accumulators/{id}/join`). Handle 403 with a join prompt.

5. **Today vs Lifetime Counts**: Today totals are returned as `total_today_count` and `user_today_count` on the detail endpoint. Pass `X-Timezone` for the user's local calendar day. Use `GET /group-accumulators/{id}/history?today_only=true` to fetch only today's history rows (no client-side date filtering needed).

6. **Joined Groups Filter**: Use `GET /accumulators/{id}/groups?joined_only=true` to return only group accumulators in groups the user has joined. No separate call to `/users/me/joined/author/groups` is needed.

7. **Pagination**: All list endpoints support `skip` and `limit` parameters. Default limit is 20, max is 100.

8. **Language Parameter**: Use `language` query param on `/accumulators/presets` to get mantra content in the user's preferred language.

9. **Soft Deletes / Reset**: Deleting a group accumulator sets `deleted_at` and hides it from active lists. History rows are preserved so per-user and overall lifetime totals remain calculable.
