# Ambient Sounds — API

Client-facing reference for the background sound a meditation timer plays: the
curated catalogue, and how a timer points at one entry in it.

Two routers serve it:

| Router | Prefix | Audience |
|--------|--------|----------|
| Ambient sounds | `/ambient-sounds` | The app — reads the catalogue |
| CMS | `/ambient-sounds/cms` | Studio — writes the catalogue |

---

## 1. One catalogue, no uploads

There is exactly one kind of ambient sound: a curated catalogue entry, created
in Studio and listed to everybody. Users do not upload their own — they pick an
entry and point a timer at it.

| | |
|--|--|
| Created by | Studio (super admin) |
| Who sees it | Everybody |
| Who edits it | Super admins, via the CMS router |

### The DTO

```json
{
  "id": "3f1c…",
  "name": "Sea waves",
  "url": "https://s3…?X-Amz-Signature=…",
  "image_url": "https://s3…?X-Amz-Signature=…",
  "is_default": true,
  "display_order": 0
}
```

`url` and `image_url` are **presigned S3 URLs valid for one hour**, minted fresh
on every response. Cache the DTO if you like, but do not persist the URLs —
re-fetch the list instead. Either can come back `null` if the object cannot be
signed; `image_url` is also `null` whenever no cover was uploaded.

`is_default` marks the sound to preselect. At most one entry carries it: setting
it on one row clears it on every other. `display_order` is the catalogue's
manual sort — the list comes back ordered by it, ascending.

---

## 2. Listing (app)

```http
GET /ambient-sounds
```

```json
{ "sounds": [ … ] }
```

Returns the whole catalogue, ordered by `display_order`. **No token required** —
the catalogue is the same for everyone, so there is nothing per-caller to
protect. There is no pagination; the catalogue is small by design.

---

## 3. The catalogue (CMS)

Super-admin only. A non-super-admin caller gets `403`.

| Method | Path | |
|--------|------|--|
| `POST` | `/ambient-sounds/cms` | Publish a sound → 201 |
| `PUT` | `/ambient-sounds/cms/{ambient_sound_id}` | Every field optional |
| `DELETE` | `/ambient-sounds/cms/{ambient_sound_id}` | 204 |

There is no CMS `GET`: Studio reads the same public listing the app does.

### Creating

`multipart/form-data`, not JSON:

```http
POST /ambient-sounds/cms
Authorization: Bearer <token>
Content-Type: multipart/form-data

name:          Sea waves      (required)
file:          waves.mp3      (required)
image_file:    cover.png      (optional)
display_order: 0              (optional, defaults to 0)
is_default:    false          (optional, defaults to false)
```

**Audio file:** extension must be one of `.mp3`, `.m4a`, `.wav`, `.aac`,
`.ogg`, and at most `MAX_AUDIO_FILE_SIZE` (default 50 MB).

**Cover image:** optional, and put through the same validate-and-compress
pipeline as every other user image — it must be an `image/*` upload of at most
`MAX_FILE_SIZE_MB` (default 1 MB), and is stored re-encoded as WebP regardless
of what you send.

If the row fails to save, or the cover is rejected after the audio has already
gone up, the uploaded objects are removed again — a rejected request leaves
nothing behind.

### Updating

```http
PUT /ambient-sounds/cms/{ambient_sound_id}
Content-Type: multipart/form-data

name:          Ocean waves    (optional)
file:          new.mp3        (optional)
image_file:    new-cover.png  (optional)
display_order: 2              (optional)
is_default:    true           (optional)
```

Every field is optional — send only what changes. Omitting a field leaves it
alone; there is no way to clear a cover back to nothing through this endpoint.
Replacing the audio or the cover deletes the old object from storage once the
new row has committed.

### Deleting

**Timers that used it keep working.** The foreign key is `ON DELETE SET NULL`,
so those timers simply have `ambient_sound_id: null` afterwards and fall back to
whatever silence-or-default the client uses — deleting a sound never deletes a
timer or its history. The audio and its cover are removed from storage.

---

## 4. Attaching a sound to a timer

A timer references a catalogue entry by id:

```json
{
  "id": "aa11…", "name": "Morning sit", "duration": 900000,
  "ambient_sound_id": "3f1c…",
  "bell_at_start": true,
  "bell_at_end": true
}
```

