# Recurring Events Backend Implementation - Complete

## ✅ Implementation Status: COMPLETE

All 9 phases of the recurring events backend have been successfully implemented and tested.

---

## Phase Summary

### ✅ Phase 1: Lunar → Gregorian Helper
**Files Modified:**
- `pecha_api/calendar/calendar_parser.py` - Added `find_gregorian_dates_for_lunar()`
- `tests/calendar/test_calendar_parser.py` - Added 6 test cases

**Status:** ✅ Complete - All tests passing

### ✅ Phase 2: Database Migration
**Files Created:**
- `migrations/versions/11de7acad90f_add_event_recurrence_columns.py`

**Columns Added:**
- `is_recurring` (Boolean, default=false)
- `recurrence_frequency` (String(20), nullable)
- `recurrence_date_system` (String(20), nullable)
- `recurrence_calendar_type` (String(10), nullable)
- `recurrence_month` (Integer, nullable)
- `recurrence_day` (Integer, nullable)
- `duration_days` (Integer, default=1)

**Constraints Added:**
- `ck_events_recurrence_required`
- `ck_events_lunar_calendar_type`
- `ck_events_yearly_month`
- `ck_events_duration_positive`

**Status:** ✅ Complete - Migration applied successfully

### ✅ Phase 3: Model & Enums
**Files Created:**
- `pecha_api/events/event_enums.py` - `RecurrenceFrequency`, `RecurrenceDateSystem`

**Files Modified:**
- `pecha_api/events/event_model.py` - Added 7 recurrence columns to Event model

**Status:** ✅ Complete

### ✅ Phase 4: DTOs & Validation
**Files Modified:**
- `pecha_api/events/event_response_models.py`

**Models Added:**
- `RecurrenceInput` - Request model with validation
- `RecurrenceDTO` - Response model

**Models Updated:**
- `CreateEventRequest` - Added `recurrence` field, made dates optional
- `UpdateEventRequest` - Added `recurrence` field
- `EventDTO` - Added `is_recurring`, `recurrence`, `occurrence_date` fields

**Validation Rules:**
- Lunar calendar requires `calendar_type` (phugpa/tsurphu)
- Yearly frequency requires `month`
- Lunar day must be 1-30
- Either dates or recurrence required for create

**Status:** ✅ Complete - All validation tests passing

### ✅ Phase 5: Recurrence Resolution Service
**Files Created:**
- `pecha_api/events/recurrence_service.py`

**Functions Implemented:**
- `compute_initial_dates()` - Compute next occurrence for new events
- `expand_occurrences()` - Expand template into date ranges
- `resolve_next_occurrence()` - Find next occurrence after a date
- Helper functions for Gregorian/Lunar yearly/monthly resolution

**Status:** ✅ Complete - Core logic tested

### ✅ Phase 6: CMS Service Updates
**Files Modified:**
- `pecha_api/events/event_service.py`

**Updates:**
- `create_event_service()` - Handles recurrence input, computes initial dates
- `update_event_service()` - Handles recurrence updates, recomputes dates
- `_event_to_dto()` - Includes recurrence fields in response

**Status:** ✅ Complete

### ✅ Phase 7: Expand-on-Read for List/Today
**Files Modified:**
- `pecha_api/events/event_repository.py` - Added `get_recurring_events()`
- `pecha_api/events/event_service.py` - Rewrote `get_events_service()`

**Implementation:**
- Default expansion window: rolling 12 months from today
- Fetches one-shot events and recurring templates separately
- Resolves each recurring template to its single earliest occurrence within
  the date range (not every occurrence in range) — a template still surfaces
  as one entry per listing regardless of how many times it recurs within the
  window
- Merges and sorts by start_date
- Applies pagination to merged results
- Each occurrence shares parent event ID
- `occurrence_date` field marks an item as an expanded recurring occurrence
  (present) vs. a one-shot event (absent)

**Status:** ✅ Complete (updated 2026-09-07: was originally all occurrences in
range, now first occurrence only — see "Bug Fixes" below)

### ✅ Phase 8: Featured Events
**Status:** ✅ Complete - Existing `get_featured_events_service()` works with recurring events

### ✅ Phase 9: Tests
**Files Created:**
- `tests/events/test_recurrence_service.py` - 15 unit tests
- `tests/events/test_recurring_events_integration.py` - 8 integration tests

**Test Coverage:**
- Gregorian yearly/monthly recurrence
- Lunar yearly/monthly recurrence
- Multi-day duration
- Invalid date handling
- Validation rules
- DTO serialization

