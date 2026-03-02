"""Service logic for video ratings."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID

from fastapi import HTTPException, status

from app.db.astra_client import get_table, AstraDBCollection
from app.models.rating import (
    RatingCreateOrUpdateRequest,
    Rating,
    AggregateRatingResponse,
    RatingValue,
)
from app.models.video import VideoID, VideoStatusEnum
from app.models.user import User
from app.services import video_service
from app.services.user_activity_service import record_user_activity
from astrapy.exceptions.data_api_exceptions import DataAPIResponseException

logger = logging.getLogger(__name__)

RATINGS_TABLE_NAME = video_service.VIDEO_RATINGS_TABLE_NAME  # "video_ratings_by_user"
RATINGS_SUMMARY_TABLE_NAME = video_service.VIDEO_RATINGS_SUMMARY_TABLE_NAME


async def _update_video_aggregate_rating(
    video_id: VideoID,
    new_rating: int,
    old_rating: int | None = None,
    summary_db_table: AstraDBCollection | None = None,
) -> None:
    """Increment counters on the video_ratings summary table.

    * **New rating** (old_rating is None): increment rating_counter by 1 and
      rating_total by new_rating.
    * **Updated rating** (old_rating provided): increment rating_total by
      (new_rating - old_rating) only — counter stays the same.
    """

    if summary_db_table is None:
        summary_db_table = await get_table(RATINGS_SUMMARY_TABLE_NAME)

    vid_str = str(video_id)

    if old_rating is None:
        inc_doc: Dict[str, Any] = {"rating_counter": 1, "rating_total": new_rating}
    else:
        delta = new_rating - old_rating
        inc_doc = {"rating_total": delta}

    try:
        await summary_db_table.update_one(
            filter={"videoid": vid_str},
            update={"$inc": inc_doc},
            upsert=True,
        )
    except DataAPIResponseException as exc:
        if "Update operation not supported" in str(
            exc
        ) or "unsupported operations" in str(exc):
            existing = await summary_db_table.find_one(
                filter={"videoid": vid_str}
            )
            counter = int(existing.get("rating_counter", 0)) if existing else 0
            total = int(existing.get("rating_total", 0)) if existing else 0
            if old_rating is None:
                counter += 1
                total += new_rating
            else:
                total += new_rating - old_rating
            await summary_db_table.update_one(
                filter={"videoid": vid_str},
                update={"$set": {"rating_counter": counter, "rating_total": total}},
                upsert=True,
            )
        else:
            raise


async def rate_video(
    video_id: VideoID,
    request: RatingCreateOrUpdateRequest,
    current_user: User,
    db_table: Optional[AstraDBCollection] = None,
) -> Rating:
    target_video = await video_service.get_video_by_id(video_id)
    if target_video is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    # Videos persisted through the fallback path often lack a ``status`` column
    # (the table schema has no such column).  In that scenario Pydantic fills
    # the attribute with its default (PENDING). We consider *absence* of the
    # field equivalent to READY so that legacy/legacy-imported videos remain
    # rateable.
    status_in_doc = "status" in getattr(target_video, "model_fields_set", set())
    if target_video.status != VideoStatusEnum.READY and status_in_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not available for rating",
        )

    if db_table is None:
        db_table = await get_table(RATINGS_TABLE_NAME)

    now = datetime.now(timezone.utc)
    rating_filter = {"videoid": str(video_id), "userid": str(current_user.userid)}
    existing_doc = await db_table.find_one(filter=rating_filter)

    if existing_doc:
        await db_table.update_one(
            filter=rating_filter,
            update={"$set": {"rating": request.rating, "rating_date": now}},
        )
        created_at = existing_doc.get("rating_date", now)
        rating_obj = Rating(
            videoId=video_id,
            userId=current_user.userid,
            rating=request.rating,
            createdAt=created_at,
            updatedAt=now,
        )
        # Track in user_activity (never fail the rating operation)
        try:
            await record_user_activity(
                userid=current_user.userid,
                activity_type="rate",
            )
        except Exception:
            logger.debug(
                "user_activity insert failed for rate; ignoring", exc_info=True
            )
    else:
        rating_obj = Rating(
            videoId=video_id,
            userId=current_user.userid,
            rating=request.rating,
            createdAt=now,
            updatedAt=now,
        )
        insert_doc = {
            "videoid": str(video_id),
            "userid": str(current_user.userid),
            "rating": request.rating,
            "rating_date": now,
        }
        await db_table.insert_one(document=insert_doc)
        # Track in user_activity (never fail the rating operation)
        try:
            await record_user_activity(
                userid=current_user.userid,
                activity_type="rate",
            )
        except Exception:
            logger.debug(
                "user_activity insert failed for rate; ignoring", exc_info=True
            )

    # update aggregate counters on the summary table
    old_rating_value: int | None = None
    if existing_doc:
        old_rating_value = int(existing_doc["rating"])
    await _update_video_aggregate_rating(
        video_id, new_rating=request.rating, old_rating=old_rating_value
    )
    return rating_obj


# ---------------------------------------------------------------------------
# Aggregate fetch
# ---------------------------------------------------------------------------


async def get_video_ratings_summary(
    video_id: VideoID,
    current_user_id: UUID | None = None,
    ratings_db_table: Optional[AstraDBCollection] = None,
    summary_db_table: Optional[AstraDBCollection] = None,
) -> AggregateRatingResponse:
    """Return aggregated rating info for a video and optionally the caller's rating."""

    # 404 check – make sure the video exists
    target_video = await video_service.get_video_by_id(video_id)
    if target_video is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Video not found"
        )

    # Read counters from the video_ratings summary table
    if summary_db_table is None:
        summary_db_table = await get_table(RATINGS_SUMMARY_TABLE_NAME)

    summary_doc = await summary_db_table.find_one(
        filter={"videoid": str(video_id)}
    )

    if summary_doc:
        rating_counter = int(summary_doc.get("rating_counter", 0))
        rating_total = int(summary_doc.get("rating_total", 0))
        avg = round(rating_total / rating_counter, 2) if rating_counter > 0 else None
        total = rating_counter
    else:
        avg = None
        total = 0

    # Look up current user's individual rating
    user_rating_value: RatingValue | None = None
    if current_user_id is not None:
        if ratings_db_table is None:
            ratings_db_table = await get_table(RATINGS_TABLE_NAME)

        doc = await ratings_db_table.find_one(
            filter={"videoid": str(video_id), "userid": str(current_user_id)},
            projection={"rating": 1},
        )
        if doc and "rating" in doc:
            user_rating_value = int(doc["rating"])

    return AggregateRatingResponse(
        videoId=video_id,
        averageRating=avg,
        totalRatingsCount=total,
        currentUserRating=user_rating_value,
    )