Set it on create or update:

```http
POST /timers/user          { "name": "Morning sit", "duration": 900000, "ambient_sound_id": "3f1c…" }
PUT  /timers/user/{id}     { "ambient_sound_id": "3f1c…" }
PUT  /timers/user/{id}     { "ambient_sound_id": null }      // detach
```

On `PUT`, `ambient_sound_id` is only touched when the key is actually present in
the body — omitting it keeps the current sound, whereas sending an explicit
`null` detaches it. An id that is not in the catalogue is `404`.

### Where the choice lives, and how long it lasts

The choice is stored on the **timer row** (`timers.ambient_sound_id`), and that
row belongs to one person (`timers.user_id`). So a user's pick persists
indefinitely — across sessions and devices — and is theirs alone: editing a
timer you do not own is `403`, not a silent no-op.

Two things follow, and clients regularly get them wrong:

**It is per timer, not per user.** A user with three timers has three
independent choices. Changing one does not touch the others, and there is no
user-level "my ambient sound" setting to fall back on — nothing in the schema
stores a preference outside a timer. A client that wants one sound everywhere
has to write it to each timer.

**Only your own user-created timers can be changed.** Curated preset timers
(`type: preset`) are read-only to everybody: a `PUT` against one is
`403 Only user-created timers can be updated`, even for the caller who is
looking at it. To customize a preset, create your own timer from it and set
`parent_preset_id` — the copy is yours, and its sound is yours to change.

**`is_default` is not the user's default.** It marks the catalogue entry Studio
wants preselected for everyone, and at most one entry carries it. It is a
starting point for a client building a picker, not a per-user setting, and a
user changing their timer's sound never changes it.

#### Two users, two picks

```
Ani:  POST /timers/user {"name":"Quick sit","duration":5000,"ambient_sound_id":"green-…"}
      → t1  user_id=Ani   ambient_sound_id=green-…

Dawa: POST /timers/user {"name":"Quick sit","duration":5000,"ambient_sound_id":"rain-…"}
      → t2  user_id=Dawa  ambient_sound_id=rain-…
```

Dawa switching to Sea waves is `PUT /timers/user/t2` and rewrites one column on
one row; `t1` is a different row and is untouched. A `PUT` Dawa aims at `t1` is
`403` before anything is assigned, and `GET /timers/user` is filtered by
`user_id`, so Dawa never sees `t1` at all. The same is true of the cover: each
picks an entry, and each entry brings its own `image_url`.

**The one thing that is shared** is the catalogue entry itself. Two users who
both pick "Green" hear the same audio and see the same cover, and a super admin
editing that entry in Studio changes it for both of them at once. Users own
*which entry they point at*, not the entry's contents — that is the trade for
having one curated catalogue instead of per-user uploads.

### The bells are not this sound

`bell_at_start` and `bell_at_end` are independent booleans on the timer. They do
not reference `ambient_sound_id`, they are not affected by changing or detaching
it, and the catalogue has no say in what a bell sounds like — that is the
client's to decide. A timer can ring its bells with no background sound at all,
or play a background sound with both bells off.

---

## 5. Errors

| Status | Message | Meaning |
|--------|---------|---------|
| 400 | `Invalid audio file format` | Extension outside `.mp3 .m4a .wav .aac .ogg` |
| 400 | image error | The cover is not an image, or could not be processed |
| 403 | forbidden | Non-super-admin calling a `/cms` endpoint |
| 404 | `Ambient sound not found` | No such catalogue entry, on the CMS routes or when attaching one to a timer |
| 413 | `Audio file is too large` | Over `MAX_AUDIO_FILE_SIZE` (default 50 MB) |
| 413 | image size error | Cover over `MAX_FILE_SIZE_MB` (default 1 MB) |

Error bodies from this module are shaped `{"detail": {"error": …, "message": …}}`.

Attaching a sound goes through the timers API, so it can also fail with that
module's errors:

| Status | Message | Meaning |
|--------|---------|---------|
| 403 | `You don't have permission to update this timer` | The timer belongs to someone else |
| 403 | `Only user-created timers can be updated` | The timer is a curated preset; copy it first |
| 404 | `Timer not found` | No such timer |
