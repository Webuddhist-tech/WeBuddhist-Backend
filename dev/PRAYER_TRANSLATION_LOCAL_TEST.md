# Local prayer translation test (copy-paste)

Seeded in your local Postgres (`localhost:5434/pecha`). API docs: **http://127.0.0.1:8000/doc**

## One-time: enable email login for test users

Seeded accounts have no password until you run:

```bash
cd WeBuddhist-Backend
poetry run python dev/set_local_test_password.py
```

Default password: **`localdev-test`** (override with env `LOCAL_TEST_PASSWORD`).

## Get a JWT (Swagger)

1. **POST `/auth/login`**
   ```json
   {
     "email": "lobsangshakya5@gmail.com",
     "password": "localdev-test"
   }
   ```
2. Copy **`auth.access_token`** (not `refresh_token`).
3. Click **Authorize** → Bearer → paste **only** the token (no `Bearer ` prefix if the UI adds it for you).

Auth0 tokens also work if the token’s email matches a user in your local DB; email login is simpler for local dev.

## IDs (fixed for this seed)

| What | UUID |
|------|------|
| **Event id** | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| **Group id** | `81d53c2f-2667-4d03-9d54-b36a79674540` |
| **Room id** | Created on step 1 — use `id` from the room response (may already exist from a prior GET) |

**Test users (group members):** `lobsangshakya5@gmail.com`, `lobsangshakya6@gmail.com`

**Intention slug (any):** `peace`, `healing`, `abundance`, `love`, `protection`

---

## Endpoints to try (in order)

### 0. Optional — list intentions (no auth)

```http
GET /intentions
```

### 1. Open event chat room (creates room + joins you)

```http
GET /chat/events/a1b2c3d4-e5f6-7890-abcd-ef1234567890/room
Authorization: Bearer YOUR_JWT
```

Copy **`id`** from the JSON → that is **`room_id`** for step 3.

### 2. Post a prayer request (Chinese → translate to EN)

```http
POST /chat/events/a1b2c3d4-e5f6-7890-abcd-ef1234567890/messages
Authorization: Bearer YOUR_JWT
Content-Type: application/json
```

```json
{
  "body": "为我们镇上的流浪狗祈祷，愿它们冬天有温暖有食物。",
  "message_type": "PRAYER",
  "intention": "peace"
}
```

Expect **201**: `body` = original text; often `translation.status` = `pending`.

### 3. List prayers with English translation (poll every ~10s)

Replace `ROOM_ID` with value from step 1.

```http
GET /chat/rooms/ROOM_ID/messages?message_type=PRAYER&translation_language=EN&limit=20
Authorization: Bearer YOUR_JWT
```

**Success:** `source_language` = `ZH`, `translation.status` = `ready`, `translation.body` = English; `body` still Chinese.

### 4. Same language → no translation toggle

```http
GET /chat/rooms/ROOM_ID/messages?message_type=PRAYER&translation_language=ZH&limit=20
Authorization: Bearer YOUR_JWT
```

Expect `can_translate: false` on the Chinese prayer.

### 5. Optional — edit prayer body (re-runs translation)

```http
PATCH /chat/rooms/ROOM_ID/messages/MESSAGE_ID
Authorization: Bearer YOUR_JWT
Content-Type: application/json
```

```json
{
  "body": "请为我的母亲康复祈祷。"
}
```

Then repeat step 3.

### 6. Optional — event detail (prayer count)

```http
GET /events/a1b2c3d4-e5f6-7890-abcd-ef1234567890
Authorization: Bearer YOUR_JWT
```

---

## Env (backend)

In `.env`:

- `GEMINI_API_KEY` — required for real translations
- `PRAYER_TRANSLATION_ENABLED=true`

Restart uvicorn after changes.

## SQL sanity check

```sql
SELECT id, source_language, left(body, 40)
FROM chat_messages WHERE message_type = 'PRAYER' ORDER BY created_at DESC LIMIT 3;

SELECT message_id, target_language, status, left(body, 50)
FROM chat_message_translations ORDER BY updated_at DESC LIMIT 6;
```

## Troubleshooting auth

| Response | Fix |
|----------|-----|
| **403** on `/room` | Add `Authorization: Bearer …` |
| **401** `Invalid or no token found` | Use `access_token` from `/auth/login`; run `set_local_test_password.py` if login fails |
| **401** `Invalid email or password` | Run `dev/set_local_test_password.py` |
