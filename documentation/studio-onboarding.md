# Studio onboarding

How a new author gets from "I was told about the Studio" to creating content,
and what the Studio frontend calls along the way.

Before this, a new author could hit four separate waits before getting in:
signing up, verifying their email, waiting for a SuperAdmin to activate them,
and getting the group owner to re-send an invite that had expired after 30
minutes. Now there's no approval step: anyone who signs in to the Studio is a
creator straight away.

## Who gets in

`studio_access_service.admit_author()` runs on every Studio sign-in (password,
phone, Google, passwordless email, app account, invite sign-up) and on email
verification. It:

1. redeems a join link if `join_link_token` was sent, joining that group;
2. **activates the author** if they weren't active yet. No SuperAdmin is
   involved; every author's platform role is `CREATOR` by default;
3. on that first entry, **accepts every pending invite** to their verified
   email, so they land inside the groups they were invited to.

Password accounts still verify their email before their first sign-in, unless
they sign up from an invite link, which proves the email by itself.

Being active doesn't open anyone else's group: group roles still decide that
(`shared/permissions.py`). A new author on their own can create a group, which
makes them its owner, and its **name goes through the chat term filter**.

### Group name filter

`groups_service._assert_group_name_clean` runs the group's **title and
subtitle in every language, and its slug**, through
`chat.moderation_service.contains_inappropriate_language`. That's the same
`better_profanity` list and dharma-term exceptions used for chat messages. It
runs on create (`POST /cms/author/groups`) and on rename
(`PUT`/`PATCH /cms/author/groups/{id}` with `metadata` or `slug`). A match returns
`400`:

```json
{ "detail": { "success": false, "code": "INAPPROPRIATE_LANGUAGE",
  "message": "The group name contains inappropriate language. Please change it and try again." } }
```

The filter has the same limits as in chat. It matches whole English words, so
joined-up spellings ("badwordgroup") and non-English titles pass.

### Safety rules

- **Suspension is final.** SuperAdmin suspend sets `authors.suspended_at`. A
  sign-in never re-activates a suspended author; only
  `POST /cms/admin/authors/{id}/activate` does, and it clears the field and
  emails the author that their account is active.
- **App signups aren't creators until they use the Studio.** The inert Author
  created for every app signup stays inactive until that person signs in to
  the Studio.
- **Accepting invites needs a proven email.** Invites are only auto-accepted
  when `is_verified` is true, which means the Studio verify link, Auth0 Google
  or passwordless email, or an invite link. App signup doesn't check the
  email, so signing in with an app account activates the author but doesn't
  accept invites addressed to that email.
- **Invite tokens are not login tokens.** They are signed with their own
  audience (`{JWT_AUD}/group-invite`) and carry no `sub`, `email` or
  `phone_number` claim, so they can't be replayed as a bearer token.
- **Signing in with an app account never takes over a Studio account.** The
  app account is attached only through the existing `Author.user_id` link.
  If a separate Studio account already uses the email or phone, the response
  is `409`.

## Config

| Key | Default | Notes |
| --- | --- | --- |
| `GROUP_INVITE_EXPIRY_MINUTES` | `10080` (7 days) | Clamped to 1 minute..30 days. **Check the deployed env:** if it still sets `30`, invites keep expiring in 30 minutes. |
| `STUDIO_JOIN_PAGE_ENABLED` | `false` | Turn on **after** the Studio `/join` page ships. Until then invite emails keep linking to `/groups` with the old wording. |
| `GROUP_JOIN_LINK_DEFAULT_EXPIRY_DAYS` | `14` | |
| `GROUP_JOIN_LINK_MAX_EXPIRY_DAYS` | `90` | |

## Migration

`onbd1a2b3c4d5e` adds `authors.suspended_at` and the `author_group_join_links`
table. Backfill: an inactive author last changed by someone other than
themselves is marked suspended. `updated_by` is only ever written by the
SuperAdmin endpoints, so this keeps existing suspensions in place now that a
sign-in activates everyone else.

