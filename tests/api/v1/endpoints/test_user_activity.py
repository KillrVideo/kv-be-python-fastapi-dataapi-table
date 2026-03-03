"""API-level tests for the user activity endpoint."""

import pytest
from httpx import AsyncClient
from fastapi import status
from uuid import uuid4, uuid1
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.main import app
from app.core.config import settings
from app.models.user_activity import UserActivity


@pytest.fixture
def sample_activities():
    userid = uuid4()
    now = datetime.now(timezone.utc)
    return [
        UserActivity(
            userid=userid,
            day=now.strftime("%Y-%m-%d"),
            activity_type="view",
            activity_id=uuid1(),
            activity_timestamp=now,
        ),
        UserActivity(
            userid=userid,
            day=now.strftime("%Y-%m-%d"),
            activity_type="comment",
            activity_id=uuid1(),
            activity_timestamp=now,
        ),
    ], userid


@pytest.mark.asyncio
async def test_get_user_activity_success(sample_activities):
    activities, userid = sample_activities

    with patch(
        "app.api.v1.endpoints.user_activity.user_activity_service.list_user_activity",
        new_callable=AsyncMock,
    ) as mock_list:
        mock_list.return_value = (activities, 2)

        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.get(
                f"{settings.API_V1_STR}/users/{userid}/activity",
            )

        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert len(body["data"]) == 2
        assert body["pagination"]["totalItems"] == 2
        mock_list.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_user_activity_empty():
    with patch(
        "app.api.v1.endpoints.user_activity.user_activity_service.list_user_activity",
        new_callable=AsyncMock,
    ) as mock_list:
        mock_list.return_value = ([], 0)

        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.get(
                f"{settings.API_V1_STR}/users/{uuid4()}/activity",
            )

        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert body["data"] == []
        assert body["pagination"]["totalItems"] == 0
        assert body["pagination"]["totalPages"] == 0


@pytest.mark.asyncio
async def test_get_user_activity_with_type_filter(sample_activities):
    activities, userid = sample_activities
    view_only = [a for a in activities if a.activity_type == "view"]

    with patch(
        "app.api.v1.endpoints.user_activity.user_activity_service.list_user_activity",
        new_callable=AsyncMock,
    ) as mock_list:
        mock_list.return_value = (view_only, 1)

        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.get(
                f"{settings.API_V1_STR}/users/{userid}/activity?activity_type=view",
            )

        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert len(body["data"]) == 1
        item = body["data"][0]
        assert item["activityType"] == "view"
        # Verify the filter was passed through
        call_kwargs = mock_list.call_args[1]
        assert call_kwargs["activity_type"] == "view"


@pytest.mark.asyncio
async def test_get_user_activity_invalid_uuid():
    """Invalid UUID in path returns 422."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get(f"{settings.API_V1_STR}/users/not-a-uuid/activity")
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_user_activity_pagination(sample_activities):
    activities, userid = sample_activities

    with patch(
        "app.api.v1.endpoints.user_activity.user_activity_service.list_user_activity",
        new_callable=AsyncMock,
    ) as mock_list:
        mock_list.return_value = ([activities[1]], 2)

        async with AsyncClient(app=app, base_url="http://test") as ac:
            resp = await ac.get(
                f"{settings.API_V1_STR}/users/{userid}/activity?page=2&pageSize=1",
            )

        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["pagination"]["currentPage"] == 2
        assert body["pagination"]["pageSize"] == 1
        assert body["pagination"]["totalItems"] == 2
        assert body["pagination"]["totalPages"] == 2


@pytest.mark.asyncio
async def test_get_user_activity_invalid_type_returns_422():
    """An unrecognised activity_type value must produce a 422 validation error."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get(
            f"{settings.API_V1_STR}/users/{uuid4()}/activity?activity_type=invalid"
        )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
