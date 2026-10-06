"""Per-stage timing on the trace: where a query's wall time went.

Pipeline code wraps a stage in `with timed_step("name"):`; the milliseconds
accumulate on the request's TraceCollector and are persisted as JSON in
QueryTrace.step_ms.
"""

import asyncio
import json
import sqlite3

import pytest

from ragline.storage import metadata_db
from ragline.tracing.collector import TraceCollector, _current_trace, get_current_trace, timed_step


@pytest.fixture(autouse=True)
def _no_leaked_collector():
    yield
    _current_trace.set(None)


def test_steps_accumulate_across_repeated_use():
    trace = TraceCollector(query="q")
    trace.add_step("rerank", 10.0)
    with timed_step("rerank"):
        pass
    with timed_step("graph"):
        pass

    assert list(trace.steps) == ["rerank", "graph"]
    assert trace.steps["rerank"] >= 10.0
    assert trace.steps["graph"] >= 0.0


def test_step_recorded_when_the_block_raises():
    trace = TraceCollector(query="q")

    with pytest.raises(RuntimeError):
        with timed_step("answer"):
            raise RuntimeError("endpoint down")

    assert "answer" in trace.steps


def test_timed_step_is_a_noop_without_a_trace():
    assert get_current_trace() is None

    with timed_step("rerank"):
        value = 1

    assert value == 1
    assert get_current_trace() is None


def test_timed_step_works_inside_gathered_tasks():
    """Post-passes run under asyncio.gather; each task must still reach the collector."""

    async def run():
        trace = TraceCollector(query="q")

        async def stage(name):
            with timed_step(name):
                await asyncio.sleep(0)

        await asyncio.gather(stage("memory_pass"), stage("confidence_pass"))
        return trace

    trace = asyncio.run(run())

    assert set(trace.steps) == {"memory_pass", "confidence_pass"}


def test_finalize_serialises_steps():
    trace = TraceCollector(query="q")
    trace.add_step("embed_query", 12.345)
    trace.add_step("answer", 2000.04)

    record = trace.finalize()

    assert json.loads(record.step_ms) == {"embed_query": 12.3, "answer": 2000.0}
    # Finalizing deactivates the collector: later stages attach to nothing.
    with timed_step("late"):
        pass
    assert "late" not in trace.steps


def test_finalize_with_no_steps_is_an_empty_object():
    assert TraceCollector(query="q").finalize().step_ms == "{}"


def test_micro_migration_adds_step_ms_to_an_existing_table(tmp_path, monkeypatch):
    """A database created before this column existed gains it at startup."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE querytrace (id VARCHAR PRIMARY KEY, created_at TIMESTAMP, query VARCHAR, "
        "session_id VARCHAR, prompt_tokens INTEGER, completion_tokens INTEGER, total_ms FLOAT, "
        "citation_count INTEGER, confidence_score FLOAT)"
    )
    con.execute("INSERT INTO querytrace (id, query) VALUES ('old-row', 'q')")
    con.commit()
    con.close()

    url = f"sqlite+aiosqlite:///{db}"
    engine = create_async_engine(url)
    monkeypatch.setattr(metadata_db, "_engine", engine)
    monkeypatch.setattr(metadata_db.settings, "database_url", url)

    async def run():
        await metadata_db.init_db()
        await metadata_db.init_db()          # idempotent
        await engine.dispose()

    asyncio.run(run())

    con = sqlite3.connect(db)
    columns = [row[1] for row in con.execute("PRAGMA table_info(querytrace)")]
    old_row = con.execute("SELECT step_ms FROM querytrace WHERE id = 'old-row'").fetchone()
    con.close()
    assert "step_ms" in columns
    assert old_row[0] == "{}"