## Endpoints

All paths are under `/api/v1`.

### Email invites: `/join?invite=<token>`

With `STUDIO_JOIN_PAGE_ENABLED=true`, the invite email's button opens
`{STUDIO}/join?invite=<token>`.

`GET /cms/auth/invites/preview?token=` (public)

```json
{ "invite_id": "…", "group_id": "…", "group_name": "Sangha", "role": "AUTHOR",
  "target_email": "tenzin@example.org", "inviter_name": "Karma",
  "status": "PENDING", "expires_at": "…", "account_exists": false }
```

`status` is `EXPIRED` once the invite lapses. What the page does next:

- `account_exists: false`: a one-step sign-up form (name + password), or
  "Continue with Google / email code". Signing in that way accepts the invite
  automatically.
  `POST /cms/auth/invites/register`
  `{ "invite_token", "first_name", "last_name", "password" }` → `201` with the
  usual `AuthorLoginResponse` (tokens) plus `joined_group_ids`. There's no
  verify-email step. `409` if an account already exists.
- `account_exists: true`: the normal sign-in. With a password, send
  `invite_token` on `POST /cms/auth/login`; that also verifies an account whose
  email was never confirmed. If the author is already active, call the
  existing `POST /cms/author/groups/invites/{invite_id}/accept`.

### Join links: `/join?link=<token>`

Group OWNER/ADMIN (ADMIN-role links: OWNER only):

- `POST /cms/author/groups/{group_id}/join-links`
  `{ "role": "AUTHOR", "max_uses": 30, "expires_in_days": 14 }` → link with
  `url` to share
- `GET /cms/author/groups/{group_id}/join-links`
- `POST /cms/author/groups/{group_id}/join-links/{link_id}/revoke` → `204`

Anyone with the link:

- `GET /cms/auth/join-links/preview?token=` (public) →
  `{ group_id, group_name, role, expires_at, is_usable }`
- Signed out: pass `join_link_token` to **any** sign-in (`/cms/auth/login`,
  `/phone/exchange`, `/google/exchange`, `/email/exchange`, `/app/login`). It
  works for phone-only authors too.
- Signed in: `POST /cms/author/groups/join-links/redeem` `{ "token" }`.

A link that can't be used never fails the sign-in. The response carries
`join_link_error` instead. Redeeming a link you're already a member of doesn't
use up one of its uses.

### Bulk invites

`POST /cms/author/groups/{group_id}/members/invites/bulk`
`{ "target_emails": ["a@x.org", "b@x.org"], "role": "AUTHOR" }` (max 50) →
`{ "invites": [...], "skipped": [{ "target_email", "reason" }] }`. One bad
address never blocks the rest.

### Sign in with a WeBuddhist app account

`POST /cms/auth/app/login` `{ "email", "password", "join_link_token"? }`. This
is the app's email + password. It returns the same shape as the exchanges.

### Sign-in replies

Every sign-in reply now also has:

- `account_status`: `ACTIVE` or `SUSPENDED`. `status` stays `ACTIVE`/`INACTIVE`
  because the Studio already branches on `INACTIVE`.
- `message`: a suspended author gets "Your Studio account has been suspended.
  Contact a Studio admin." The password login's `401` detail stays exactly
  `Author not active`, which the Studio matches on.
- `joined_group_ids`: open the first one instead of an empty dashboard.
- `join_link_error`

`GET /cms/auth/verify-email` returns `status: ACTIVE` with "You can sign in to
the Studio now".

### SuperAdmin

`GET /cms/admin/authors?account_status=SUSPENDED` (or `ACTIVE`, or `INACTIVE`
for authors who never signed in to the Studio). List and detail rows include
`account_status`; detail rows also include `suspended_at`.

### Other fixes in this change

- Phone sign-in no longer needs `is_verified`, because the SMS code proves the
  person. Before, an author created from an app signup could never sign in by
  phone.
- Phone-only signups no longer log an exception from invite backfill.
