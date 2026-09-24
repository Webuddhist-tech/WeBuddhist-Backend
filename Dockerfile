# Use the official Python image from the Docker Hub
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \ 
    ffmpeg \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev \
    libraqm-dev \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Copy the pyproject.toml and poetry.lock files to the container
COPY pyproject.toml poetry.lock /app/

# Install Poetry and Python dependencies (retries tolerate transient PyPI errors).
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    POETRY_HTTP_TIMEOUT=120 \
    POETRY_REQUESTS_TIMEOUT=120 \
    POETRY_INSTALLER_MAX_WORKERS=1
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/root/.cache/pypoetry \
    pip install --upgrade pip setuptools wheel && \
    pip install "poetry>=2.0,<3" && \
    poetry config virtualenvs.create false && \
    poetry config installer.max-workers 1 && \
    for attempt in 1 2 3 4 5 6; do \
        poetry install --no-root --no-interaction && exit 0; \
        echo "poetry install failed (attempt ${attempt}/6), clearing PyPI cache and retrying..."; \
        poetry cache clear PyPI --all --no-interaction || true; \
        sleep $((attempt * 15)); \
    done; \
    exit 1

# Copy the rest of the application code to the container
COPY . /app

# Expose the port that the app runs on
EXPOSE 8000

# Command to run the application
# SYNC_ALEMBIC_STAMP defaults to false; only enable for legacy local databases.
# ws-ping-*: uvicorn defaults (20s/20s) drop a socket after 20s without a
# pong, which a phone on a weak connection hits during an hours-long puja.
CMD ["sh", "-c", "poetry run python scripts/sync_alembic_stamp.py && poetry run alembic upgrade heads && poetry run uvicorn pecha_api.app:api --host 0.0.0.0 --port 8000 --log-level debug --ws-ping-interval 30 --ws-ping-timeout 60"]