**Status:** ✅ Complete - 23 tests passing

---

## API Examples

### Create Recurring Event (Gregorian Yearly)
```json
POST /cms/events
{
  "group_id": "uuid",
  "metadata": [{"name": "Christmas", "description": "...", "language": "EN"}],
  "recurrence": {
    "frequency": "YEARLY",
    "date_system": "GREGORIAN",
    "month": 12,
    "day": 25,
    "duration_days": 1
  }
}
```

### Create Recurring Event (Lunar Monthly)
```json
POST /cms/events
{
  "group_id": "uuid",
  "metadata": [{"name": "Full Moon", "description": "...", "language": "EN"}],
  "recurrence": {
    "frequency": "MONTHLY",
    "date_system": "TIBETAN_LUNAR",
    "calendar_type": "phugpa",
    "day": 15,
    "duration_days": 1
  }
}
```

### List Events (Auto-Expands Recurring)
```
GET /events?from_date=2025-01-01&to_date=2025-12-31
```

Response includes one-shot events plus one entry per recurring template — its
earliest occurrence falling within `[from_date, to_date]` — sorted by
`start_date`. A recurring event does **not** appear once per occurrence; a
monthly template covering the full range still contributes a single item,
not twelve. `total`/`skip`/`limit` are computed over this deduplicated set.
Use `occurrence_date` on an item to see which occurrence was selected.

### Today's Events
```
GET /events/today
X-Timezone: America/New_York
```

Returns events for today. A recurring event appears only if today falls
within its earliest matching occurrence for the day's window.

---

## Database Schema

```sql
ALTER TABLE events ADD COLUMN is_recurring BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE events ADD COLUMN recurrence_frequency VARCHAR(20);
ALTER TABLE events ADD COLUMN recurrence_date_system VARCHAR(20);
ALTER TABLE events ADD COLUMN recurrence_calendar_type VARCHAR(10);
ALTER TABLE events ADD COLUMN recurrence_month INTEGER;
ALTER TABLE events ADD COLUMN recurrence_day INTEGER;
ALTER TABLE events ADD COLUMN duration_days INTEGER NOT NULL DEFAULT 1;
```

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Occurrence ID | Share parent event ID | Simpler v1, participants join template |
| Expansion window | Rolling 12 months | Practical default, bounded results |
| Occurrences per template, per listing | One (earliest in window) | See "One Occurrence Per Recurring Event" below — avoids one row per occurrence in list/CMS views |
| Date fields | Reuse `start_date`/`end_date` | Minimal API surface |
| CMS edits | Template-level only | Per RFC non-goals |
| Participant tracking | Template-level | No per-occurrence joins in v1 |

---

## Files Modified/Created

### Created (4 files)
1. `pecha_api/events/event_enums.py`
2. `pecha_api/events/recurrence_service.py`
3. `migrations/versions/11de7acad90f_add_event_recurrence_columns.py`
4. `tests/events/test_recurrence_service.py`
5. `tests/events/test_recurring_events_integration.py`

### Modified (6 files)
1. `pecha_api/calendar/calendar_parser.py`
2. `pecha_api/events/event_model.py`
3. `pecha_api/events/event_response_models.py`
4. `pecha_api/events/event_service.py`
5. `pecha_api/events/event_repository.py`
6. `tests/calendar/test_calendar_parser.py`

**Total:** 11 files (5 new, 6 modified)

---

## Testing

Run all recurring events tests:
```bash
pytest tests/events/test_recurrence_service.py -v
pytest tests/events/test_recurring_events_integration.py -v
pytest tests/calendar/test_calendar_parser.py::TestFindGregorianDatesForLunar -v
```

---

## Next Steps (Future Enhancements)

Per RFC, these are **out of scope** for v1 (weekly schedules were added post-v1 — see `RecurrenceFrequency.WEEKLY`):
- Chinese lunar calendar
- Per-occurrence edits/exceptions
- Pre-materialized occurrence rows
- iCal export
- `/calendar/resolve` preview endpoint (would be the place to add a
  "list every occurrence of this template in a range" capability, now that
  `GET /events`/`GET /cms/events` only surface one occurrence per template —
  see "One Occurrence Per Recurring Event in List/CMS" under Bug Fixes)

---

## Migration

Apply migration:
```bash
alembic upgrade head
```

Rollback if needed:
```bash
alembic downgrade -1
```

---

**Implementation Date:** August 14, 2026  
**Status:** ✅ Production Ready

