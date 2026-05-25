"""Tests for batch runners."""
import pandas as pd
import pytest
from unittest.mock import MagicMock

from phreeqc_batch.templates import PhreeqcTemplate
from phreeqc_batch.tasks import SolutionTask, MultiSolutionTask
from phreeqc_batch.runner import (
    SolutionBatchRunner,
    FullBatchRunner,
    results_to_scalar_df,
    results_to_curve_dict,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_COMP = PhreeqcTemplate("    pH {pH}\n    temp {temp}\n")
SIMPLE_RUN = PhreeqcTemplate(
    "SOLUTION 1\n{composition_str}\nSELECTED_OUTPUT\n  -reset false\nEND\n"
)
MULTI_RUN = PhreeqcTemplate(
    "SOLUTION 1\n{sol_a}\nSOLUTION 2\n{sol_b}\n"
    "MIX 3\n  1 {f1}\n  2 {f2}\nEND\n"
)


def _make_backend(output=None) -> MagicMock:
    backend = MagicMock()
    backend.get_selected_output_array.return_value = output or [["pH"], [7.0]]
    return backend


def _solution_task() -> SolutionTask:
    return SolutionTask(
        task_name="density",
        run_template=SIMPLE_RUN,
        composition_template=SIMPLE_COMP,
    )


def _multi_task() -> MultiSolutionTask:
    return MultiSolutionTask(
        task_name="mixing",
        run_template=MULTI_RUN,
        composition_templates={"sol_a": SIMPLE_COMP, "sol_b": SIMPLE_COMP},
    )


# ---------------------------------------------------------------------------
# SolutionBatchRunner — DataFrame input
# ---------------------------------------------------------------------------

class TestSolutionBatchRunnerDataFrame:
    def test_runs_each_row(self):
        df = pd.DataFrame({
            "sample_id": ["A", "B"],
            "pH": [7.0, 7.5],
            "temp": [25.0, 30.0],
        })
        backend = _make_backend()
        runner = SolutionBatchRunner(task=_solution_task(), id_col="sample_id")
        results = runner.run(df, phreeqc=backend)

        assert len(results) == 2
        assert [r.id for r in results] == ["A", "B"]
        assert backend.run.call_count == 2

    def test_uses_index_when_no_id_col(self):
        df = pd.DataFrame({"pH": [7.0, 7.5], "temp": [25.0, 30.0]}, index=["x", "y"])
        backend = _make_backend()
        runner = SolutionBatchRunner(task=_solution_task())
        results = runner.run(df, phreeqc=backend)

        assert [r.id for r in results] == ["x", "y"]

    def test_extracts_only_template_columns(self):
        """Extra columns in the df must not break the run."""
        df = pd.DataFrame({
            "sample_id": ["A"],
            "pH": [7.0],
            "temp": [25.0],
            "notes": ["this column is irrelevant"],
        })
        backend = _make_backend()
        runner = SolutionBatchRunner(task=_solution_task(), id_col="sample_id")
        results = runner.run(df, phreeqc=backend)

        assert len(results) == 1

    def test_failed_row_does_not_stop_batch(self):
        df = pd.DataFrame({
            "sample_id": ["A", "B", "C"],
            "pH": [7.0, 7.5, 8.0],
            "temp": [25.0, 30.0, 35.0],
        })
        backend = _make_backend()
        # second call raises, others succeed
        backend.run.side_effect = [None, RuntimeError("boom"), None]
        runner = SolutionBatchRunner(task=_solution_task(), id_col="sample_id")
        results = runner.run(df, phreeqc=backend)

        assert len(results) == 2
        assert [r.id for r in results] == ["A", "C"]


# ---------------------------------------------------------------------------
# SolutionBatchRunner — dict input
# ---------------------------------------------------------------------------

class TestSolutionBatchRunnerDict:
    def test_runs_each_entry(self):
        compositions = {
            "A": {"pH": 7.0, "temp": 25.0},
            "B": {"pH": 7.5, "temp": 30.0},
        }
        backend = _make_backend()
        runner = SolutionBatchRunner(task=_solution_task())
        results = runner.run(compositions, phreeqc=backend)

        assert len(results) == 2
        assert {r.id for r in results} == {"A", "B"}


# ---------------------------------------------------------------------------
# SolutionBatchRunner — extra_keys
# ---------------------------------------------------------------------------

class TestSolutionBatchRunnerExtraKeys:
    def test_extra_keys_passed_to_task(self):
        # task with extra placeholder
        run_t = PhreeqcTemplate(
            "SOLUTION 1\n{composition_str}\nREACTION\nHCl {amount}\nEND\n"
        )
        task = SolutionTask(
            task_name="t",
            run_template=run_t,
            composition_template=SIMPLE_COMP,
        )
        df = pd.DataFrame({"pH": [7.0], "temp": [25.0]})
        backend = _make_backend()
        runner = SolutionBatchRunner(task=task, extra_keys={"amount": 0.1})
        results = runner.run(df, phreeqc=backend)

        assert len(results) == 1
        # check the actual input string contains the extra key value
        called_input = backend.run.call_args[0][0]
        assert "HCl 0.1" in called_input


# ---------------------------------------------------------------------------
# MultiSolutionBatchRunner
# ---------------------------------------------------------------------------

class TestMultiSolutionBatchRunner:
    def test_runs_each_job(self):
        jobs = [
            {
                "id": "mix_50_50",
                "compositions": {
                    "sol_a": {"pH": 7.0, "temp": 25.0},
                    "sol_b": {"pH": 8.0, "temp": 20.0},
                },
                "f1": 0.5, "f2": 0.5,
            },
            {
                "id": "mix_70_30",
                "compositions": {
                    "sol_a": {"pH": 7.0, "temp": 25.0},
                    "sol_b": {"pH": 8.0, "temp": 20.0},
                },
                "f1": 0.7, "f2": 0.3,
            },
        ]
        backend = _make_backend()
        runner = FullBatchRunner(task=_multi_task())
        results = runner.run(jobs, phreeqc=backend)

        assert len(results) == 2
        assert [r.id for r in results] == ["mix_50_50", "mix_70_30"]

    def test_uses_index_when_no_id(self):
        jobs = [
            {
                "compositions": {
                    "sol_a": {"pH": 7.0, "temp": 25.0},
                    "sol_b": {"pH": 8.0, "temp": 20.0},
                },
                "f1": 0.5, "f2": 0.5,
            },
        ]
        backend = _make_backend()
        runner = FullBatchRunner(task=_multi_task())
        results = runner.run(jobs, phreeqc=backend)

        assert results[0].id == 0

    def test_raises_if_compositions_missing_in_job(self):
        jobs = [{"id": "bad", "f1": 0.5, "f2": 0.5}]  # no compositions
        backend = _make_backend()
        runner = FullBatchRunner(task=_multi_task())
        with pytest.raises(ValueError, match="missing required 'compositions'"):
            runner.run(jobs, phreeqc=backend)


# ---------------------------------------------------------------------------
# Post-processing utilities
# ---------------------------------------------------------------------------

class TestPostprocess:
    def test_results_to_scalar_df_from_data(self):
        from phreeqc_batch.tasks import PhreeqcResult
        results = [
            PhreeqcResult(id="A", task_name="density", data=1.18),
            PhreeqcResult(id="B", task_name="density", data=1.22),
        ]
        out = results_to_scalar_df(results)
        assert list(out.columns) == ["id", "density"]
        assert out["density"].tolist() == [1.18, 1.22]

    def test_results_to_scalar_df_from_metadata(self):
        from phreeqc_batch.tasks import PhreeqcResult
        results = [
            PhreeqcResult(id="A", task_name="t", data=None, metadata={"si": 0.3}),
        ]
        out = results_to_scalar_df(results, scalar_key="si")
        assert out["si"].tolist() == [0.3]

    def test_results_to_curve_dict(self):
        from phreeqc_batch.tasks import PhreeqcResult
        df_a = pd.DataFrame({"pH": [7, 6]})
        df_b = pd.DataFrame({"pH": [8, 5]})
        results = [
            PhreeqcResult(id="A", task_name="t", data=df_a),
            PhreeqcResult(id="B", task_name="t", data=df_b),
        ]
        out = results_to_curve_dict(results)
        assert set(out.keys()) == {"A", "B"}
        assert out["A"].equals(df_a)