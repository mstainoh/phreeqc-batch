"""phreeqpy_tools — structured PHREEQC workflows over phreeqpy.

Provides template-based composition building, typed task execution,
batch processing over DataFrames, and a backend abstraction layer
that decouples the workflow from any specific phreeqpy binding.

Typical usage::

    from phreeqpy_tools import (
        PhreeqcTemplate,
        BrineComposition,
        PhreeqcTask,
        PhreeqcBatchRunner,
        create_phreeqcpy_instance,
        DEFAULT_COMPOSITION_TEMPLATE,
        DEFAULT_SOLUTION_RUN_TEMPLATE,
    )

    backend = create_phreeqcpy_instance(Path("phreeqc_database/pitzer.dat"))

    task = PhreeqcTask(
        task_name="density",
        run_template=DEFAULT_SOLUTION_RUN_TEMPLATE,
        composition_template=DEFAULT_COMPOSITION_TEMPLATE,
    )

    runner = PhreeqcBatchRunner(task=task, id_col="sample_id")
    results = runner.run(df, phreeqc=backend)
"""

from .templates import (
    PhreeqcTemplate,
    DEFAULT_COMPOSITION_TEMPLATE,
    DEFAULT_COMPOSITION_NO_CONDITIONS_TEMPLATE,
    DEFAULT_SOLUTION_RUN_TEMPLATE,
)
from .composition import BaseComposition, GenericComposition, BrineComposition
from .tasks import PhreeqcResult, SolutionTask, MultiSolutionTask
from .runner import PhreeqcBatchRunner, results_to_scalar_df, results_to_curve_dict
from .backend import PhreeqcBackend, PhreeqpyBackend, create_phreeqcpy_instance

__all__ = [
    # templates
    "PhreeqcTemplate",
    "DEFAULT_COMPOSITION_TEMPLATE",
    "DEFAULT_COMPOSITION_NO_CONDITIONS_TEMPLATE",
    "DEFAULT_SOLUTION_RUN_TEMPLATE",
    # composition
    "BaseComposition",
    "GenericComposition",
    "BrineComposition",
    # tasks
    "PhreeqcResult",
    "SolutionTask",
    "MultiSolutionTask",
    # runner
    "PhreeqcBatchRunner",
    "results_to_scalar_df",
    "results_to_curve_dict",
    # backend
    "PhreeqcBackend",
    "PhreeqpyBackend",
    "create_phreeqcpy_instance",
]
