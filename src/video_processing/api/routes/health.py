from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from video_processing.common.db.session import get_db_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    summary="Liveness check",
    description="Confirms the process is running; no dependency checks.",
)
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/ready",
    summary="Readiness check",
    description="Confirms the process can serve traffic by checking the database connection.",
    responses={503: {"description": "Database is not reachable"}},
)
def ready(db: Annotated[Session, Depends(get_db_session)]) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not reachable",
        ) from error

    return {"status": "ok"}
