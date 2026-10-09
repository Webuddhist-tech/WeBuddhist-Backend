# RFC: Deity Image on Mantras

| Field | Value |
|-------|-------|
| **Status** | Proposed |
| **Date** | 2026-09-17 |
| **Scope** | WeBuddhist-Backend (`mantra`, `accumulator`); additive, no breaking changes |

---

## 1. Summary

Add one nullable column, `mantra.deity_image`, holding an S3 key. Serve it as an `ImageUrlModel` (`thumbnail` / `medium` / `original`) wherever a mantra is already returned — `GET /mantra`, and the accumulators the mantra is a preset of. Unset means `null`; no backfill.

## 2. Problem

A mantra has a deity — Chenrezig for Om Mani Padme Hung — and nowhere to store it. The only artwork today is the **mala** image: a picture of the beads, per-accumulator and user-overridable, which says nothing about what is being recited.

## 3. Schema

```python
# pecha_api/mantra/mantra_model.py
class Mantra(Base):
    ...
    deity_image = Column(String(1000), nullable=True)   # S3 key of the "original" size
```

Migration `cd2e3f4a5b6c`, `down_revision = "bn1c2d3e4f5a"` (current head): one `add_column`, `drop_column` to roll back.

**A column, not a catalog table.** `mala_images` is a catalog because malas are shared and user-selectable. A deity image is one per mantra and never user-chosen, so a catalog buys deduplication that would never fire at the cost of a table, an FK, and a join per read. This matches `group_accumulators.image_key` ([group_accumulator_models.py:24](../pecha_api/accumulator/group_accumulator_models.py#L24)).

## 4. Read shape

`deity_image: ImageUrlModel | null` on the app surfaces; `deity_image_key: string | null` alongside it on CMS surfaces only, so an edit form can round-trip the key. Three sizes because the image is used both as a list thumbnail and full-bleed on the practice screen, and `prepare_image_upload` already produces all three. Not per-language: it lives on `mantra`, not `mantra_metadata`.

## 5. Endpoints

| Method | Path | Change |
|--------|------|--------|
| `GET` | `/mantra` | `MantraDTO` gains `deity_image` |
| `POST` | `/cms/mantras` | request gains `deity_image_key` |
| `PATCH` | `/cms/mantras/{id}` | **New** — set/clear the key on an existing mantra |
| `POST` | `/cms/mantras/image` | **New** — upload → `PlanUploadResponse`, path `images/mantra_images/{mantra_id}/{uuid4}` |
| `GET` | `/accumulators/presets` | `accumulators[].mantra.deity_image` |
| `GET`/`POST`/`PUT` | `/cms/accumulators/presets…` | same, plus `deity_image_key` |
| `GET` | `/accumulators/user`, `/user/history`, detail | flat `deity_image` on `AccumulatorDTO` / `AccumulatorHistoryDTO` |

`PATCH /cms/mantras/{id}` is required, not extra: `mantra` has only a create endpoint today, so existing rows could otherwise only get an image via raw SQL.

## 6. Implementation

- `PresetMantraDTO` gains the field, filled in `build_preset_mantra_dto` ([accumulator_service.py:191](../pecha_api/accumulator/accumulator_service.py#L191)) — that one function already feeds every preset surface, and those services already batch `get_mantras_by_ids`, so the preset side costs no extra query.
- `AccumulatorDTO` / `AccumulatorHistoryDTO` resolve it from the linked mantra: `convert_accumulators_to_dtos` and `_build_accumulator_history_dto` take an optional `mantras_by_id`, batched once per page in the user list/detail/history services. One extra `WHERE id IN (…)`, never per row.
- **Resolved, never copied.** `mala_image` is copied onto the accumulator at create time because the user can override it; the deity image has no override, so copying would only create a second source of truth that goes stale when the CMS swaps the artwork.
- One helper presigns, via `safe_get_image_url` — a bad key logs and yields `null` instead of 500-ing a whole preset list:

```python
def resolve_deity_image(mantra: Optional[Mantra]) -> Optional[ImageUrlModel]:
    if mantra is None or not mantra.deity_image:
        return None
    return safe_get_image_url(mantra.deity_image, resource_id=mantra.id, resource_type="mantra")
```

Touched: `mantra_model.py`, `mantra_response_models.py`, `mantra_service.py`, `mantra_repository.py`, `mantra_views.py`, `accumulator_response_models.py`, `accumulator_service.py`, one migration.

## 7. Rollout, tests, out of scope

Migration ships → everything reads `null` → CMS uploads images. Every added field is optional, so no client release is gated on the migration and a new client still works against the old backend.

Tests: create/patch/clear the key; `GET /mantra` returns three presigned sizes; presign failure yields `null`; a preset and a user accumulator created from it resolve the same image, and both follow a CMS key change (the no-copy guarantee); `GET /accumulators/user` stays at one mantra query for 20 rows.

Out of scope, each a separate small change: bookmark thumbnails ([bookmark_utils.py:562](../pecha_api/bookmarks/bookmark_utils.py#L562)), routine session cards, `MantraCountSummaryDTO`, `GroupMantraAccumulationDTO`, per-language artwork.
