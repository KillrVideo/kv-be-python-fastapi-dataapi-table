import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from app.services import rating_service
from app.models.rating import RatingCreateOrUpdateRequest
from app.models.user import User
from app.models.video import Video, VideoStatusEnum


@pytest.fixture
def viewer_user() -> User:
    return User(
        userid=uuid4(),
        firstname="Viewer",
        lastname="Test",
        email="viewer@example.com",
        roles=["viewer"],
        created_date=datetime.now(timezone.utc),
        account_status="active",
    )


def _make_video(video_id=None, **kwargs):
    defaults = dict(
        videoid=video_id or uuid4(),
        userid=uuid4(),
        added_date=datetime.now(timezone.utc),
        name="Title",
        location="http://a.b/c.mp4",
        location_type=0,
        status=VideoStatusEnum.READY,
        title="Title",
    )
    defaults.update(kwargs)
    return Video(**defaults)


# ---------------------------------------------------------------------------
# rate_video – new rating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_video_new(viewer_user: User):
    video_id = uuid4()
    req = RatingCreateOrUpdateRequest(rating=4)

    with (
        patch(
            "app.services.rating_service.video_service.get_video_by_id",
            new_callable=AsyncMock,
        ) as mock_get_vid,
        patch(
            "app.services.rating_service.get_table", new_callable=AsyncMock
        ) as mock_get_table,
    ):
        mock_get_vid.return_value = _make_video(video_id)
        ratings_tbl = AsyncMock()
        summary_tbl = AsyncMock()
        mock_get_table.return_value = summary_tbl

        ratings_tbl.find_one.return_value = None
        ratings_tbl.insert_one.return_value = {}

        result = await rating_service.rate_video(
            video_id, req, viewer_user, db_table=ratings_tbl
        )
        assert result.rating == 4
        ratings_tbl.insert_one.assert_called_once()
        # Should call $inc on summary table with counter=1, total=4
        summary_tbl.update_one.assert_awaited_once()
        call_kwargs = summary_tbl.update_one.call_args.kwargs
        assert call_kwargs["update"] == {"$inc": {"rating_counter": 1, "rating_total": 4}}


# ---------------------------------------------------------------------------
# rate_video – update existing rating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_video_update(viewer_user: User):
    video_id = uuid4()
    req = RatingCreateOrUpdateRequest(rating=5)

    existing_doc = {
        "videoid": str(video_id),
        "userid": str(viewer_user.userid),
        "rating": 3,
        "rating_date": datetime.now(timezone.utc),
    }

    with (
        patch(
            "app.services.rating_service.video_service.get_video_by_id",
            new_callable=AsyncMock,
        ) as mock_get_vid,
        patch(
            "app.services.rating_service.get_table", new_callable=AsyncMock
        ) as mock_get_table,
    ):
        mock_get_vid.return_value = _make_video(video_id)
        ratings_tbl = AsyncMock()
        summary_tbl = AsyncMock()
        mock_get_table.return_value = summary_tbl

        ratings_tbl.find_one.return_value = existing_doc
        ratings_tbl.update_one.return_value = {}

        result = await rating_service.rate_video(
            video_id, req, viewer_user, db_table=ratings_tbl
        )

        ratings_tbl.update_one.assert_called_once()
        assert result.rating == req.rating
        # Should call $inc on summary table with delta only (5 - 3 = 2)
        summary_tbl.update_one.assert_awaited_once()
        call_kwargs = summary_tbl.update_one.call_args.kwargs
        assert call_kwargs["update"] == {"$inc": {"rating_total": 2}}


# ---------------------------------------------------------------------------
# rate_video – user activity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_video_user_activity_failure_does_not_break(viewer_user: User):
    """If user_activity insert fails, the rating still succeeds."""
    video_id = uuid4()
    req = RatingCreateOrUpdateRequest(rating=4)

    with (
        patch(
            "app.services.rating_service.video_service.get_video_by_id",
            new_callable=AsyncMock,
        ) as mock_get_vid,
        patch(
            "app.services.rating_service.get_table", new_callable=AsyncMock
        ) as mock_get_table,
        patch(
            "app.services.rating_service.record_user_activity",
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ) as mock_record,
    ):
        mock_get_vid.return_value = _make_video(video_id)
        ratings_tbl = AsyncMock()
        summary_tbl = AsyncMock()
        mock_get_table.return_value = summary_tbl
        ratings_tbl.find_one.return_value = None
        ratings_tbl.insert_one.return_value = {}

        result = await rating_service.rate_video(video_id, req, viewer_user, db_table=ratings_tbl)
        assert result.rating == 4
        ratings_tbl.insert_one.assert_called_once()
        mock_record.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_video_new_calls_record_user_activity(viewer_user: User):
    """New rating triggers record_user_activity with activity_type='rate'."""
    video_id = uuid4()
    req = RatingCreateOrUpdateRequest(rating=4)

    with (
        patch(
            "app.services.rating_service.video_service.get_video_by_id",
            new_callable=AsyncMock,
        ) as mock_get_vid,
        patch(
            "app.services.rating_service.get_table", new_callable=AsyncMock
        ) as mock_get_table,
        patch(
            "app.services.user_activity_service.get_table", new_callable=AsyncMock
        ) as mock_ua_get_table,
    ):
        mock_get_vid.return_value = _make_video(video_id)
        ratings_tbl = AsyncMock()
        summary_tbl = AsyncMock()
        mock_get_table.return_value = summary_tbl

        ratings_tbl.find_one.return_value = None
        ratings_tbl.insert_one.return_value = {}

        mock_ua_table = AsyncMock()
        mock_ua_get_table.return_value = mock_ua_table

        await rating_service.rate_video(video_id, req, viewer_user, db_table=ratings_tbl)

        mock_ua_table.insert_one.assert_awaited_once()
        doc = mock_ua_table.insert_one.call_args.args[0] if mock_ua_table.insert_one.call_args.args else mock_ua_table.insert_one.call_args.kwargs
        assert doc["userid"] == str(viewer_user.userid)
        assert doc["activity_type"] == "rate"


