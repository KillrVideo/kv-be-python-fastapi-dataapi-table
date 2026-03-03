from __future__ import annotations

"""Utility helpers for interacting with the Astra Data API tables in a way that
is agnostic to *table* vs. *collection* quirks.

At the time of writing the Data API only supports `countDocuments` on
**collections**.  Invoking the command on a **table** results in a
``DataAPIResponseException`` with error code ``UNSUPPORTED_TABLE_COMMAND``.

`safe_count` wraps the call and transparently falls back to a supplied
client-side count (typically `len(docs)` fetched earlier). This lets service
layers share the same pagination logic regardless of the underlying storage
object.
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator

from astrapy.exceptions.data_api_exceptions import DataAPIResponseException  # type: ignore

__all__ = ["safe_count", "suppress_astrapy_warnings"]

_ASTRAPY_LOGGER = logging.getLogger("astrapy.utils.api_commander")


class _SuppressAstrapyWarnings(logging.Filter):
    """Drop WARNING records whose message contains any of the given substrings.

    astrapy emits WARNINGs for certain operations that we handle or expect
    (e.g. ``UNSUPPORTED_TABLE_COMMAND`` on tables, ``ZERO_FILTER_OPERATIONS``
    for unfiltered queries).  This filter suppresses only the specified codes
    so legitimate warnings still surface.
    """

    def __init__(self, substrings: frozenset[str]) -> None:
        super().__init__()
        self._substrings = substrings

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(s in msg for s in self._substrings)


async def safe_count(
    db_table,
    *,
    query_filter: Dict[str, Any],
    fallback_len: int,
) -> int:
    """Return the number of rows matching *query_filter*.

    If the backing object is a **table** (where ``countDocuments`` is not
    supported) the function silently returns *fallback_len* instead of raising
    an exception.  The same applies to stub collections used in unit-tests.
    """

    _filter = _SuppressAstrapyWarnings(frozenset({"UNSUPPORTED_TABLE_COMMAND"}))
    _ASTRAPY_LOGGER.addFilter(_filter)
    try:
        return await db_table.count_documents(filter=query_filter, upper_bound=10**9)
    except (TypeError, DataAPIResponseException) as exc:
        if isinstance(
            exc, DataAPIResponseException
        ) and "UNSUPPORTED_TABLE_COMMAND" not in str(exc):
            # An unexpected Data API error – surface to caller.
            raise
        return fallback_len
    finally:
        _ASTRAPY_LOGGER.removeFilter(_filter)


@contextmanager
def suppress_astrapy_warnings(*warning_codes: str) -> Iterator[None]:
    """Temporarily suppress astrapy warnings matching any of *warning_codes*.

    Usage::

        with suppress_astrapy_warnings("ZERO_FILTER_OPERATIONS", "IN_MEMORY_SORTING"):
            cursor = db_table.find(...)
            docs = await cursor.to_list()
    """
    _filter = _SuppressAstrapyWarnings(frozenset(warning_codes))
    _ASTRAPY_LOGGER.addFilter(_filter)
    try:
        yield
    finally:
        _ASTRAPY_LOGGER.removeFilter(_filter)
