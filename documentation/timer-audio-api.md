# Timer Audio — API

Client-facing reference for the audio a meditation timer plays: the curated
preset catalogue, a user's own uploads, and how a timer points at one.

Two routers serve it:

| Router | Prefix | Audience |
|--------|--------|----------|
| Timers | `/timers/audios` | The app — presets plus the caller's own uploads |
| CMS | `/timers/audios/cms` | Studio — the preset catalogue only |

Every endpoint on both requires a bearer token.

---

## 1. Two kinds of audio

`TimerAudioDTO.type` is `preset` or `user_uploaded`:

| | `preset` | `user_uploaded` |
|--|----------|-----------------|
| Created by | Studio (super admin) | Any user, for themselves |
| `user_id` | `null` — it belongs to the catalogue, not a person | The uploader |
| Who sees it | Everybody | Only the uploader |
| Who edits it | Super admins, via the CMS router | The uploader, via the app router |

There is no "shared with a group" kind. An upload is private to the person who
made it, and the only way something reaches everyone is for Studio to publish
it as a preset.

### The DTO

```json
{
  "id": "3f1c…",
  "user_id": "9ab2…",
  "type": "user_uploaded",
  "name": "Morning bell",
  "audio_url": "https://s3…?X-Amz-Signature=…",
  "image_url": "https://s3…?X-Amz-Signature=…",
  "created_at": "2026-09-16T10:04:00+00:00",
  "updated_at": null
}
```

`audio_url` and `image_url` are **presigned S3 URLs valid for one hour**, minted
fresh on every response. Cache the DTO if you like, but do not persist the URLs
— re-fetch the list instead. Either can come back `null` if the object cannot
be signed; `image_url` is also `null` whenever no cover was uploaded.

---

## 2. Listing (app)

```http
GET /timers/audios?skip=0&limit=20
Authorization: Bearer <token>
```

```json
{ "audios": [ … ], "total": 12, "skip": 0, "limit": 20 }
```

Returns **every preset plus the caller's own uploads**, presets first, then
newest-first within each kind. Other people's uploads are never included —
which is why this endpoint needs a token even though presets are public in
spirit. `limit` is 1-100.

---

## 3. Uploading your own (app)

`multipart/form-data`, not JSON:

```http
POST /timers/audios
Authorization: Bearer <token>
Content-Type: multipart/form-data

name:        Morning bell        (required)
audio_file:  bell.mp3            (required)
image_file:  cover.png           (optional)
```

`201 Created` → `TimerAudioDTO`.

**Audio file:** extension must be one of `.mp3`, `.m4a`, `.wav`, `.aac`,
`.ogg`, and at most `MAX_AUDIO_FILE_SIZE` (default 50 MB).

**Cover image:** optional, and put through the same validate-and-compress
pipeline as every other user image — it must be an `image/*` upload of at most
`MAX_FILE_SIZE_MB` (default 1 MB), and is stored re-encoded as WebP regardless
of what you send.

**Names are unique per person** (`(user_id, name)`), so two users may both have
a "Bell" but one user may not have two. A clash is `409`. Preset names are not
constrained this way.

If the row fails to save, or the cover is rejected after the audio has already
gone up, the uploaded objects are removed again — a rejected request leaves
nothing behind.

---

## 4. Editing and deleting your own (app)

```http
PUT /timers/audios/{timer_audio_id}
Content-Type: multipart/form-data

name:        Evening bell     (optional)
audio_file:  new.mp3          (optional)
image_file:  new-cover.png    (optional)
```

Every field is optional — send only what changes. Omitting a field leaves it
alone; there is no way to clear a cover back to nothing through this endpoint.
Replacing the audio or the cover deletes the old object from storage once the
new row has committed.

```http
DELETE /timers/audios/{timer_audio_id}
```

`204 No Content`.

**Timers that used it keep working.** The foreign key is `ON DELETE SET NULL`,
so those timers simply have `timer_audio_id: null` afterwards and fall back to
whatever silence-or-default the client uses — deleting an audio never deletes a
timer or its history.

Both endpoints act on **your own uploads only**. A preset id here is a `404`,
not a `403`: presets are Studio's to manage.

---

## 5. The preset catalogue (CMS)

Same four operations, super-admin only, against presets only:

| Method | Path | |
|--------|------|--|
| `GET` | `/timers/audios/cms?skip=0&limit=20` | Presets only — no user uploads ever appear here |
| `POST` | `/timers/audios/cms` | Publish a preset → 201; same multipart fields as the app upload |
| `PUT` | `/timers/audios/cms/{timer_audio_id}` | Same optional-field semantics |
| `DELETE` | `/timers/audios/cms/{timer_audio_id}` | 204; timers using it keep working |

A created preset has `user_id: null` and is listed to every user immediately.
Passing a user upload's id to any of these reads as `404`.

Deleting a preset that users' timers point at is allowed and safe — those
timers lose the reference (`SET NULL`), not their data. Storage objects are
only removed once no row references them, so a preset sharing media with
another row leaves the file in place.

---

## 6. Attaching an audio to a timer

A timer references an audio by id, and the DTO inlines it so listing timers
needs no second call per timer:

```json
{
  "id": "aa11…", "name": "Morning sit", "duration": 900000,
  "timer_audio_id": "3f1c…",
  "audio": { "id": "3f1c…", "type": "preset", "name": "Bowl", "audio_url": "…" },
  "ambient_sound_id": null,
  "bell_at_start": true,
  "bell_at_end": true
}
```

Set it on create or update:

```http
POST /timers/user          { "name": "Morning sit", "duration": 900000, "timer_audio_id": "3f1c…" }
PUT  /timers/user/{id}     { "timer_audio_id": "3f1c…" }
PUT  /timers/user/{id}     { "timer_audio_id": null }      // detach
```

On `PUT`, `timer_audio_id` is only touched when the key is actually present in
the body — omitting it keeps the current audio, whereas sending an explicit
`null` detaches it.

You may attach **a preset or one of your own uploads**. Someone else's upload
is rejected as `404 Timer audio not found` rather than `403`, so ids cannot be
probed by guessing.

`ambient_sound_id` is a separate feature (a background soundscape) with its own
catalogue, and is validated independently of the timer audio.

---

## 7. Errors

| Status | Message | Meaning |
|--------|---------|---------|
| 400 | `Invalid audio file format` | Extension outside `.mp3 .m4a .wav .aac .ogg` |
| 400 | image error | The cover is not an image, or could not be processed |
| 403 | `You don't have permission to update/delete this audio` | The upload exists but belongs to someone else |
| 403 | forbidden | Non-super-admin calling a `/cms` endpoint |
| 404 | `Timer audio not found` | No such audio, or it is the wrong kind for this router (a preset on the app endpoints, an upload on the CMS ones) |
| 409 | `You already have an audio with this name` | `(user_id, name)` is taken |
| 413 | `Audio file is too large` | Over `MAX_AUDIO_FILE_SIZE` (default 50 MB) |
| 413 | image size error | Cover over `MAX_FILE_SIZE_MB` (default 1 MB) |

Error bodies from this module are shaped `{"detail": {"error": …, "message": …}}`.