@pytest.mark.asyncio
async def test_rate_video_update_calls_record_user_activity(viewer_user: User):
    """Updated rating also triggers record_user_activity."""
    video_id = uuid4()
    req = RatingCreateOrUpdateRequest(rating=5)

    existing_doc = {
        "videoid": str(video_id),
        "userid": str(viewer_user.userid),
        "rating": 3,
        "rating_date": datetime.now(timezone.utc),
    }

    with (
        patch(
            "app.services.rating_service.video_service.get_video_by_id",
            new_callable=AsyncMock,
        ) as mock_get_vid,
        patch(
            "app.services.rating_service.get_table", new_callable=AsyncMock
        ) as mock_get_table,
        patch(
            "app.services.rating_service._update_video_aggregate_rating",
            new_callable=AsyncMock,
        ) as mock_update_agg,
        patch(
            "app.services.user_activity_service.get_table", new_callable=AsyncMock
        ) as mock_ua_get_table,
    ):
        mock_get_vid.return_value = _make_video(video_id)
        ratings_tbl = AsyncMock()
        mock_get_table.return_value = AsyncMock()

        ratings_tbl.find_one.return_value = existing_doc
        ratings_tbl.update_one.return_value = {}

        mock_ua_table = AsyncMock()
        mock_ua_get_table.return_value = mock_ua_table

        await rating_service.rate_video(video_id, req, viewer_user, db_table=ratings_tbl)

        mock_ua_table.insert_one.assert_awaited_once()
        doc = mock_ua_table.insert_one.call_args.args[0] if mock_ua_table.insert_one.call_args.args else mock_ua_table.insert_one.call_args.kwargs
        assert doc["activity_type"] == "rate"


# ---------------------------------------------------------------------------
# Summary fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_video_ratings_summary_with_user(viewer_user: User):
    video_id = uuid4()

    summary_tbl = AsyncMock()
    summary_tbl.find_one.return_value = {"rating_counter": 2, "rating_total": 9}

    ratings_tbl = AsyncMock()
    ratings_tbl.find_one.return_value = {"rating": 5}

    with patch(
        "app.services.rating_service.video_service.get_video_by_id",
        new_callable=AsyncMock,
    ) as mock_get_vid:
        mock_get_vid.return_value = _make_video(video_id)

        summary = await rating_service.get_video_ratings_summary(
            video_id,
            current_user_id=viewer_user.userid,
            ratings_db_table=ratings_tbl,
            summary_db_table=summary_tbl,
        )

        assert summary.averageRating == 4.5
        assert summary.totalRatingsCount == 2
        assert summary.currentUserRating == 5


@pytest.mark.asyncio
async def test_get_video_ratings_summary_no_ratings():
    """Returns None/0 when no counter doc exists in the summary table."""
    video_id = uuid4()

    summary_tbl = AsyncMock()
    summary_tbl.find_one.return_value = None

    with patch(
        "app.services.rating_service.video_service.get_video_by_id",
        new_callable=AsyncMock,
    ) as mock_get_vid:
        mock_get_vid.return_value = _make_video(video_id)

        summary = await rating_service.get_video_ratings_summary(
            video_id,
            summary_db_table=summary_tbl,
        )

        assert summary.averageRating is None
        assert summary.totalRatingsCount == 0
        assert summary.currentUserRating is None


# ---------------------------------------------------------------------------
# _update_video_aggregate_rating – unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_aggregate_new_rating_counter_increment():
    """New rating: $inc counter by 1 and total by rating value."""
    video_id = uuid4()
    summary_tbl = AsyncMock()

    await rating_service._update_video_aggregate_rating(
        video_id, new_rating=4, old_rating=None, summary_db_table=summary_tbl
    )

    summary_tbl.update_one.assert_awaited_once()
    call_kwargs = summary_tbl.update_one.call_args.kwargs
    assert call_kwargs["update"] == {"$inc": {"rating_counter": 1, "rating_total": 4}}
    assert call_kwargs["upsert"] is True


@pytest.mark.asyncio
async def test_update_aggregate_updated_rating_delta():
    """Updated rating: $inc total by delta only, counter unchanged."""
    video_id = uuid4()
    summary_tbl = AsyncMock()

    await rating_service._update_video_aggregate_rating(
        video_id, new_rating=5, old_rating=3, summary_db_table=summary_tbl
    )

    summary_tbl.update_one.assert_awaited_once()
    call_kwargs = summary_tbl.update_one.call_args.kwargs
    assert call_kwargs["update"] == {"$inc": {"rating_total": 2}}
    assert call_kwargs["upsert"] is True
