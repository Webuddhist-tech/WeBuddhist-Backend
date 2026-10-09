# RFC: Group Assets, and Audio on Recitation Collection Items

| Field | Value |
|-------|-------|
| **Status** | Proposed |
| **Date** | 2026-09-14 |
| **Scope** | WeBuddhist-Backend (`pecha_api/group_assets/`, `pecha_api/group_recitation_collection/`), WeBuddhist-Studio |
| **Related** | [rfc-group-recitation-collections.md](./rfc-group-recitation-collections.md) (the feature this extends), `group_posts` media (the replace-ordered-set pattern this copies), `plan_item_audio` (the pattern this deliberately does *not* copy) |

---

## 1. Summary

Two layers, kept separate on purpose:

1. **A group asset library.** A group owns its files. An author uploads audio
   *to the group*, once, and it lands in that group's library under a
   group-scoped S3 prefix.
2. **A link from a recitation collection item to those assets.** Each text in a
   collection points at one or more audio assets from its group's library,
   in a chosen order.

So uploading and linking are different actions. Studio can offer "pick from
this group's audio" — the thing it cannot do today — and the same recording can
serve three collections without being uploaded three times.

## 2. Motivation

A recitation collection is a list of texts to chant. Today it is text only: a
member can read the Heart Sutra but not hear it. Groups want recordings, and
**more than one per text** — a fast and a slow version, a different chant
master, a different lineage's melody.

**Why a library instead of uploading straight onto the item.** `plan_item_audio`
took the direct route: the file is uploaded to a plan day and the row *is* the
attachment. Reusing a recording later meant bolting a second path on top —
`assign_plan_day_audio` re-links a raw `audio_key` string, the "library" Studio
browses (`get_cms_plan_audio_list`) is really just a listing of attachment rows,
and because two rows can now share one key, deleting one has to first count the
others (`count_plan_item_audio_by_audio_key`) to avoid pulling the file out from
under its twin. That is the shape you get when the library is discovered late.

A file that outlives any single attachment is an entity. Model it as one.

---

## 3. Data model

### 3.1 `group_assets` — the library

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | `uuid4` |
| `group_id` | UUID FK → `author_groups.id` ON DELETE CASCADE | The owner. Assets never cross groups |
| `asset_type` | ENUM `group_asset_type` NOT NULL | `AUDIO` in v1; `IMAGE` / `VIDEO` reserved so covers and post media can move here later |
| `title` | VARCHAR(255) NOT NULL | What Studio shows in the picker. Defaults to the uploaded file name |
| `s3_key` | VARCHAR(1000) NOT NULL | Presigned on read, never returned raw |
| `file_name` | VARCHAR(255) NOT NULL | Original name, for the picker's second line |
| `mime_type` | VARCHAR(64) NULL | |
| `file_size_bytes` | BIGINT NULL | |
| `duration_ms` | INTEGER NULL | Audio/video only |
| `created_at` / `created_by` | TIMESTAMPTZ NOT NULL / VARCHAR(255) NOT NULL | Author email, as elsewhere in this module |
| `updated_at` / `updated_by` | TIMESTAMPTZ NULL / VARCHAR(255) NULL | |
| `deleted_at` | TIMESTAMPTZ NULL | Soft delete — links point here, so rows must not vanish |

**Indexes**

- `idx_group_assets_group_type` on `(group_id, asset_type)` — the picker query
- Partial unique `(group_id, s3_key)` WHERE `deleted_at IS NULL`

### 3.2 `group_recitation_collection_item_assets` — the link

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `item_id` | UUID FK → `group_recitation_collection_items.id` ON DELETE CASCADE | |
| `asset_id` | UUID FK → `group_assets.id` ON DELETE RESTRICT | A backstop, not the mechanism: assets are soft-deleted, so §5's check is what normally guards this. RESTRICT is there for the day someone hard-deletes a row by hand |
| `display_order` | INTEGER NOT NULL | 1-based, the order the app plays them in |
| `created_at` / `created_by` | TIMESTAMPTZ NOT NULL / VARCHAR(255) NOT NULL | |

**Constraints**

- `UNIQUE (item_id, asset_id)` — the same recording twice on one text is a mistake
- `UNIQUE (item_id, display_order)` — mirrors `uq_group_post_media_post_order`
- Index on `asset_id`, so "what uses this asset?" is cheap (§5)

No `deleted_at`: a link is a fact about the current state, and §4.2 replaces the
whole set atomically. The asset it points at holds the history.

