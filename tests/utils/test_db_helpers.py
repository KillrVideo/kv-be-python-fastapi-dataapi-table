"""Tests for app.utils.db_helpers.safe_count."""

from __future__ import annotations

import logging

import pytest
from unittest.mock import AsyncMock

from astrapy.exceptions.data_api_exceptions import DataAPIResponseException  # type: ignore[import]

from app.utils.db_helpers import safe_count

_ASTRAPY_LOGGER = "astrapy.utils.api_commander"


def _make_exc(error_code: str) -> DataAPIResponseException:
    """Build a DataAPIResponseException whose str() contains the given error code."""
    return DataAPIResponseException(
        error_code,
        command={},
        raw_response={"errors": [{"errorCode": error_code, "message": error_code}]},
        error_descriptors=[],
        warning_descriptors=[],
    )


# ---------------------------------------------------------------------------
# Correct fallback behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_count_returns_fallback_for_unsupported_table_command():
    """Returns fallback_len when the table doesn't support countDocuments."""
    db_table = AsyncMock()
    db_table.count_documents.side_effect = _make_exc("UNSUPPORTED_TABLE_COMMAND")

    result = await safe_count(db_table, query_filter={}, fallback_len=7)

    assert result == 7


@pytest.mark.asyncio
async def test_safe_count_returns_actual_count_when_supported():
    """Returns the real count when count_documents succeeds."""
    db_table = AsyncMock()
    db_table.count_documents.return_value = 42

    result = await safe_count(db_table, query_filter={"userid": "abc"}, fallback_len=3)

    assert result == 42


@pytest.mark.asyncio
async def test_safe_count_propagates_unexpected_data_api_error():
    """Re-raises DataAPIResponseException for unrelated error codes."""
    db_table = AsyncMock()
    db_table.count_documents.side_effect = _make_exc("SOME_OTHER_ERROR")

    with pytest.raises(DataAPIResponseException):
        await safe_count(db_table, query_filter={}, fallback_len=5)


# ---------------------------------------------------------------------------
# Warning suppression — simulates astrapy's real behaviour (log then raise)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_count_does_not_log_warning_for_unsupported_table_command(caplog):
    """UNSUPPORTED_TABLE_COMMAND must NOT produce a WARNING in the logs.

    astrapy logs a WARNING from api_commander *before* raising the exception.
    We simulate that by having the mock emit the warning then raise, matching
    what happens in production when count_documents hits a CQL table.
    """
    astrapy_logger = logging.getLogger(_ASTRAPY_LOGGER)
    exc = _make_exc("UNSUPPORTED_TABLE_COMMAND")

    async def _fake_count_documents(*args, **kwargs):
        astrapy_logger.warning("APICommander about to raise from: UNSUPPORTED_TABLE_COMMAND")
        raise exc

    db_table = AsyncMock()
    db_table.count_documents = _fake_count_documents

    with caplog.at_level(logging.WARNING, logger=_ASTRAPY_LOGGER):
        await safe_count(db_table, query_filter={}, fallback_len=3)

    unsupported_warnings = [
        r for r in caplog.records
        if "UNSUPPORTED_TABLE_COMMAND" in r.getMessage()
        and r.levelno >= logging.WARNING
    ]
    assert unsupported_warnings == [], (
        "safe_count should suppress astrapy's UNSUPPORTED_TABLE_COMMAND warning"
    )
