# Verse of the Day — Likes & Comments API

Client-facing reference for like and comment endpoints on a **Verse of the Day**
(VOD) record. Implementation lives under
[`pecha_api/verse_of_day/`](../pecha_api/verse_of_day/) (`like_views.py`,
`comment_views.py`, `comment_like_views.py`).

All paths below are relative to the API root **`/api/v1`**.

**Replies and comment shape** follow the same conventions as
[public group post comments](../pecha_api/group_posts/comment_views.py):

- There is **no** separate “reply” URL. Replies are created with
  `POST /verse-of-day/{verse_id}/comments` and an optional `parent_comment_id`
  in the JSON body.
- `GET /verse-of-day/{verse_id}/comments` returns a **flat**, paginated list
  (newest first). Each item may include `parent_comment_id`; the client nests
  replies under their parent for threaded UI (same as group posts).

---

## Shared types

### Comment user (`VerseOfDayCommentUserDTO`)

| Field | Type | Notes |
|-------|------|-------|
| `first_name` | string | Display name; `"Unknown"` if user missing |
| `last_name` | string \| null | |
| `avatar_url` | string \| null | Presigned S3 URL when available |

### Comment (`VerseOfDayCommentDTO`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID | |
| `verse_id` | UUID | |
| `user_id` | UUID | Author |
| `parent_comment_id` | UUID \| null | Set on replies |
| `user` | object | See above |
| `text` | string | |
| `created_at` | string | ISO 8601 |
| `updated_at` | string \| null | ISO 8601 |
| `like_count` | integer | Default `0` |
| `liked_by_me` | boolean | Default `false`; set when caller is authenticated |

### Liker (`VerseOfDayLikerDTO` / `VerseOfDayCommentLikerDTO`)

| Field | Type | Notes |
|-------|------|-------|
| `user_id` | UUID | |
| `first_name` | string | |
| `last_name` | string \| null | |
| `avatar_url` | string \| null | Presigned when available |
| `created_at` | string | When the like was created (ISO 8601) |

---

## Verse likes

### 1. Get like summary

| Method | Path | Auth |
|--------|------|------|
| `GET` | `/verse-of-day/{verse_id}/likes` | Optional Bearer |

**Query:** none.

**Response `200`** — `VerseOfDayLikesResponse`:

```json
{
  "verse_id": "6a3c1d6e-2f0b-4a8e-9a57-0d6f1f3c2b11",
  "like_count": 5,
  "liked_by_me": false
}
```

With a valid token, `liked_by_me` reflects the caller. Invalid tokens are
ignored (same as optional auth elsewhere on this resource).

**Errors:** `404` if the verse does not exist.

---

### 2. List users who liked the verse

| Method | Path | Auth |
|--------|------|------|
| `GET` | `/verse-of-day/{verse_id}/likes/users` | Bearer **required** |

**Query:**

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `skip` | integer | `0` | `>= 0` |
| `limit` | integer | `20` | `1`–`100` |

**Response `200`** — `VerseOfDayLikersResponse`:

```json
{
  "likes": [
    {
      "user_id": "0b8f6c1e-7d5a-4f3e-8c2b-1a9e4d7f6c33",
      "first_name": "Pema",
      "last_name": null,
      "avatar_url": "https://…",
      "created_at": "2026-10-01T12:00:00+00:00"
    }
  ],
  "skip": 0,
  "limit": 20,
  "total": 5
}
```

Newest likes first.

**Errors:** `403` without auth; `404` if verse not found.

---

### 3. Like a verse

| Method | Path | Auth |
|--------|------|------|
| `POST` | `/verse-of-day/{verse_id}/likes` | Bearer **required** |

**Request body:** none.

**Response `201`** (new like) or **`200`** (already liked) —
`LikeVerseOfDayResponse`:

```json
{
  "verse_id": "6a3c1d6e-2f0b-4a8e-9a57-0d6f1f3c2b11",
  "user_id": "0b8f6c1e-7d5a-4f3e-8c2b-1a9e4d7f6c33",
  "liked": true,
  "like_count": 6,
  "created_at": "2026-10-06T09:00:00+00:00",
  "is_new": true
}
```

**Errors:** `401`/`403` auth; `404` verse not found.

---

### 4. Unlike a verse

| Method | Path | Auth |
|--------|------|------|
| `DELETE` | `/verse-of-day/{verse_id}/likes` | Bearer **required** |

**Request body:** none.

**Response `204`** — empty body. Idempotent if not liked.

**Errors:** `401`/`403` auth; `404` verse not found.

---

## Verse comments

### 5. List comments

| Method | Path | Auth |
|--------|------|------|
| `GET` | `/verse-of-day/{verse_id}/comments` | Optional Bearer |

**Query:**

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `skip` | integer | `0` | `>= 0` |
| `limit` | integer | `20` | `1`–`100` |

**Response `200`** — `VerseOfDayCommentsResponse`:

```json
{
  "comments": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "verse_id": "6a3c1d6e-2f0b-4a8e-9a57-0d6f1f3c2b11",
      "user_id": "0b8f6c1e-7d5a-4f3e-8c2b-1a9e4d7f6c33",
      "parent_comment_id": null,
      "user": {
        "first_name": "Karma",
        "last_name": "L",
        "avatar_url": "https://…"
      },
      "text": "ok, good",
      "created_at": "2026-10-06T07:00:00+00:00",
      "updated_at": null,
      "like_count": 12,
      "liked_by_me": false
    }
  ],
  "skip": 0,
  "limit": 20,
  "total": 2
}
```

Use `total` for headers such as “Comments – 2”. Thread replies in the client
by grouping items with the same `parent_comment_id` (flat feed, same as group
post comments).

**Errors:** `404` if verse not found.

---

### 6. Create comment or reply

| Method | Path | Auth |
|--------|------|------|
| `POST` | `/verse-of-day/{verse_id}/comments` | Bearer **required** |

**Request body** — `CreateVerseOfDayCommentRequest`:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `text` | string | **yes** | Trimmed; non-empty; max 5000 chars |
| `parent_comment_id` | UUID | no | Reply target; must belong to this verse |

**Example (top-level comment):**

```json
{ "text": "What do you think of this?" }
```

**Example (reply):**

```json
{
  "text": "I agree.",
  "parent_comment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Response `201`** — `VerseOfDayCommentDTO` (same shape as list items).

**Errors:**

| Status | When |
|--------|------|
| `404` | Verse not found, or `parent_comment_id` not on this verse |
| `422` | Empty/invalid `text` |
| `401`/`403` | Missing or invalid token |

---

### 7. Delete comment

| Method | Path | Auth |
|--------|------|------|
| `DELETE` | `/verse-of-day/comments/{comment_id}` | Bearer **required** |

**Request body:** none.

**Response `204`** — empty body. Only the comment author may delete.

**Errors:** `404` comment or verse not found; `403` not the author.

---

## Comment likes

### 8. List users who liked a comment

| Method | Path | Auth |
|--------|------|------|
| `GET` | `/verse-of-day/comments/{comment_id}/likes/users` | Bearer **required** |

**Query:** `skip` (default `0`), `limit` (default `20`, max `100`).

**Response `200`** — `VerseOfDayCommentLikersResponse`:

```json
{
  "likes": [
    {
      "user_id": "0b8f6c1e-7d5a-4f3e-8c2b-1a9e4d7f6c33",
      "first_name": "Pema",
      "last_name": null,
      "avatar_url": "https://…",
      "created_at": "2026-10-06T08:00:00+00:00"
    }
  ],
  "skip": 0,
  "limit": 20,
  "total": 12
}
```

**Errors:** `403` without auth; `404` if comment/verse not found.

---

### 9. Like a comment

| Method | Path | Auth |
|--------|------|------|
| `POST` | `/verse-of-day/comments/{comment_id}/likes` | Bearer **required** |

**Request body:** none.

**Response `201`** or **`200`** — `LikeVerseOfDayCommentResponse`:

```json
{
  "comment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": "0b8f6c1e-7d5a-4f3e-8c2b-1a9e4d7f6c33",
  "liked": true,
  "like_count": 13,
  "created_at": "2026-10-06T09:05:00+00:00",
  "is_new": true
}
```

**Errors:** `401`/`403` auth; `404` comment/verse not found.

---

### 10. Unlike a comment

| Method | Path | Auth |
|--------|------|------|
| `DELETE` | `/verse-of-day/comments/{comment_id}/likes` | Bearer **required** |

**Request body:** none.

**Response `204`** — empty body. Idempotent.

**Errors:** `401`/`403` auth; `404` comment/verse not found.

---

## Quick reference

| # | Method | Path | Request | Response |
|---|--------|------|---------|----------|
| 1 | GET | `/verse-of-day/{verse_id}/likes` | — | `VerseOfDayLikesResponse` |
| 2 | GET | `/verse-of-day/{verse_id}/likes/users` | Query: `skip`, `limit` | `VerseOfDayLikersResponse` |
| 3 | POST | `/verse-of-day/{verse_id}/likes` | — | `LikeVerseOfDayResponse` |
| 4 | DELETE | `/verse-of-day/{verse_id}/likes` | — | `204` |
| 5 | GET | `/verse-of-day/{verse_id}/comments` | Query: `skip`, `limit` | `VerseOfDayCommentsResponse` |
| 6 | POST | `/verse-of-day/{verse_id}/comments` | `{ text, parent_comment_id? }` | `VerseOfDayCommentDTO` |
| 7 | DELETE | `/verse-of-day/comments/{comment_id}` | — | `204` |
| 8 | GET | `/verse-of-day/comments/{comment_id}/likes/users` | Query: `skip`, `limit` | `VerseOfDayCommentLikersResponse` |
| 9 | POST | `/verse-of-day/comments/{comment_id}/likes` | — | `LikeVerseOfDayCommentResponse` |
| 10 | DELETE | `/verse-of-day/comments/{comment_id}/likes` | — | `204` |