---

## Bug Fixes

### Duplicate Recurring Events in List (Fixed: August 14, 2026)

**Issue:** Recurring events appeared twice in event lists - once as the template and once as an expanded occurrence.

**Root Cause:** The `get_events()` function was returning ALL events including recurring templates. The `get_events_service()` then:
1. Fetched all events (including recurring templates) as "one-shot events"
2. Separately fetched recurring templates via `get_recurring_events()`
3. Expanded the recurring templates into occurrences
4. Merged both lists, causing duplicates

**Fix:** Added `is_recurring == False` filter to:
- `get_events()` - now only returns non-recurring events
- `get_featured_events()` - now only returns non-recurring featured events

This ensures recurring events are only processed through the expansion logic, not included in the one-shot events list.

### One Occurrence Per Recurring Event in List/CMS (Fixed: September 7, 2026)

**Issue:** A recurring event appeared once per occurrence inside the query window instead of once per template — e.g. a monthly recurring event listed on `GET /events` or `GET /cms/events` over the default 12-month window showed up as ~12 separate rows with the same underlying event ID. This was especially confusing in the CMS events table (`GroupEventsPage`), where each row is meant to represent one manageable event.

**Root Cause:** `get_events_service()` called `expand_occurrences(template, from_date, to_date)` and appended *every* `(start_date, end_date)` pair it returned to the merged listing, rather than picking a single representative occurrence per template — unlike `get_featured_events_service()` and the author-group-feed service, which already used `resolve_current_or_next_occurrence()` to surface just one occurrence.

**Fix:** `get_events_service()` (`pecha_api/events/event_service.py`) now takes only `occurrences[0]` — the earliest occurrence within `[from_date, to_date]` — from `expand_occurrences()` per template, instead of iterating over the full list. This applies to both `GET /events` (public) and `GET /cms/events` (CMS), since both route through the same function.

**Behavior change:** Callers that relied on the list endpoints to enumerate *every* date a recurring event falls on within a range (e.g. rendering all occurrences of a weekly/monthly event on a calendar) will now only see the next/earliest one per request. There is currently no endpoint that returns the full set of occurrences for a template within a range — a dedicated expansion/preview endpoint would be needed if that becomes a requirement (see "Next Steps").

## Weekly Recurrence (Added: September 8, 2026)

Added `RecurrenceFrequency.WEEKLY` alongside the existing `MONTHLY`/`YEARLY` options — an event that repeats every week on a specific day (e.g. "every Wednesday").

**Files Modified:**
- `pecha_api/events/event_enums.py` - added `WEEKLY` to `RecurrenceFrequency`
- `pecha_api/events/event_model.py` - added `recurrence_day_of_week` column (Integer, nullable)
- `migrations/versions/wk1a2b3c4d5e_add_event_recurrence_weekly.py` - adds the column; splits `ck_events_recurrence_required` into per-frequency day requirements (`ck_events_monthly_yearly_day`, `ck_events_weekly_day_of_week`); adds `ck_events_weekly_gregorian_only` since weekly has no lunar equivalent
- `pecha_api/events/event_response_models.py` - `RecurrenceInput`/`RecurrenceDTO` gained `day_of_week` (0=Monday..6=Sunday); `day` is now optional (required only for MONTHLY/YEARLY, validated in `validate_recurrence_rules`)
- `pecha_api/events/recurrence_service.py` - added `_resolve_gregorian_weekly()`; wired a `WEEKLY` branch into the frequency dispatch in both `expand_occurrences()` and `compute_initial_dates()`
- `pecha_api/events/event_service.py` - threads `recurrence_day_of_week` through `create_event_service()`, `_apply_recurrence_update()`, and `_event_to_dto()`

**Convention:** `day_of_week` uses Python's `date.weekday()` convention: `0=Monday .. 6=Sunday`. Weekly recurrence only supports `RecurrenceDateSystem.GREGORIAN` — there's no lunar "day of week" concept.

**Studio (CMS) changes:** `EventSchema.ts` (added `WEEKLY` + `day_of_week` field + `DAYS_OF_WEEK` constant), `EventRecurrenceSection.tsx` (Weekly option in the frequency dropdown, a Day-of-week select shown in place of the day-of-month input, Tibetan Lunar disabled while Weekly is selected), and `eventsApi.ts` (`day_of_week` threaded through `RecurrenceDTO`/`RecurrenceInput`, `buildRecurrenceInput()`, the DTO→form mapping, and the update-diff check).
