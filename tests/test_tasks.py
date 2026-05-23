"""Tests for task classes: BaseTask, SolutionTask, MultiSolutionTask."""
import pytest
import pandas as pd
from unittest.mock import MagicMock

from phreeqc_batch.templates import PhreeqcTemplate
from phreeqc_batch.tasks import PhreeqcResult, SolutionTask, MultiSolutionTask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_COMP_TEMPLATE = PhreeqcTemplate("    pH {pH}\n    temp {temp}\n")

SIMPLE_RUN_TEMPLATE = PhreeqcTemplate(
    "SOLUTION 1\n{composition_str}\nSELECTED_OUTPUT\n  -reset false\nEND\n"
)

MULTI_RUN_TEMPLATE = PhreeqcTemplate(
    "SOLUTION 1\n{sol_a}\nSOLUTION 2\n{sol_b}\n"
    "MIX 3\n  1 {f1}\n  2 {f2}\n"
    "SELECTED_OUTPUT\n  -reset false\nEND\n"
)

SAMPLE = {"pH": 7.2, "temp": 25.0}


def _make_backend(output_rows: list[list] | None = None) -> MagicMock:
    """Return a mock PhreeqcBackend with a configurable selected output."""
    backend = MagicMock()
    rows = output_rows or [["pH", "temp"], [7.2, 25.0]]
    backend.get_selected_output_array.return_value = rows
    return backend


# ---------------------------------------------------------------------------
# PhreeqcResult
# ---------------------------------------------------------------------------

class TestPhreeqcResult:
    def test_defaults(self):
        r = PhreeqcResult(id="s1", task_name="density", data=1.18)
        assert r.metadata == {}

    def test_stores_dataframe(self):
        df = pd.DataFrame({"density": [1.18]})
        r = PhreeqcResult(id=1, task_name="t", data=df)
        assert isinstance(r.data, pd.DataFrame)


# ---------------------------------------------------------------------------
# SolutionTask — construction
# ---------------------------------------------------------------------------

class TestSolutionTaskConstruction:
    def test_valid_with_composition_template(self):
        task = SolutionTask(
            task_name="t",
            run_template=SIMPLE_RUN_TEMPLATE,
            composition_template=SIMPLE_COMP_TEMPLATE,
        )
        assert task.composition_template is not None

    def test_valid_without_composition_template(self):
        t = PhreeqcTemplate("SOLUTION 1\n    pH {pH}\nEND\n")
        task = SolutionTask(task_name="t", run_template=t)
        assert task.composition_template is None

    def test_raises_if_template_provided_but_key_missing(self):
        run = PhreeqcTemplate("SOLUTION 1\n    pH 7\nEND\n")
        with pytest.raises(ValueError, match="not found in run_template"):
            SolutionTask(
                task_name="t",
                run_template=run,
                composition_template=SIMPLE_COMP_TEMPLATE,
            )

    def test_raises_if_key_present_but_no_template(self):
        with pytest.raises(ValueError, match="no composition_template was provided"):
            SolutionTask(task_name="t", run_template=SIMPLE_RUN_TEMPLATE)

    def test_extra_keys(self):
        run = PhreeqcTemplate(
            "SOLUTION 1\n{composition_str}\nREACTION\nHCl {amount}\nEND\n"
        )
        task = SolutionTask(
            task_name="t",
            run_template=run,
            composition_template=SIMPLE_COMP_TEMPLATE,
        )
        assert task.extra_keys == {"amount"}


# ---------------------------------------------------------------------------
# SolutionTask — get_phreeqc_input
# ---------------------------------------------------------------------------

class TestSolutionTaskInput:
    def test_fills_composition_into_run_template(self):
        task = SolutionTask(
            task_name="t",
            run_template=SIMPLE_RUN_TEMPLATE,
            composition_template=SIMPLE_COMP_TEMPLATE,
        )
        inp = task.get_phreeqc_input(composition=SAMPLE)
        assert "pH 7.2" in inp
        assert "temp 25.0" in inp

    def test_raises_if_composition_missing(self):
        task = SolutionTask(
            task_name="t",
            run_template=SIMPLE_RUN_TEMPLATE,
            composition_template=SIMPLE_COMP_TEMPLATE,
        )
        with pytest.raises(ValueError, match="no composition supplied"):
            task.get_phreeqc_input()

    def test_no_composition_template_uses_kwargs(self):
        run = PhreeqcTemplate("SOLUTION 1\n    pH {pH}\nEND\n")
        task = SolutionTask(task_name="t", run_template=run)
        inp = task.get_phreeqc_input(pH=6.5)
        assert "pH 6.5" in inp


