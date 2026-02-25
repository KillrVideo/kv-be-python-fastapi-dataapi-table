"""Unit tests for the user_activity_service module."""

import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4, uuid1
from datetime import datetime, timezone

from app.services.user_activity_service import (
    record_user_activity,
    list_user_activity,
    ANONYMOUS_USER_ID,
    USER_ACTIVITY_TABLE_NAME,
    MAX_ACTIVITY_ROWS,
)
from app.models.user_activity import UserActivity


@pytest.mark.asyncio
async def test_record_user_activity_auto_activity_id():
    """record_user_activity generates a uuid1 when activity_id is not provided."""
    mock_table = AsyncMock()
    userid = uuid4()

    await record_user_activity(
        userid=userid,
        activity_type="view",
        db_table=mock_table,
    )

    mock_table.insert_one.assert_awaited_once()
    doc = mock_table.insert_one.call_args[1].get(
        "document", mock_table.insert_one.call_args[0][0]
        if mock_table.insert_one.call_args[0] else mock_table.insert_one.call_args[1]
    )
    # insert_one is called with a positional dict
    insert_call = mock_table.insert_one.call_args
    if insert_call.args:
        doc = insert_call.args[0]
    else:
        doc = insert_call.kwargs

    assert doc["userid"] == str(userid)
    assert doc["activity_type"] == "view"
    assert doc["activity_id"] is not None
    assert doc["day"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")


@pytest.mark.asyncio
async def test_record_user_activity_timestamp_is_isoformat_string():
    """record_user_activity serializes activity_timestamp as an ISO 8601 string."""
    mock_table = AsyncMock()

    await record_user_activity(
        userid=uuid4(),
        activity_type="view",
        db_table=mock_table,
    )

    insert_call = mock_table.insert_one.call_args
    doc = insert_call.args[0] if insert_call.args else insert_call.kwargs
    assert isinstance(doc["activity_timestamp"], str)
    # Verify it is a valid ISO format string by parsing it back
    parsed = datetime.fromisoformat(doc["activity_timestamp"])
    assert parsed.tzinfo is not None


@pytest.mark.asyncio
async def test_record_user_activity_explicit_activity_id():
    """record_user_activity uses the provided activity_id."""
    mock_table = AsyncMock()
    userid = uuid4()
    explicit_id = uuid1()

    await record_user_activity(
        userid=userid,
        activity_type="comment",
        activity_id=explicit_id,
        db_table=mock_table,
    )

    mock_table.insert_one.assert_awaited_once()
    insert_call = mock_table.insert_one.call_args
    doc = insert_call.args[0] if insert_call.args else insert_call.kwargs
    assert doc["activity_id"] == str(explicit_id)
    assert doc["activity_type"] == "comment"


@pytest.mark.asyncio
async def test_record_user_activity_anonymous():
    """record_user_activity works with the anonymous sentinel UUID."""
    mock_table = AsyncMock()

    await record_user_activity(
        userid=ANONYMOUS_USER_ID,
        activity_type="view",
        db_table=mock_table,
    )

    mock_table.insert_one.assert_awaited_once()
    insert_call = mock_table.insert_one.call_args
    doc = insert_call.args[0] if insert_call.args else insert_call.kwargs
    assert doc["userid"] == str(ANONYMOUS_USER_ID)


@pytest.mark.asyncio
async def test_record_user_activity_fetches_table():
    """record_user_activity calls get_table when db_table is None."""
    mock_table = AsyncMock()

    with patch(
        "app.services.user_activity_service.get_table",
        new_callable=AsyncMock,
        return_value=mock_table,
    ) as mock_get_table:
        await record_user_activity(
            userid=uuid4(),
            activity_type="rate",
        )

        mock_get_table.assert_awaited_once_with(USER_ACTIVITY_TABLE_NAME)
        mock_table.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_user_activity_fetches_table():
    """list_user_activity calls get_table when db_table is None."""
    def mock_find(filter=None, **kwargs):
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[])
        return cursor

    mock_table = AsyncMock()
    mock_table.find = mock_find

    with patch(
        "app.services.user_activity_service.get_table",
        new_callable=AsyncMock,
        return_value=mock_table,
    ) as mock_get_table:
        await list_user_activity(userid=uuid4(), page=1, page_size=10)
        mock_get_table.assert_awaited_once_with(USER_ACTIVITY_TABLE_NAME)


