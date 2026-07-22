"""Data access for the `processing_jobs` table.

Plain functions, not a class/interface -- there is exactly one backing
implementation (SQLAlchemy + Postgres). Transaction control (commit/rollback)
stays with the calling business logic, not here.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from video_processing.common.models.job_status import JobStatus
from video_processing.common.models.job_type import JobType
from video_processing.common.models.processing_job import ProcessingJob


async def get_by_video_and_type(
    db: AsyncSession, video_id: uuid.UUID, job_type: JobType
) -> ProcessingJob | None:
    return (
        await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.video_id == video_id,
                ProcessingJob.job_type == job_type,
            )
        )
    ).scalar_one_or_none()


def create(db: AsyncSession, job: ProcessingJob) -> None:
    db.add(job)


async def count_completed_for_video(db: AsyncSession, video_id: uuid.UUID) -> int:
    """Count this video's ProcessingJob rows currently marked completed.

    Flushes first: the session disables autoflush (see common/db/session.py),
    so a caller's just-set `job.status = COMPLETED` on the current job would
    not otherwise be visible to this query yet.
    """
    await db.flush()
    return (
        await db.execute(
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.video_id == video_id,
                ProcessingJob.status == JobStatus.COMPLETED,
            )
        )
    ).scalar_one()
