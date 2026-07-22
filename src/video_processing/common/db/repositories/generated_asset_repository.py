"""Data access for the `generated_assets` table.

Plain functions, not a class/interface -- there is exactly one backing
implementation (SQLAlchemy + Postgres). Transaction control (commit/rollback)
stays with the calling business logic, not here.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from video_processing.common.models.asset_type import AssetType
from video_processing.common.models.generated_asset import GeneratedAsset


async def get_by_video_and_type(
    db: AsyncSession, video_id: uuid.UUID, asset_type: AssetType
) -> GeneratedAsset | None:
    return (
        await db.execute(
            select(GeneratedAsset).where(
                GeneratedAsset.video_id == video_id,
                GeneratedAsset.asset_type == asset_type,
            )
        )
    ).scalar_one_or_none()


async def list_for_video(db: AsyncSession, video_id: uuid.UUID) -> list[GeneratedAsset]:
    return list(
        (
            await db.execute(select(GeneratedAsset).where(GeneratedAsset.video_id == video_id))
        )
        .scalars()
        .all()
    )


def create(db: AsyncSession, asset: GeneratedAsset) -> None:
    db.add(asset)