@pytest.mark.asyncio
async def test_list_user_activity_returns_paginated_results():
    """list_user_activity returns a page of results and total count."""
    userid = uuid4()
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    rows = [
        {
            "userid": str(userid),
            "day": today_str,
            "activity_type": "view",
            "activity_id": str(uuid1()),
            "activity_timestamp": now.isoformat(),
        },
        {
            "userid": str(userid),
            "day": today_str,
            "activity_type": "comment",
            "activity_id": str(uuid1()),
            "activity_timestamp": now.isoformat(),
        },
    ]

    def mock_find(filter=None, **kwargs):
        cursor = AsyncMock()
        if filter and filter.get("day") == today_str:
            cursor.to_list = AsyncMock(return_value=rows)
        else:
            cursor.to_list = AsyncMock(return_value=[])
        return cursor

    mock_table = AsyncMock()
    mock_table.find = mock_find

    activities, total = await list_user_activity(
        userid=userid,
        page=1,
        page_size=10,
        db_table=mock_table,
    )

    assert total == 2
    assert len(activities) == 2
    assert all(isinstance(a, UserActivity) for a in activities)


@pytest.mark.asyncio
async def test_list_user_activity_with_type_filter():
    """list_user_activity filters by activity_type when provided."""
    userid = uuid4()
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    view_row = {
        "userid": str(userid),
        "day": today_str,
        "activity_type": "view",
        "activity_id": str(uuid1()),
        "activity_timestamp": now.isoformat(),
    }

    def mock_find(filter=None, **kwargs):
        cursor = AsyncMock()
        if filter and filter.get("day") == today_str and filter.get("activity_type") == "view":
            cursor.to_list = AsyncMock(return_value=[view_row])
        else:
            cursor.to_list = AsyncMock(return_value=[])
        return cursor

    mock_table = AsyncMock()
    mock_table.find = mock_find

    activities, total = await list_user_activity(
        userid=userid,
        page=1,
        page_size=10,
        activity_type="view",
        db_table=mock_table,
    )

    assert total == 1
    assert activities[0].activity_type == "view"


@pytest.mark.asyncio
async def test_list_user_activity_empty():
    """list_user_activity returns empty results for unknown users."""
    def mock_find(filter=None, **kwargs):
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[])
        return cursor

    mock_table = AsyncMock()
    mock_table.find = mock_find

    activities, total = await list_user_activity(
        userid=uuid4(),
        page=1,
        page_size=10,
        db_table=mock_table,
    )

    assert total == 0
    assert activities == []


@pytest.mark.asyncio
async def test_list_user_activity_pagination_page_2():
    """list_user_activity correctly returns page 2."""
    userid = uuid4()
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    rows = [
        {
            "userid": str(userid),
            "day": today_str,
            "activity_type": "view",
            "activity_id": str(uuid1()),
            "activity_timestamp": now.isoformat(),
        }
        for _ in range(3)
    ]

    def mock_find(filter=None, **kwargs):
        cursor = AsyncMock()
        if filter and filter.get("day") == today_str:
            cursor.to_list = AsyncMock(return_value=rows)
        else:
            cursor.to_list = AsyncMock(return_value=[])
        return cursor

    mock_table = AsyncMock()
    mock_table.find = mock_find

    activities, total = await list_user_activity(
        userid=userid,
        page=2,
        page_size=2,
        db_table=mock_table,
    )

    assert total == 3
    assert len(activities) == 1  # page 2 with page_size=2, only 1 left


