# Production Incident Fixes

Three production errors, what caused them, and what changed. Written to be readable
without digging into the code first.

All changes are on the `fix-temprary-issue` branch.

---

## 1. Live recitation returned "Too many positions" on a single request

### What people saw

`POST /events/{event_id}/recitation/position` returned:

```json
{ "detail": "Too many positions for this event; slow down" }
```

...on one request. Not a burst — one. And once an event started doing this, it never
stopped doing it.

### Why

The throttle allows 50 position updates per second per event. It counted them in Redis
like this:

```python
count = await self.redis.incr(key)   # step 1: add one
if count == 1:
    await self.redis.expire(key, 1)  # step 2: make it expire after a second
```

Two separate commands. Step 2 only runs when the counter reads exactly `1`.

So if step 2 ever failed to run — a brief network blip, a restart or deploy landing
between the two, a Redis client retry — the key was left **with no expiry**. And since the
counter never reads `1` again, nothing ever put the expiry back.

From that moment the counter just climbed forever: 51, 52, 53… Every request for that
event was refused, permanently. An operator hitting this at 3pm would still be blocked the
next morning.

The rate limit was raised from 10 to 50 earlier, which didn't help — it just moved the
cliff 40 requests further out.

### The fix

The counting and the expiry now happen in a single Redis script, which Redis runs as one
indivisible unit. Nothing can land between them any more.

```lua
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
elseif redis.call('TTL', KEYS[1]) < 0 then
    -- key lost its expiry at some point: restart the window
    redis.call('SET', KEYS[1], 1, 'EX', ARGV[1])
    count = 1
end
return count
```

The `elseif` branch matters: it repairs events that are **already** stuck. Without it the
fix would only protect new keys, and anything broken today would stay broken until someone
deleted the key by hand.

Two extra safety nets:

- Every event already wedged repairs itself the next time anyone touches it.
- On every app startup (so, on every redeploy) all throttle counters are swept clean. It
  uses `SCAN`, not `KEYS`, so it does not block Redis, and it can never prevent the app
  from starting.

**Files:** `pecha_api/events/recitation_websocket.py`

---

## 2. Plan day content silently going missing

### What people saw

Mostly nothing — which is the problem. Sentry filled up with:

```
RemoteProtocolError: Server disconnected without sending a response
Failed to fetch segment content 'KaRT44lgqWnKVIvKFCoAq' from openpecha
```

The request still returned `200 OK`. But any segment that failed was quietly dropped from
the day's reading. Users got a plan day with lines missing and no error anywhere.

### Why

`Server disconnected without sending a response` means we sent a request down a connection
that the other end had already closed. We reuse connections for speed, and the upstream
service closes idle ones on its own schedule — so occasionally we write into a dead one.

That part is normal and unavoidable. What made it hurt:

- **No retry.** One unlucky connection meant one lost segment, every time.
- **No timeout at all.** A hung request could wait forever.
- **No limit on concurrency.** The endpoint fired one request per segment, all at once —
  dozens or hundreds in parallel. That burst is exactly what provokes the upstream into
  dropping connections.

### The fix

This one was already fixed by the team on `develop` (commits `c0e5ef59`, `590eaf75`):
retries with backoff, a 10-second timeout, connection limits, and a cap of 10 concurrent
requests across all callers.

**Worth knowing:** these transport errors will still happen occasionally — that is
inherent to reusing connections. They are just retried silently now, and only reach Sentry
after three failures in a row. Expect far fewer, not zero.

> This matters for issue 3 below: while these calls were slow, they were holding database
> connections hostage.

**Files:** `pecha_api/external_clients/__init__.py`

---

## 3. The app ran out of database connections

### What people saw

`500` errors, after a 30-second hang, on `/users/me/plan/{plan_id}/days/{day_number}` —
and then on completely unrelated endpoints too:

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached,
connection timed out, timeout 30.00
```

Instances were restarting.

### Why

The app can hold at most 15 database connections. A request that cannot get one waits 30
seconds, then fails. Three separate problems combined to use them all up.

**a) One connection per task, instead of one per request**

Building a plan day looked up "referenced content" once per task, and each of those
lookups opened its **own** database connection instead of reusing the one the request
already had. Those lookups ran in parallel.

A day with five tasks therefore used six connections at once. Three people opening a plan
day = 18 connections against a ceiling of 15.

**b) Connections held during a slow network call**

Worse, the request kept its connection open for its entire duration — *including* while
waiting on the slow openpecha calls from issue 2, which in one trace took **1 minute 10
seconds**.

So connections were not just numerous, they were held for a very long time. The pool never
had a chance to drain. This is why unrelated endpoints started failing too: by the time
they asked for a connection, there were none left. The errors people saw in login or
series lookups were **victims, not causes**.

**c) The connection pool was never configured**

```python
engine = create_engine(get("DATABASE_URL"))
```

No settings at all, so it used SQLAlchemy's defaults — 5 connections plus 10 spare. That is
a reasonable default for a small app, but it was never a deliberate choice, and there was
no health check on connections either (so a database restart left dead connections that
failed on first use).

### The fix

**a)** Referenced content is now resolved **once per request**, reusing the connection the
request already holds. Went from `1 + number_of_tasks` connections down to `1`. The same
bug existed in the CMS day view and was fixed the same way.

**b)** The request now does all its database work up front, **hands the connection back**,
and only then makes the slow network calls. A connection is now held for a few fast
queries instead of for a minute.

> One thing to be careful about: this works because the day query loads all its related
> data up front. If someone later adds a field to this response that loads lazily, it will
> raise `DetachedInstanceError` in production — and the tests will not catch it, because
> they mock the database. There is a comment in the code saying so.

**c)** The pool is now configured and tunable per environment:

| Setting | Value | Why |
|---|---|---|
| `DB_POOL_SIZE` | 10 | Normal capacity |
| `DB_MAX_OVERFLOW` | 20 | Burst headroom (ceiling is 30) |
| `DB_POOL_TIMEOUT` | 30 | Seconds to wait before giving up |
| `DB_POOL_RECYCLE` | 1800 | Replace connections older than 30 minutes |
| `pool_pre_ping` | on | Check a connection is alive before handing it out |

**Before deploying:** that ceiling of 30 is **per instance**. Multiply by your number of
instances and compare against the database's `max_connections` (usually 100). With four or
more instances, lower `DB_POOL_SIZE` via environment variable.

**Files:** `pecha_api/plans/users/plan_users_service.py`,
`pecha_api/plans/cms/cms_plans_service.py`, `pecha_api/db/database.py`,
`pecha_api/config.py`

---

## The common thread

All three bugs share a shape worth remembering:

1. **Two steps that must be one.** The Redis counter broke because incrementing and
   expiring could come apart. Anything that must happen together should happen in one
   atomic operation.

2. **Errors swallowed into silence.** Missing segments and missing references were both
   caught, logged, and turned into a `200 OK` with data quietly absent. Logging an error is
   not the same as handling it — decide deliberately whether the user should be told.

3. **Holding a scarce resource during a slow call.** A database connection is scarce; an
   HTTP call to another service is slow. Never hold the first while waiting on the second.

## Still open

- `/v2/texts/*` calls in `pecha_api/texts/texts_openpecha_api.py` still have no retry
  (9 call sites), so a single dropped connection there becomes a `502` for the user.
- Reference lookups still fail silently into `reference: null`. Worth a deliberate decision
  rather than leaving it as it is.
- There is no automated test for the "already-stuck key repairs itself" path, because the
  test suite has no real Redis. Verify manually on staging: set the key with no expiry,
  send one request, confirm it succeeds.
