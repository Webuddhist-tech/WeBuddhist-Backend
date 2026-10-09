# Event group accumulations (CMS & read API)

Events can link **multiple** group accumulations (e.g. Tara Sadhana + 21 Praise) via the `group_event_accumulations` junction table. Each link has its own format, display order, and counting mode.

---

## `EventDTO.accumulations`

Present on public and CMS event reads (`GET /events/{id}`, `GET /cms/events/{id}`, listings, author group feed when events include linked resources).

Each item (`EventGroupAccumulationDTO`):

| Field | Description |
|-------|-------------|
| `id` | Junction row UUID — use as **`event_accumulation_id`** for in-person CMS APIs when the event has more than one manual link |
| `group_accumulator_id` | Target `group_accumulators.id` |
| `parent_id` | Optional hierarchy (e.g. Praise under Sadhana) |
| `event_format` | `online`, `offline`, or `hybrid` for **this link** (not the event-level format) |
| `display_order` | Sort order in Studio (ascending) |
| `count_mode` | `manual_in_person` or `offline_participants` |
| `group_accumulator` | `{ id, name, image_url }` |
| `offline_participant_count` | Only when `count_mode` is `offline_participants`: count of event participants with `participation_type = offline` (same event-wide RSVP metric on each offline link) |

Top-level **`group_accumulator_id`** / **`group_accumulator`** remain for backward compatibility: they mirror the “primary” link (lowest `display_order` manual root, else lowest root).

---

## CMS create / update: `accumulations[]`

**POST** `/cms/events` and **PUT** `/cms/events/{id}` accept:

```json
"accumulations": [
  {
    "id": "optional-on-update-stable-junction-uuid",
    "group_accumulator_id": "uuid",
    "event_format": "offline",
    "display_order": 1,
    "count_mode": "offline_participants",
    "parent_id": null,
    "client_key": "sadhana",
    "parent_client_key": null
  },
  {
    "group_accumulator_id": "uuid",
    "event_format": "offline",
    "display_order": 2,
    "count_mode": "manual_in_person",
    "parent_client_key": "sadhana"
  }
]
```

- **Update:** when `"accumulations"` is sent, the payload is the **full** intended set; junction rows not listed are removed.
- **Stable `id`:** include on update so in-person URLs and Studio state do not break.
- **`client_key` / `parent_client_key`:** wire parent/child links in one request when creating new rows.

Legacy: sending only top-level **`group_accumulator_id`** (without `accumulations`) upserts a single `manual_in_person` link and does **not** delete other junction rows on multi-link events.

---

## CMS in-person counts: `event_accumulation_id`

**Base:** `/cms/events/{event_id}/in-person-counts`

| Query param | Required when |
|-------------|----------------|
| `event_accumulation_id` | Two or more links with `count_mode = manual_in_person` |
| (omit) | Exactly one manual link, or legacy event with only `events.group_accumulator_id` and no junction rows |

Resolution rules:

1. Param provided → junction row must belong to the event and have `count_mode = manual_in_person` → counts go to that row’s `group_accumulator_id`.
2. Param omitted, one manual link → that link is used; response includes its `event_accumulation_id`.
3. Param omitted, multiple manual links → **409** `EVENT_ACCUMULATION_ID_REQUIRED`.
4. Param points at `offline_participants` link → **409** `NO_MANUAL_EVENT_ACCUMULATION`.

In-person rows are stored in `group_accumulator_history` under the system user (`IN_PERSON_USER_ID`), one count per calendar day in the event timezone.

List/create/update/delete on this router all accept the same query param.

---

## Tara-style example

| Practice | `count_mode` | How it counts |
|----------|--------------|----------------|
| Sadhana | `offline_participants` | Read-only `offline_participant_count` from event RSVPs (`participation_type: offline`) |
| 21 Praise | `manual_in_person` | CMS in-person counts → Praise `group_accumulator_id`; scope with Praise junction `id` as `event_accumulation_id` when both exist |