@pytest.mark.asyncio
async def test_list_user_activity_error_in_partition_is_skipped():
    """list_user_activity skips a failing partition and returns remaining results."""
    userid = uuid4()
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    good_row = {
        "userid": str(userid),
        "day": today_str,
        "activity_type": "view",
        "activity_id": str(uuid1()),
        "activity_timestamp": now.isoformat(),
    }

    call_count = 0

    def mock_find(filter=None, **kwargs):
        nonlocal call_count
        cursor = AsyncMock()
        if filter and filter.get("day") == today_str:
            # Today's partition returns good data
            cursor.to_list = AsyncMock(return_value=[good_row])
        else:
            # All other partitions raise an error
            cursor.to_list = AsyncMock(side_effect=Exception("DB timeout"))
        call_count += 1
        return cursor

    mock_table = AsyncMock()
    mock_table.find = mock_find

    activities, total = await list_user_activity(
        userid=userid,
        page=1,
        page_size=10,
        db_table=mock_table,
    )

    # Only the good row should come through; erring partitions are skipped
    assert total == 1
    assert len(activities) == 1
    assert activities[0].activity_type == "view"


@pytest.mark.asyncio
async def test_record_user_activity_db_failure_raises():
    """record_user_activity raises on DB failure; callers must wrap in try/except."""
    mock_table = AsyncMock()
    mock_table.insert_one.side_effect = Exception("DB connection lost")

    with pytest.raises(Exception, match="DB connection lost"):
        await record_user_activity(
            userid=uuid4(),
            activity_type="view",
            db_table=mock_table,
        )


@pytest.mark.asyncio
async def test_record_user_activity_each_activity_type():
    """record_user_activity accepts all activity types: view, comment, rate."""
    for activity_type in ("view", "comment", "rate"):
        mock_table = AsyncMock()
        await record_user_activity(
            userid=uuid4(),
            activity_type=activity_type,
            db_table=mock_table,
        )
        mock_table.insert_one.assert_awaited_once()
        insert_call = mock_table.insert_one.call_args
        doc = insert_call.args[0] if insert_call.args else insert_call.kwargs
        assert doc["activity_type"] == activity_type


@pytest.mark.asyncio
async def test_list_user_activity_per_day_limit_is_bounded():
    """list_user_activity passes a per-partition limit of MAX_ACTIVITY_ROWS//30, not MAX_ACTIVITY_ROWS.

    With 30 partitions the naive limit would allow up to 30 x MAX_ACTIVITY_ROWS rows
    to be fetched before the post-gather trim.  The bounded limit keeps the total
    near MAX_ACTIVITY_ROWS.
    """
    captured_limits: list[int] = []

    def mock_find(filter=None, limit=None, **kwargs):
        if limit is not None:
            captured_limits.append(limit)
        cursor = AsyncMock()
        cursor.to_list = AsyncMock(return_value=[])
        return cursor

    mock_table = AsyncMock()
    mock_table.find = mock_find

    await list_user_activity(userid=uuid4(), page=1, page_size=10, db_table=mock_table)

    expected_limit = max(1, MAX_ACTIVITY_ROWS // 30)
    assert len(captured_limits) == 30, "Expected find() to be called for all 30 partitions"
    assert all(
        lim == expected_limit for lim in captured_limits
    ), f"All per-day limits should be {expected_limit}, got: {set(captured_limits)}"
    # Confirm the per-day limit is strictly less than MAX_ACTIVITY_ROWS so that
    # 30 partitions cannot return more than ~MAX_ACTIVITY_ROWS rows total.
    assert expected_limit < MAX_ACTIVITY_ROWS


@pytest.mark.asyncio
async def test_list_user_activity_page_beyond_data():
    """Requesting a page beyond available data returns empty list with correct total."""
    userid = uuid4()
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    rows = [
        {
            "userid": str(userid),
            "day": today_str,
            "activity_type": "view",
            "activity_id": str(uuid1()),
            "activity_timestamp": now,
        }
        for _ in range(3)
    ]

    def mock_find(filter=None, **kwargs):
        cursor = AsyncMock()
        if filter and filter.get("day") == today_str:
            cursor.to_list = AsyncMock(return_value=rows)
        else:
            cursor.to_list = AsyncMock(return_value=[])
        return cursor

    mock_table = AsyncMock()
    mock_table.find = mock_find

    activities, total = await list_user_activity(
        userid=userid, page=99, page_size=10, db_table=mock_table,
    )

    assert total == 3
    assert activities == []
