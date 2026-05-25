"""phreeqpy_tools — structured PHREEQC workflows over phreeqpy.

Provides template-based input building, typed task execution, Sweep
processing over DataFrames or job lists, and a backend abstraction layer
that decouples the workflow from any specific PHREEQC Python binding.

Typical usage::

    from pathlib import Path
    from phreeqpy_tools import (
        PhreeqcTemplate,
        SolutionTask,
        FullSweepRunner,
        SolutionSweepRunner,
        ParamSweepRunner,
        PhreeqpyBackend,
        DEFAULT_COMPOSITION_TEMPLATE,
        DEFAULT_SOLUTION_RUN_TEMPLATE,
    )

    backend = PhreeqpyBackend.create_from_database(
        Path("phreeqc_database/pitzer.dat")
    )

    task = SolutionTask(
        task_name="density",
        run_template=DEFAULT_SOLUTION_RUN_TEMPLATE,
        composition_template=DEFAULT_COMPOSITION_TEMPLATE,
    )

    runner = SolutionSweepRunner(task=task, id_col="sample_id")
    results = runner.run(df, phreeqc=backend)
"""

from .templates import (
    PhreeqcTemplate,
    DEFAULT_COMPOSITION_TEMPLATE,
    DEFAULT_COMPOSITION_NO_CONDITIONS_TEMPLATE,
    DEFAULT_SOLUTION_RUN_TEMPLATE,
)
from .tasks import (
    BaseTask,
    PhreeqcResult,
    SolutionTask,
    MultiSolutionTask,
)
from .runner import (
    BaseSweepRunner,
    FullSweepRunner,
    SolutionSweepRunner,
    ParamSweepRunner,
    results_to_scalar_df,
    results_to_curve_dict,
)
from .backend import PhreeqcBackend, PhreeqpyBackend

__all__ = [
    # templates
    "PhreeqcTemplate",
    "DEFAULT_COMPOSITION_TEMPLATE",
    "DEFAULT_COMPOSITION_NO_CONDITIONS_TEMPLATE",
    "DEFAULT_SOLUTION_RUN_TEMPLATE",
    # tasks
    "BaseTask",
    "PhreeqcResult",
    "SolutionTask",
    "MultiSolutionTask",
    # runner
    "BaseSweepRunner",
    "FullSweepRunner",
    "SolutionSweepRunner",
    "ParamSweepRunner",
    "results_to_scalar_df",
    "results_to_curve_dict",
    # backend
    "PhreeqcBackend",
    "PhreeqpyBackend",
]