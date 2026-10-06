"""Trace persistence — one insert per answered query.

There is no traces API or UI; rows exist for offline SQL analysis (token
spend per session, confidence over time, latency trends).
"""

import structlog

from ragline.storage.metadata_db import _async_session
from ragline.tracing.models import QueryTrace

log = structlog.get_logger()


async def save_trace(trace: QueryTrace) -> None:
    """Insert the finalized trace row (best-effort at call sites)."""
    async with _async_session() as session:
        session.add(trace)
        await session.commit()
    log.debug("trace saved", trace_id=trace.id)