### 3.3 Migration

One Alembic revision: the enum type, both tables, FKs, indexes, constraints.
`down_revision = "5fb87118f326"` (current head at time of writing).

Nothing to backfill — no group audio exists yet.

### 3.4 Decisions worth stating

**The link is item-scoped, not text-scoped.** The same `text_id` can sit in two
collections. Linking at the item means each collection curates its own
recordings — a beginners' collection and an advanced one can give the same sutra
different audio — while the *file* is still shared through the library. This is
what buys us both halves; see §11 for the case against.

**Assets are group-scoped, full stop.** No cross-group sharing, no "platform
library". A group's recordings are its own, the S3 prefix says so, and
permission checks stay a single `group_id` lookup.

**`group_assets` is its own module, not a table inside the recitation code.**
Covers (`img_url`), post media, and event images are all group-owned files that
want the same picker. v1 only fills it with audio and only the recitation
collection reads it, but nothing in the table is recitation-shaped.

---

## 4. API

### 4.1 The library — `/cms/author/groups/{group_id}/assets`

| Method | Path | Purpose | Status |
|--------|------|---------|--------|
| `POST` | `` | Upload a file into this group's library (multipart) | 201 |
| `GET` | `` | List/search the group's assets — the Studio picker | 200 |
| `PATCH` | `/{asset_id}` | Rename (`title`) | 200 |
| `DELETE` | `/{asset_id}` | Remove from the library | 204 / 409 |

#### `POST` — upload

`multipart/form-data`: `file` (required), `asset_type` (required, `AUDIO`),
`title` and `duration_ms` (optional).

One file per call: a failed third upload should not cost the user the first two.

S3 key: `groups/{group_id}/assets/audio/{uuid4}{ext}` — group-scoped, so an
asset's ownership is legible from the key alone, unlike today's
`audio/plan_days/...`.

**`201` — `GroupAssetDTO`**

```json
{
  "id": "uuid",
  "group_id": "uuid",
  "asset_type": "AUDIO",
  "title": "Heart Sutra — slow tempo",
  "file_name": "heart-sutra-slow.mp3",
  "asset_url": "https://presigned…",
  "mime_type": "audio/mpeg",
  "file_size_bytes": 2947188,
  "duration_ms": 184000,
  "created_at": "2026-09-14T10:04:00+00:00"
}
```

#### `GET` — the picker

| Query | Type | Default |
|-------|------|---------|
| `asset_type` | enum | — (omit for all) |
| `search` | string | — matches `title` and `file_name` |
| `skip` / `limit` | int | 0 / 20 (max 100) |

Newest first. Returns `{ assets: [GroupAssetDTO], skip, limit, total }`.

This is the endpoint that makes the Studio flow in §8 possible: it is the
group's audio, listed, before anything is linked to anything.

### 4.2 The link — on the recitation collection router

| Method | Path (under `/cms/author/groups/{group_id}/recitation-collections`) | Purpose | Status |
|--------|------|---------|--------|
| `PUT` | `/{collection_id}/items/{item_id}/audio` | Set the item's ordered audio | 200 |

One endpoint, not four.

```json
{ "asset_ids": ["uuid-a", "uuid-b", "uuid-c"] }
```

The array **is** the state: it links, unlinks and reorders in one atomic
replace, and `display_order` is the array index. `[]` clears the item. Sending
the same body twice changes nothing.

This is exactly `PUT /cms/author/groups/{group_id}/posts/{post_id}/media`
(`ReplaceGroupPostMediaRequest` → `replace_post_media`), which already solved
this for post media. The set is small and always fully in hand in the editor, so
a declarative replace beats add/remove/reorder endpoints and the
read-modify-write races they invite.

Validation: every id must be a live asset **of this group** with
`asset_type = AUDIO` (404 naming the offenders — an asset from another group is
"not found", never "forbidden"), duplicates → 400, more than 10 → 400.

**`200` — the updated `GroupRecitationCollectionItemDTO`.**

### 4.3 Reading it back

`GroupRecitationCollectionItemDTO` gains one field:

```python
audio: List[GroupAssetDTO] = []
```

Ordered by `display_order`, presigned on the way out. It shows up on the CMS
detail *and* the public collection detail, so there is no new read endpoint —
and being additive with a default, existing clients are unaffected.

`cms_service.py` and `service.py` each have their own `_build_items_dto` (and
their own copy of `_generate_presigned_url`), so both need the same change: one
batched fetch of links+assets keyed by item id, never a query per item.

