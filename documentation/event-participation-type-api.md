# Event Participation Type — API

Client-facing reference for recording **how** a participant attends an event:
online or offline.

Everything here is additive. The join endpoint's body is optional, the new
response fields are omitted when they are null, and a client that knows
nothing about participation types keeps working exactly as before.

---

## 1. The choice

`participation_type` is `"online"` or `"offline"` — there is no `"hybrid"`
value for a person, because a person attends one way. `hybrid` describes the
*event*, not the participant.

What the event offers decides what the user may pick:

| `event_format` | Sending `participation_type` | Sending nothing |
|----------------|------------------------------|-----------------|
| `hybrid` | `online` or `offline`, both accepted | Stays unset (`null`) — the user has joined but not decided |
| `online` | Only `"online"`; `"offline"` → 400 | Filled in as `"online"` |
| `offline` | Only `"offline"`; `"online"` → 400 | Filled in as `"offline"` |

A single-format event leaves no real choice, so the server fills the value in
rather than leaving it blank — and rejects a contradicting value rather than
silently correcting it, so a client that sends the wrong one hears about it.

---

## 2. Choosing on join

```http
POST /events/{event_id}/participants
Authorization: Bearer <token>

{ "participation_type": "offline" }
```

`204 No Content`.

The body is **optional** — `POST` with no body at all is still valid and keeps
the old behaviour (see the table above).

Join stays idempotent, and doubles as an upsert:

- Joining again with a `participation_type` **updates** the existing
  participation, so the client can implement "switch" with the same call it
  already uses to join.
- Joining again **without** one leaves whatever the user already chose alone;
  it never resets a choice to `null`.

Joining also puts the user into the event's chat room when one exists — see
[event-chat-and-prayers-api.md](./event-chat-and-prayers-api.md).

---

## 3. Switching afterwards

```http
PATCH /events/{event_id}/participants/me
Authorization: Bearer <token>

{ "participation_type": "online" }
```

`204 No Content`. The body is required here, and `participation_type` with it.

This endpoint only *changes* an existing participation — it never creates one.
A caller who has not joined gets `404`, so use `POST` to join and `PATCH` to
switch, or just use `POST` for both.

Leaving the event (`DELETE /events/{event_id}/participants/me`) removes the
row entirely, choice included.

---

## 4. Reading it back

### The caller's own choice

`EventDTO` gains `my_participation_type`:

```json
{
  "id": "860fd109-…",
  "event_format": "hybrid",
  "participant_count": 42,
  "is_joined": true,
  "my_participation_type": "offline"
}
```

It is `null` (and, with `response_model_exclude_none`, absent from the JSON)
when the request is unauthenticated, when the caller has not joined, or when
they joined a hybrid event without picking. Pair it with `is_joined` to tell
"not joined" apart from "joined but undecided".

Served on:

| Endpoint | |
|----------|--|
| `GET /events` | list |
| `GET /events/today` | |
| `GET /events/featured` | |
| `GET /events/{event_id}` | detail |
| `GET /author/groups/feeds` | inside each `EVENT` feed item |

It is always the **authenticated caller's** own choice, never another user's,
and it is looked up only for events the caller has actually joined. The CMS
listings (`GET /cms/events`, `GET /cms/events/{id}`) do not carry it.

### Everyone else's choice

`EventParticipantDTO` gains `participation_type`, on both the public and the
CMS roster:

```http
GET /events/{event_id}/participants?skip=0&limit=20
GET /cms/events/{event_id}/participants?skip=0&limit=20
```

```json
{ "participants": [
    { "user_id": "…", "username": "lena", "fullname": "Lena T.",
      "avatar_url": "https://…", "participation_type": "offline",
      "created_at": "2026-09-16T10:04:00+00:00" }
  ],
  "skip": 0, "limit": 20, "total": 42 }
```

Absent on a participant who has not picked. This is what an organiser counts
heads with — how many are coming in person, how many are dialling in.

---

## 5. Participants who joined before this existed

The column is nullable on purpose, and the migration
(`pt1a2b3c4d5e`) backfills only what it can know for certain: participants of
`online`-only and `offline`-only events get their event's format. Everyone who
had joined a **hybrid** event is left `null` — there is no correct value to
invent — so clients should expect a populated roster to contain participants
with no `participation_type` and prompt for the choice rather than assuming
one.

---

## 6. Errors

| Status | Meaning |
|--------|---------|
| 400 | `Event '<id>' is <format>-only; participation_type '<value>' is not available` — the event does not run the way the caller asked to attend |
| 403 | No bearer token (both endpoints require auth) |
| 404 | The event does not exist |
| 404 | `You have not joined event '<id>'` — `PATCH` (and `DELETE`) on a participation that is not there |
| 422 | `participation_type` missing or not one of `online` / `offline` on `PATCH` |
