"""Service layer for tracking user activity (views, comments, ratings)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from uuid import UUID, uuid1

from app.db.astra_client import get_table, AstraDBCollection
from app.models.user_activity import UserActivity, ACTIVITY_TYPES

USER_ACTIVITY_TABLE_NAME = "user_activity"

ANONYMOUS_USER_ID = UUID("00000000-0000-0000-0000-000000000000")

# Hard cap on total rows scanned across all 30 partitions to prevent OOM.
MAX_ACTIVITY_ROWS = 1000

logger = logging.getLogger(__name__)


async def record_user_activity(
    userid: UUID,
    activity_type: ACTIVITY_TYPES,
    activity_id: Optional[UUID] = None,
    db_table: Optional[AstraDBCollection] = None,
) -> None:
    """Insert a single user activity row.

    Parameters
    ----------
    userid:
        The user who performed the action (use ANONYMOUS_USER_ID for unauthenticated).
    activity_type:
        One of 'view', 'comment', 'rate'.
    activity_id:
        Optional time-based UUID linking back to the activity. Auto-generated if not provided.
    db_table:
        Optional pre-fetched table reference (for testing).
    """

    if db_table is None:
        db_table = await get_table(USER_ACTIVITY_TABLE_NAME)

    if activity_id is None:
        activity_id = uuid1()

    now_utc = datetime.now(timezone.utc)
    day_partition = now_utc.strftime("%Y-%m-%d")

    await db_table.insert_one(
        {
            "userid": str(userid),
            "day": day_partition,
            "activity_type": activity_type,
            "activity_id": str(activity_id),
            "activity_timestamp": now_utc.isoformat(),
        }
    )


async def _fetch_day_rows(
    db_table: AstraDBCollection,
    userid: UUID,
    day_key: str,
    activity_type: Optional[str],
    limit: int,
) -> List[dict]:
    """Fetch activity rows for a single day partition.

    Returns an empty list on error so one bad partition does not abort the
    entire read.
    """
    try:
        query_filter: dict = {"userid": str(userid), "day": day_key}
        if activity_type:
            query_filter["activity_type"] = activity_type

        cursor = db_table.find(filter=query_filter, limit=limit)

        if hasattr(cursor, "to_list"):
            return await cursor.to_list()
        return cursor  # type: ignore[return-value]
    except Exception:
        logger.warning(
            "Failed to fetch user activity for day=%s userid=%s; skipping partition.",
            day_key,
            userid,
            exc_info=True,
        )
        return []


async def list_user_activity(
    userid: UUID,
    page: int,
    page_size: int,
    activity_type: Optional[str] = None,
    db_table: Optional[AstraDBCollection] = None,
) -> Tuple[List[UserActivity], int]:
    """Query user activity across the last 30 days of partitions.

    Queries all 30 day-partitions concurrently via asyncio.gather and applies a
    hard cap of MAX_ACTIVITY_ROWS total rows to prevent unbounded memory usage.

    Returns
    -------
    Tuple[List[UserActivity], int]
        A page of activity items and the total count.
    """

    if db_table is None:
        db_table = await get_table(USER_ACTIVITY_TABLE_NAME)

    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=29)

    partition_keys: List[str] = [
        (start_date + timedelta(days=delta)).strftime("%Y-%m-%d")
        for delta in range(30)
    ]

    # Run all 30 partition queries concurrently; divide the total cap evenly
    # across all partitions so that 30 x per_day_limit stays bounded at
    # ~MAX_ACTIVITY_ROWS rather than 30 x MAX_ACTIVITY_ROWS.
    per_day_limit = max(1, MAX_ACTIVITY_ROWS // 30)

    results: List[List[dict]] = await asyncio.gather(
        *[
            _fetch_day_rows(db_table, userid, day_key, activity_type, per_day_limit)
            for day_key in partition_keys
        ]
    )

    all_rows: List[dict] = []
    for day_rows in results:
        all_rows.extend(day_rows)
        if len(all_rows) >= MAX_ACTIVITY_ROWS:
            all_rows = all_rows[:MAX_ACTIVITY_ROWS]
            break

    # Sort by activity_timestamp descending (newest first)
    all_rows.sort(
        key=lambda r: r.get("activity_timestamp", ""),
        reverse=True,
    )

    total = len(all_rows)

    # Paginate
    skip = (page - 1) * page_size
    page_rows = all_rows[skip : skip + page_size]

    activities = [UserActivity.model_validate(r) for r in page_rows]
    return activities, total