---

## 5. Deleting an asset that is in use

The interesting case, and why the link FK is `ON DELETE RESTRICT`.

`DELETE /assets/{asset_id}` with no links → soft-delete the row, delete the S3
object, `204`.

With links → **`409`**, naming what uses it:

```json
{ "detail": "Asset is used by 2 recitation items",
  "usages": [{ "collection_id": "…", "collection_name": "Morning Recitations",
               "item_id": "…", "text_title": "Heart Sutra" }] }
```

Pass `?force=true` to drop those links and delete anyway. Default refuse,
opt-in force: an author deleting from the library cannot see which collections
they are about to silently change, so make them look first. The `asset_id` index
in §3.2 is what keeps that lookup cheap.

Group deletion cascades assets; item or collection deletion drops links and
leaves the assets in the library, which is the point of having one.

---

## 6. Permissions

No new rules — the helpers in `plans/shared/permissions.py` already cover it:

| Action | Helper | Roles |
|--------|--------|-------|
| List / search assets | `require_can_read_group_content` | + VIEWER (browsing is harmless) |
| Upload / rename / delete asset | `require_can_create_content` | OWNER / ADMIN / AUTHOR |
| Set an item's audio | `require_can_create_content` | OWNER / ADMIN / AUTHOR |

Super-admin bypass and the reviewer read-only block come along with those
helpers. Every route takes a CMS author Bearer token.

## 7. Validation and limits

Lift `plan_day_audio_service._validate_audio_file` into a shared helper and
apply it at upload: `ALLOWED_AUDIO_EXTENSIONS` (`.mp3 .m4a .wav .aac .ogg`) →
400, `MAX_AUDIO_FILE_SIZE` (50 MB) → 413.

One new limit: **10 audio assets per item**, matching `MAX_MEDIA_ITEMS_PER_POST`.
The library itself is uncapped.

---

## 8. Studio (`WeBuddhist-Studio`)

The two-layer model is only worth building if the client uses both layers. This
section is the contract, not a suggestion: a Studio that uploads straight onto
an item would put us back at §2.

### 8.1 The flow

On **`GroupChantDetailPage`**, each text row grows an audio cell — a count, or
the first recording's title, plus a **Manage audio** button. It opens a picker
dialog:

1. The dialog lists **the group's audio** —
   `GET /cms/author/groups/{groupId}/assets?asset_type=AUDIO&search=…`, paginated,
   each row showing title, file name, duration and an inline `<audio>` preview.
   This list exists independently of the text being edited; that is the point.
2. The author ticks recordings and drags the selected ones into order.
3. **Upload new** inside the dialog posts one file to
   `POST /cms/author/groups/{groupId}/assets`, then ticks the returned asset
   automatically. The file is in the library the moment it lands — closing the
   dialog without linking still leaves it there for the next text.
4. **Save** sends the whole ordered array to
   `PUT …/items/{itemId}/audio` — one request, no per-row add/remove calls.

A group-level **Assets** page (list, rename, delete, see usage) falls out of the
same endpoints and is where an author cleans up.

### 8.2 Files

| File | Change |
|------|--------|
| `src/components/routes/groups/api/groupAssetsApi.ts` | **New.** Wraps §4.1: `fetchGroupAssets`, `uploadGroupAsset`, `renameGroupAsset`, `deleteGroupAsset` (with the `force` flag). Types `GroupAssetDTO`, `GroupAssetsResponse`, `GroupAssetType` |
| `src/components/routes/groups/api/chantsApi.ts` | Add `setChantItemAudio(groupId, collectionId, itemId, assetIds)`; `ChantCollectionItemDTO` gains `audio: GroupAssetDTO[]` |
| `src/components/routes/groups/components/chants/ChantItemAudioDialog.tsx` | **New.** The picker: search, paginated list, multi-select, dnd-kit ordering, upload tab |
| `src/components/routes/groups/components/chants/ChantItemAudioCell.tsx` | **New.** The row summary + trigger button |
| `src/components/routes/groups/hooks/useGroupAudioAssets.ts` | **New.** Query + upload mutation for the picker, mirroring `useChantImage`'s shape (uploading flag, toasts, 413 handling) |
| `src/components/routes/groups/GroupChantDetailPage.tsx` | Render the new cell per row; wire the dialog |
| `src/components/routes/groups/GroupAssetsPage.tsx` | **New.** The library management page |
| `src/routes/paths.ts` | Add `groupAssets: (groupId) => \`/groups/${groupId}/assets\`` |
| `src/components/routes/groups/GroupLayout.tsx` | Add an **Assets** `NavLink`, next to the existing Chants tab |
| `src/main.tsx` | Register the assets route |

