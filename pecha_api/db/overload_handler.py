"""Turn a saturated connection pool into a clean 503 instead of a 500.

`DB_POOL_TIMEOUT` is deliberately short: a request that cannot get a
connection should give up quickly rather than hold a worker thread for half a
minute while the queue behind it grows. The cost of a short timeout is that
SQLAlchemy raises more often under load, so the raise has to mean "busy, come
back" - an unhandled 500 tells the client to give up, tells the app's error
tracking something is broken, and loses the one piece of information the
caller can act on, which is that retrying shortly will probably work.
"""

import logging

from fastapi import FastAPI
from sqlalchemy.exc import TimeoutError as SQLAlchemyPoolTimeout
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Long enough for in-flight requests to hand their connections back, short
# enough that a phone retrying feels like a hesitation rather than an outage.
RETRY_AFTER_SECONDS = "2"

BUSY_DETAIL = "The service is busy right now. Please try again in a moment."


async def pool_timeout_handler(request: Request, exc: Exception) -> JSONResponse:
    # warning, not exception: pool exhaustion is a capacity signal, not a bug,
    # and at the moment it happens it happens to *every* in-flight request. A
    # stack trace per request would bury the incident in its own noise.
    logger.warning(
        "DB connection pool exhausted serving %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": BUSY_DETAIL},
        headers={"Retry-After": RETRY_AFTER_SECONDS},
    )


def register_db_overload_handlers(api: FastAPI) -> None:
    """Register the pool-exhaustion handler on the app."""
    api.add_exception_handler(SQLAlchemyPoolTimeout, pool_timeout_handler)
