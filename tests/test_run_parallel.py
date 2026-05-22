"""Tests for run_parallel using a picklable fake backend.

These tests verify the parallel execution machinery (process pool,
result collection, order preservation, error handling) without
requiring phreeqpy. The fake backend lives at module level so it
is picklable.
"""
import pandas as pd
import pytest

from phreeqpy_tools.templates import PhreeqcTemplate
from phreeqpy_tools.tasks import SolutionTask
from phreeqpy_tools.runner import SolutionBatchRunner


# ---------------------------------------------------------------------------
# Module-level picklable fakes
# ---------------------------------------------------------------------------

class FakeBackend:
    """Minimal PhreeqcBackend satisfying the Protocol. Picklable."""

    def __init__(self):
        self._last_input = ""

    def run(self, input: str) -> None:
        self._last_input = input
        if "FAIL_ME" in input:
            raise RuntimeError("simulated PHREEQC failure")

    def get_selected_output_array(self) -> list:
        return [["density"], [1.18]]


def make_fake_backend() -> FakeBackend:
    """Module-level factory — picklable."""
    return FakeBackend()


SIMPLE_COMP = PhreeqcTemplate("    pH {pH}\n    temp {temp}\n")
SIMPLE_RUN = PhreeqcTemplate(
    "SOLUTION 1\n{composition_str}\nSELECTED_OUTPUT\n  -reset false\nEND\n"
)


def _solution_task() -> SolutionTask:
    return SolutionTask(
        task_name="density",
        run_template=SIMPLE_RUN,
        composition_template=SIMPLE_COMP,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSolutionBatchRunnerParallel:
    def test_runs_all_jobs(self):
        df = pd.DataFrame({
            "sample_id": [f"S{i:02d}" for i in range(6)],
            "pH": [7.0 + i * 0.1 for i in range(6)],
            "temp": [25.0] * 6,
        })
        runner = SolutionBatchRunner(task=_solution_task(), id_col="sample_id")
        results = runner.run_parallel(
            df,
            backend_factory=make_fake_backend,
            n_workers=2,
        )
        assert len(results) == 6

    def test_preserves_order_when_requested(self):
        df = pd.DataFrame({
            "sample_id": [f"S{i:02d}" for i in range(6)],
            "pH": [7.0 + i * 0.1 for i in range(6)],
            "temp": [25.0] * 6,
        })
        runner = SolutionBatchRunner(task=_solution_task(), id_col="sample_id")
        results = runner.run_parallel(
            df,
            backend_factory=make_fake_backend,
            n_workers=2,
            preserve_order=True,
        )
        assert [r.id for r in results] == [f"S{i:02d}" for i in range(6)]

    def test_unordered_returns_all_jobs(self):
        df = pd.DataFrame({
            "sample_id": [f"S{i:02d}" for i in range(6)],
            "pH": [7.0 + i * 0.1 for i in range(6)],
            "temp": [25.0] * 6,
        })
        runner = SolutionBatchRunner(task=_solution_task(), id_col="sample_id")
        results = runner.run_parallel(
            df,
            backend_factory=make_fake_backend,
            n_workers=2,
            preserve_order=False,
        )
        # all should arrive, regardless of order
        assert {r.id for r in results} == {f"S{i:02d}" for i in range(6)}