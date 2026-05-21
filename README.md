# phreeqpy-tools

Structured PHREEQC workflows over [phreeqpy](https://github.com/hydrocomputing/phreeqpy).

phreeqpy-tools provides a thin but opinionated layer on top of phreeqpy's IPhreeqc bindings:
template-based input building, typed task execution, and batch processing over DataFrames —
without hiding the PHREEQC input format from you.

## Why

Working with IPhreeqc in Python typically means writing glue code: formatting input strings by hand,
running them, parsing the selected output array, and wiring error messages together.
phreeqpy-tools structures that flow into composable, reusable pieces.

## Core concepts

**`PhreeqcTemplate`** — a Python format string with named placeholders and key introspection.
Validates required fields before formatting so you get a clear error instead of a silent wrong result.

**`PhreeqcTask`** — pairs a composition template with a run template. Handles the two-step fill
(composition → string → injected into run block), executes PHREEQC, and returns a typed result.

**`PhreeqcBatchRunner`** — applies a task row by row over a DataFrame or dict, logging failures
without stopping the batch.

**`PhreeqcBackend`** — a Protocol that decouples the execution layer from phreeqpy.
The default `PhreeqpyBackend` wraps phreeqpy's IPhreeqc. Swap it out if the underlying
binding ever changes.

## Installation

```bash
pip install phreeqpy-tools
```

Requires Python ≥ 3.10 and phreeqpy.

## Quick start

```python
from pathlib import Path
from phreeqpy_tools import (
    BrineComposition,
    PhreeqcTask,
    PhreeqcBatchRunner,
    create_phreeqcpy_instance,
    DEFAULT_COMPOSITION_TEMPLATE,
    DEFAULT_SOLUTION_RUN_TEMPLATE,
    results_to_scalar_df,
)

# create backend (pitzer.dat included in the package)
backend = create_phreeqcpy_instance(Path("phreeqc_database/pitzer.dat"))

# define a task
task = PhreeqcTask(
    task_name="density",
    run_template=DEFAULT_SOLUTION_RUN_TEMPLATE,
    composition_template=DEFAULT_COMPOSITION_TEMPLATE,
)

# run over a DataFrame
runner = PhreeqcBatchRunner(task=task, id_col="sample_id")
results = runner.run(df, phreeqc=backend)
df_density = results_to_scalar_df(results)
```

## Custom templates

Any PHREEQC input block can be wrapped in a `PhreeqcTemplate`:

```python
from phreeqpy_tools import PhreeqcTemplate, PhreeqcTask

si_template = PhreeqcTemplate(r"""
SOLUTION 1
{composition_str}

SELECTED_OUTPUT
  -reset false
  -saturation_indices Calcite Dolomite Gypsum
END
""")

task = PhreeqcTask(
    task_name="saturation_indices",
    run_template=si_template,
    composition_template=DEFAULT_COMPOSITION_TEMPLATE,
)
```

## Custom backend

Implement `PhreeqcBackend` to wrap a different binding:

```python
class MyBackend:
    def run(self, input: str) -> None:
        ...
    def get_selected_output_array(self) -> list:
        ...
```

## Examples

See [`examples/`](examples/) for notebooks covering:

- Saturation indices over a sample set
- Brine mixing and precipitation screening

## License

MIT