# ---------------------------------------------------------------------------
# SolutionTask — run
# ---------------------------------------------------------------------------

class TestSolutionTaskRun:
    def test_run_returns_phreeqc_result(self):
        task = SolutionTask(
            task_name="density",
            run_template=SIMPLE_RUN_TEMPLATE,
            composition_template=SIMPLE_COMP_TEMPLATE,
        )
        backend = _make_backend([["pH", "temp"], [7.2, 25.0]])
        result = task.run(phreeqc=backend, id_="PW01", composition=SAMPLE)

        assert isinstance(result, PhreeqcResult)
        assert result.id == "PW01"
        assert result.task_name == "density"
        assert isinstance(result.data, pd.DataFrame)
        assert list(result.data.columns) == ["pH", "temp"]

    def test_run_calls_backend(self):
        task = SolutionTask(
            task_name="t",
            run_template=SIMPLE_RUN_TEMPLATE,
            composition_template=SIMPLE_COMP_TEMPLATE,
        )
        backend = _make_backend()
        task.run(phreeqc=backend, composition=SAMPLE)
        backend.run.assert_called_once()

    def test_run_propagates_backend_error(self):
        task = SolutionTask(
            task_name="t",
            run_template=SIMPLE_RUN_TEMPLATE,
            composition_template=SIMPLE_COMP_TEMPLATE,
        )
        backend = _make_backend()
        backend.run.side_effect = RuntimeError("PHREEQC failed")
        with pytest.raises(RuntimeError, match="PHREEQC failed"):
            task.run(phreeqc=backend, composition=SAMPLE)


# ---------------------------------------------------------------------------
# MultiSolutionTask — construction
# ---------------------------------------------------------------------------

class TestMultiSolutionTaskConstruction:
    def test_valid(self):
        task = MultiSolutionTask(
            task_name="mixing",
            run_template=MULTI_RUN_TEMPLATE,
            composition_templates={
                "sol_a": SIMPLE_COMP_TEMPLATE,
                "sol_b": SIMPLE_COMP_TEMPLATE,
            },
        )
        assert task.extra_keys == {"f1", "f2"}

    def test_raises_if_key_missing_from_run_template(self):
        with pytest.raises(ValueError, match="not found in run_template"):
            MultiSolutionTask(
                task_name="mixing",
                run_template=MULTI_RUN_TEMPLATE,
                composition_templates={
                    "sol_a": SIMPLE_COMP_TEMPLATE,
                    "nonexistent": SIMPLE_COMP_TEMPLATE,
                },
            )


# ---------------------------------------------------------------------------
# MultiSolutionTask — get_phreeqc_input
# ---------------------------------------------------------------------------

class TestMultiSolutionTaskInput:
    def setup_method(self):
        self.task = MultiSolutionTask(
            task_name="mixing",
            run_template=MULTI_RUN_TEMPLATE,
            composition_templates={
                "sol_a": SIMPLE_COMP_TEMPLATE,
                "sol_b": SIMPLE_COMP_TEMPLATE,
            },
        )

    def test_fills_both_compositions(self):
        inp = self.task.get_phreeqc_input(
            compositions={"sol_a": SAMPLE, "sol_b": {"pH": 8.0, "temp": 20.0}},
            f1=0.7, f2=0.3,
        )
        assert "pH 7.2" in inp
        assert "pH 8.0" in inp
        assert "0.7" in inp

    def test_raises_if_composition_missing(self):
        with pytest.raises(ValueError, match="missing composition for key"):
            self.task.get_phreeqc_input(
                compositions={"sol_a": SAMPLE},
                f1=0.7, f2=0.3,
            )


# ---------------------------------------------------------------------------
# MultiSolutionTask — run
# ---------------------------------------------------------------------------

class TestMultiSolutionTaskRun:
    def test_run_returns_phreeqc_result(self):
        task = MultiSolutionTask(
            task_name="mixing",
            run_template=MULTI_RUN_TEMPLATE,
            composition_templates={
                "sol_a": SIMPLE_COMP_TEMPLATE,
                "sol_b": SIMPLE_COMP_TEMPLATE,
            },
        )
        backend = _make_backend([["SI_Calcite"], [0.42]])
        result = task.run(
            phreeqc=backend,
            id_="mix_01",
            compositions={"sol_a": SAMPLE, "sol_b": {"pH": 8.0, "temp": 20.0}},
            f1=0.7, f2=0.3,
        )
        assert isinstance(result, PhreeqcResult)
        assert result.id == "mix_01"
        assert "SI_Calcite" in result.data.columns