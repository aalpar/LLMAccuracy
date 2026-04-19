"""Tests for the parallel evaluation scheduler."""
import asyncio
from evaluate import run_parallel_benchmark


def _fake_runner(problem):
    """Synchronous fake — scheduler wraps with to_thread."""
    return {
        "id": problem["id"],
        "result": problem["id"] * 2,
    }


def test_parallel_preserves_order():
    """Output order matches input order even when workers finish out of order."""
    problems = [{"id": i} for i in range(10)]
    results = asyncio.run(
        run_parallel_benchmark(problems, runner=_fake_runner, workers=4)
    )
    assert [r["id"] for r in results] == [p["id"] for p in problems]
    assert [r["result"] for r in results] == [p["id"] * 2 for p in problems]


def test_parallel_single_worker_degenerate():
    """workers=1 should still work (falls back to serial)."""
    problems = [{"id": i} for i in range(3)]
    results = asyncio.run(
        run_parallel_benchmark(problems, runner=_fake_runner, workers=1)
    )
    assert len(results) == 3


def test_parallel_empty_problem_list():
    results = asyncio.run(
        run_parallel_benchmark([], runner=_fake_runner, workers=4)
    )
    assert results == []
