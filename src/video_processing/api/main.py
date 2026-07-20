from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from video_processing.api.routes.health import router as health_router
from video_processing.api.routes.videos import router as videos_router

app = FastAPI(title="Video Processing API")

app.include_router(health_router)
app.include_router(videos_router)


@app.exception_handler(PoolTimeoutError)
def handle_pool_timeout(_request: Request, _exc: PoolTimeoutError) -> JSONResponse:
    """The DB connection pool is fully checked out -- a capacity limit, not a
    bug. Respond 503 so callers retry, instead of a bare 500 or (without
    `db_pool_timeout` being short) a request hanging for the pool's full
    default wait."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Service temporarily overloaded, please retry"},
    )
