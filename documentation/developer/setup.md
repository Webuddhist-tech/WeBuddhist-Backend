## Local Setup

### Prerequisites

- Python 3.12
- Poetry
- Docker (for local services)

### Environment Variables

Defaults are defined in `pecha_api/config.py`, but for local development
you typically override these values:

- `DATABASE_URL`
- `CACHE_CONNECTION_STRING`
- `ELASTICSEARCH_URL`
- `ELASTICSEARCH_API` (optional for local)

Optional integrations:

- `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `AWS_BUCKET_NAME`
- `DOMAIN_NAME`, `CLIENT_ID`, `AUTH0_AUDIENCE`, `AUTH0_ADDITIONAL_CLIENT_IDS` (Auth0)
- `MAILTRAP_API_KEY`, `SENDER_EMAIL`, `SENDER_NAME`

### Install Dependencies

```sh
poetry install
```

### Database and Search

Start local services (Postgres, Redis/Dragonfly, Elasticsearch):

```sh
cd local_setup
docker-compose up -d
```

If you see file permission errors for local data directories:

```sh
./dev/fix_permissions.sh
```

Apply migrations:

```sh
poetry run alembic upgrade head
```

### Run the API

Recommended:

```sh
./dev/start_dev.sh
```

Or run directly:

```sh
poetry run uvicorn pecha_api.app:api --reload
```

### Tests

```sh
poetry run pytest
```

CI (SonarQube) runs the same suite with coverage and does **not** require a local
database. A few optional integration modules run only when `TEST_DATABASE_URL`
points at a **reachable** Postgres instance (for example after
`local_setup/docker-compose.yml`, which exposes Postgres on port **5434**).
If that variable is unset or the database is down, those tests are skipped.

Coverage:

```sh
poetry run pytest --cov=pecha_api --cov=openpecha_api --cov-report=xml --cov-fail-under=80
poetry run coverage html
```
