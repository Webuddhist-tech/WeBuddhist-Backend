## Architecture

### Overview

The backend is a FastAPI application with a single app in `pecha_api/app.py`.
Routers are registered on `api` with `root_path="/api/v1"` and a shared
lifespan in `pecha_api/db/lifespan.py`.

Each feature module typically contains:
- `*_views.py` for routes
- `*_services.py` for business logic
- `*_models.py` for data models and response schemas

### Module Map

Routers included in `pecha_api/app.py`:

- `auth`: `pecha_api/auth/auth_views.py`
- `sheets`: `pecha_api/sheets/sheets_views.py`
- `collections`: `pecha_api/collections/collections_views.py`
- `texts`: `pecha_api/texts/texts_views.py`
- `groups`: `pecha_api/texts/groups/groups_views.py`
- `segments`: `pecha_api/texts/segments/segments_views.py`
- `users`: `pecha_api/users/users_views.py`
- `share`: `pecha_api/share/share_views.py`
- `search`: `pecha_api/search/search_views.py`
- `plans (CMS)`: `pecha_api/plans/cms/cms_plans_views.py`
- `plans (public)`: `pecha_api/plans/public/plan_views.py`
- `plans (users)`: `pecha_api/plans/users/plan_users_views.py`
- `plans (items)`: `pecha_api/plans/items/plan_items_views.py`
- `plans (tasks)`: `pecha_api/plans/tasks/plan_tasks_views.py`
- `plans (sub-tasks)`: `pecha_api/plans/tasks/sub_tasks/plan_sub_tasks_views.py`
- `plans (authors)`: `pecha_api/plans/authors/plan_authors_views.py`
- `plans (media)`: `pecha_api/plans/media/media_views.py`
- `plans (featured)`: `pecha_api/plans/featured/featured_day_views.py`
- `recitations`: `pecha_api/recitations/recitations_view.py`
- `user follows`: `pecha_api/user_follows/user_follow_views.py`
- `user recitations`: `pecha_api/plans/users/recitation/user_recitations_views.py`
- `cataloger`: `pecha_api/cataloger/cataloger_views.py`

### Dependencies

Local services used during development (see `local_setup/docker-compose.yml`):
- Postgres (port 5434)
- Dragonfly/Redis (port 6379)
- Elasticsearch (port 9200)

External integrations (configured in `pecha_api/config.py`):
- AWS S3 compatible storage
- Auth0
- Mailtrap

### Error Handling

Use `HTTPException` for expected errors. Log unexpected failures and return
consistent error responses from shared helpers.
