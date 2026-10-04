# In-App Feedback — API

Client-facing reference for the endpoint in
[feedback_views.py](../pecha_api/feedback/feedback_views.py).

The app's feedback sheet sends what the user wrote, up to three screenshots,
and some device context. The backend **stores it first**, then forwards a copy
to a Discord channel if a webhook is configured. The database row is the
record; the Discord post is only a notification.

---

## 1. Endpoint

| Method | Path | Auth | Body |
|--------|------|------|------|
| `POST` | `/feedback` | Bearer token (required) | `multipart/form-data` |

The feedback belongs to the user in the token. There is no `user_id` field, and
there is no anonymous feedback: a signed-out user cannot send one, so the app
should only offer the sheet to signed-in users.

---

## 2. Request

`multipart/form-data`, even when there are no images.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `content` | text | **yes** | What the user wrote. Trimmed; blank is rejected. Max `FEEDBACK_MAX_CONTENT_LENGTH` (4000) characters. |
| `images` | file | no | One part **per image**, all under the same field name `images`. Max `FEEDBACK_MAX_IMAGES` (3), max `FEEDBACK_MAX_TOTAL_IMAGE_MB` (10 MB) **in total**. JPEG, PNG, WebP or GIF. |
| `platform` | text | no | e.g. `android 14`, `ios 17.2`. Longer than 255 characters is cut, not rejected. |
| `app_version` | text | no | e.g. `2.3.1+45`. Longer than 64 characters is cut, not rejected. |

Image type is decided from the file's bytes, not its filename or the part's
content type, so a renamed non-image is rejected even if it says `.jpg`.
Images are stored as sent (no re-encoding), so compress on the device: the
app's picker settings (1600×1600, quality 85) fit comfortably.

### curl

```bash
curl -X POST "$API/feedback" \
  -H "Authorization: Bearer $TOKEN" \
  -F "content=The timer stops when the screen locks." \
  -F "platform=android 14" \
  -F "app_version=2.3.1+45" \
  -F "images=@screenshot-1.jpg" \
  -F "images=@screenshot-2.jpg"
```

### Dart (dio)

```dart
final form = FormData()
  ..fields.addAll([
    MapEntry('content', message),
    MapEntry('platform', '${Platform.operatingSystem} ${Platform.operatingSystemVersion}'),
    MapEntry('app_version', '${info.version}+${info.buildNumber}'),
  ]);
for (final path in imagePaths) {
  form.files.add(MapEntry('images', await MultipartFile.fromFile(path)));
}
await dio.post('/feedback', data: form);
```

Every image goes under the plain name `images` (not `images[]` or
`files[0]`), one part per file. A part under any other name is ignored.

---

## 3. Response

```json
201 Created
{
  "id": "6a3c1d6e-2f0b-4a8e-9a57-0d6f1f3c2b11",
  "user_id": "0b8f6c1e-7d5a-4f3e-8c2b-1a9e4d7f6c33",
  "content": "The timer stops when the screen locks.",
  "image_urls": [
    "https://app-pecha-backend.s3.amazonaws.com/feedback/...?X-Amz-Signature=..."
  ],
  "platform": "android 14",
  "app_version": "2.3.1+45",
  "created_at": "2026-10-04T09:12:44.512Z",
  "updated_at": "2026-10-04T09:12:44.512Z"
}
```

`image_urls` are presigned and expire, so do not store them. They are empty
when no images were sent.

A `201` means the feedback is saved. It does **not** mean it reached Discord.
That happens after the response and is never reported back (see §5).

---

## 4. Errors

| Status | When | Body |
|--------|------|------|
| `400` | `content` is blank / whitespace only | `{"detail": "Feedback content must not be empty."}` |
| `400` | `content` is too long | `{"detail": "Feedback content must be at most 4000 characters."}` |
| `400` | More than 3 images | `{"detail": "At most 3 images can be attached to a feedback."}` |
| `400` | An attachment is not a readable JPEG/PNG/WebP/GIF | `{"detail": "Attachment 'x.jpg' is not a valid image."}` |
| `401` | Token invalid or expired | standard token error |
| `403` | No `Authorization` header | `{"detail": "Not authenticated"}` |
| `413` | Images exceed 10 MB in total | `{"detail": "Attached images must be at most 10 MB in total."}` |
| `422` | `content` field missing from the form | FastAPI validation error |

Nothing is stored when the request fails. If saving the row fails after the
images were uploaded, the uploaded images are deleted again.

---

## 5. Discord forwarding

After the row is committed, the backend posts it to
`DISCORD_FEEDBACK_WEBHOOK_URL` in the background:

- **Webhook not set:** nothing is sent. Feedback is still stored.
- **Discord down, rate-limited or rejecting:** the failure is logged and
  dropped. The feedback stays stored, and nothing is retried.

The message is one embed with the feedback text as its description and the
images attached. Its fields are **User ID**, **Email** (only when the user has
one), **App version**, **Platform** and **Feedback ID**. Use Feedback ID to find
the row from a Discord message. Mentions are disabled, so feedback text with
`@everyone` or a role mention cannot ping anyone.

The webhook URL lives only in the backend environment. The app no longer needs
it, and should not ship it: anyone can pull a URL out of an app binary and post
to the channel.

---

## 6. Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `DISCORD_FEEDBACK_WEBHOOK_URL` | `""` | Discord webhook to forward to; empty disables forwarding |
| `FEEDBACK_MAX_CONTENT_LENGTH` | `4000` | Max characters of `content` |
| `FEEDBACK_MAX_IMAGES` | `3` | Max attachments per feedback |
| `FEEDBACK_MAX_TOTAL_IMAGE_MB` | `10` | Max total size of all attachments. Discord's own upload cap, so raising it makes forwarding fail. |

---

## 7. Storage

Table `feedbacks` (migration `fdbk1a2b3c4d5e`):

| Column | Type | Null |
|--------|------|------|
| `id` | uuid | no |
| `user_id` | uuid → `users.id`, `ON DELETE CASCADE` | no |
| `content` | text | no |
| `image_keys` | varchar(512)[] | yes |
| `platform` | varchar(255) | yes |
| `app_version` | varchar(64) | yes |
| `created_at` | timestamptz | no |
| `updated_at` | timestamptz | no |

`image_keys` holds S3 keys (`feedback/{user_id}/{feedback_id}/feedback-{n}.{ext}`),
not URLs: URLs are signed per read.

There is no read or admin endpoint yet. Read feedback from the table or from
Discord.
