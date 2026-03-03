"""API endpoint for querying user activity timelines."""

from __future__ import annotations

from typing import Annotated, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import PaginationParams
from app.models.common import PaginatedResponse, Pagination
from app.models.user_activity import UserActivityResponse
from app.services import user_activity_service

router = APIRouter(tags=["User Activity"])


@router.get(
    "/users/{user_id_path}/activity",
    response_model=PaginatedResponse[UserActivityResponse],
    summary="Get user activity timeline",
)
async def get_user_activity(
    user_id_path: UUID,
    pagination: Annotated[PaginationParams, Depends()],
    activity_type: Optional[Literal["view", "comment", "rate"]] = Query(
        None, description="Filter by activity type (view, comment, rate)"
    ),
):
    """Return a paginated timeline of a user's activity over the last 30 days."""

    activities, total = await user_activity_service.list_user_activity(
        userid=user_id_path,
        page=pagination.page,
        page_size=pagination.pageSize,
        activity_type=activity_type,
    )

    total_pages = (total + pagination.pageSize - 1) // pagination.pageSize

    response_items = [UserActivityResponse.model_validate(a) for a in activities]

    return PaginatedResponse[UserActivityResponse](
        data=response_items,
        pagination=Pagination(
            currentPage=pagination.page,
            pageSize=pagination.pageSize,
            totalItems=total,
            totalPages=total_pages,
        ),
    )