**Do not reuse `uploadChantImage` / `uploadImageToS3`.** That helper posts to
`/cms/media/upload`, which is not group-scoped and returns a bare key — exactly
the un-owned upload path this RFC replaces. Group assets get their own client.

### 8.3 Conventions to follow

These already hold on the chant pages; the new code should not invent its own:

- **Query keys** extend the existing family: `["cms-group-assets", groupId, assetType, search, page]`
  for the picker, alongside today's `["cms-chant-collection", groupId, collectionId]`.
- **After `setChantItemAudio`**, write the returned item into the
  `cms-chant-collection` cache rather than refetching — the same
  `queryClient.setQueryData` move `useChantItemReorder` already makes.
- **After an upload**, invalidate `cms-group-assets` only. The link cache is
  untouched, because uploading links nothing.
- **Ordering** uses `@dnd-kit` + `reorderArray` from `@/lib/utils`, as the item
  list does.
- **Errors** go through `getApiErrorMessage` into a `sonner` toast. Three cases
  deserve their own message: 413 (too large), 400 (bad format / 11th item), and
  409 on delete — which should render the `usages` list and offer "delete
  anyway" rather than a generic failure toast.

### 8.4 Permissions

Gate on `canWriteEvents(groupRole, platformRole)` from
`./lib/eventPermissions` — the OWNER/ADMIN/AUTHOR helper the chant pages already
use, so the audio controls appear exactly where the existing add/remove/reorder
controls do.

A VIEWER sees the audio list and can play it, but gets no upload, no picker save
and no delete. Never rely on that alone: §6 is the real gate, and the client
check is only there to avoid showing buttons that 403.

---

## 9. Non-goals

- Migrating existing surfaces (`plan_item_audio`, post media, covers) onto
  `group_assets`. The table is shaped to absorb them; doing it is separate work.
- `IMAGE` / `VIDEO` assets. The enum reserves them; v1 accepts `AUDIO` only.
- Deduplicating identical uploads by checksum. Worth adding (`checksum_sha256`
  + partial unique per group) once the library has enough in it to sprawl.
- TTS generation (`audio_job_service`) for recitation audio.
- Per-recording playback progress or analytics.
- Waveforms, transcoding, or client-side duration probing — `duration_ms` is
  whatever the uploader reports.

## 10. Acceptance criteria

### Backend

- [ ] An author uploads three recordings to a group and sees all three in
      `GET /assets?asset_type=AUDIO` before linking anything.
- [ ] Linking two of them to one text returns them in the sent order, on both
      the CMS and the public collection detail, presigned.
- [ ] Re-sending the same `asset_ids` reversed reorders them and adds no rows;
      sending `[]` clears them and leaves both assets in the library.
- [ ] One asset can be linked to texts in two different collections.
- [ ] An `asset_id` from another group is rejected as 404, not 403.
- [ ] Deleting a linked asset returns 409 listing its usages; `force=true`
      deletes it and unlinks both.
- [ ] Removing the item, the collection, or the group leaves the library
      correct — links gone, assets intact, except on group delete.
- [ ] A `.pdf`, a 60 MB file, and an 11th link are each rejected.
- [ ] A group VIEWER can list assets but cannot upload or link; a platform
      reviewer can do neither.

### Studio

- [ ] The picker on a chant row lists the group's audio before anything is
      linked, and never shows another group's.
- [ ] Uploading from inside the picker adds the asset to the list, selects it,
      and links nothing until Save.
- [ ] Selecting three, reordering by drag, and saving issues exactly **one**
      `PUT`, and the row reflects the new order without a refetch.
- [ ] Closing the picker after an upload but before Save leaves the file in the
      group Assets page.
- [ ] Deleting an in-use asset shows which collections use it and offers
      "delete anyway"; cancelling changes nothing.
- [ ] A VIEWER can play the audio but sees no upload, save, or delete control.

## 11. Open question

Should a group's recording for a text follow that text **outside** the
collection — in the library view, say? That is text-scoped audio
(`group_id` + `text_id`), which §3.4 traded away for per-collection curation.
The library half of this RFC stands either way; only the link table would
change. Worth settling with product before implementation.
