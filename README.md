![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

# phreeqc-batch

phreeqc-batch provides a thin but opinionated layer on top of PHREEQC bindings (eg. phreeqpy's IPhreeqc):
template-based input building, typed task execution, and batch processing over DataFrames —
without hiding the PHREEQC input format from you.

## Why

Python is generally used as a wrapper of PHREEQC/IPHREEQC for easier handling of input data (e.g. multiple compositions, variable temperature, etc.) and output results (e.g. table processing, file updating, etc.). PHREEQC does the work, python is simply a convenient tool to simplify I/O automation and routines. This repo provides some tools to simplify this interaction even further with a few simple classes and functions to handle template strings, dataframe processing and dll backend.

## When to use it 
I  developed this tool to wrap phreeqc calculations into a data engineer framework, originally extracted from internal mining geochemistry work. Examples include: track precipitation risks in pipeline and monitor chemical performance evolution during time. It helps interfacing with KPI monitoring and multicomposition simulation when several samples need to be tested. Phreeqc is used as a "black box" of the type composition --> some result, and applied to one or more datasets.

## When NOT to use this
If you only need to run PHREEQC once or twice, just use phreeqpy or phreeqc directly — it's a few more lines but no abstraction overhead. This package helps when you have a chemistry table with N samples and the same simulation to run on each. 

## Core concepts

**`PhreeqcTemplate`** — a Python format string with named placeholders. E.g. `"SOLUTION 1 \nCl {Cl}"`, filled by using `.format`. The class provides a convenient container to fill and validate required fields before formatting so the operation is cleaner.

**`SolutionTask`** — pairs a composition template with a run template. Handles the two-step fill (composition → string → injected into run block), executes PHREEQC, and returns a typed result.

**`MultiSolutionTask`** — similar to `SolutionTask` but allows multiple solutions (e.g. for mixes, reaction transport).

**`SolutionBatchRunner`** / **`MultiSolutionBatchRunner`** — applies a task row by row over a DataFrame, dict, or list of jobs, logging failures without stopping the batch. Supports parallel execution using `concurrent.futures.ProcessPoolExecutor`.

**`PhreeqcBackend`** — a Protocol that decouples the execution layer. The default class is `PhreeqpyBackend`, which wraps phreeqpy's IPhreeqc. Can be swapped to a different binding by the user.

## Installation

```bash
pip install phreeqc-batch
```

Requires Python ≥ 3.10 and phreeqpy.

## Quick start

```python
from pathlib import Path
import pandas as pd
from phreeqc_batch import (
    PhreeqcTemplate,
    SolutionTask,
    SolutionBatchRunner,
    PhreeqpyBackend,
)

# Define what your composition looks like in PHREEQC input.
comp_template = PhreeqcTemplate("""\
    units   {units}
    temp    {temp}
    pH      {pH}
    Na      {Na}
    Cl      {Cl}
""")

# Define what to do with it.
run_template = PhreeqcTemplate("""\
SOLUTION 1
{composition_str}

USER_PUNCH
    -headings density
    10 PUNCH RHO

SELECTED_OUTPUT
    -reset false
END
""")

task = SolutionTask(
    task_name="density",
    run_template=run_template,
    composition_template=comp_template,
)

backend = PhreeqpyBackend.create_from_database(
    Path("databases/pitzer.dat")
)

# Run over a DataFrame of samples.
df = pd.DataFrame([
    {"sample_id": "S01", "units": "mmol/L", "temp": 25, "pH": 7.0, "Na": 100, "Cl": 100},
    {"sample_id": "S02", "units": "mmol/L", "temp": 25, "pH": 7.2, "Na": 500, "Cl": 510},
])

runner = SolutionBatchRunner(task=task, id_col="sample_id")
results = runner.run(df, phreeqc=backend)
```

The runner pulls only the columns the composition template needs, so extra DataFrame columns (notes, dates, lab IDs) are silently ignored.

## Custom templates

Any PHREEQC input block can be wrapped in a `PhreeqcTemplate`:

```python
from phreeqc_batch import PhreeqcTemplate, SolutionTask

si_template = PhreeqcTemplate(r"""
SOLUTION 1
{composition_str}

SELECTED_OUTPUT
  -reset false
  -saturation_indices Calcite Dolomite Gypsum
END
""")

task = SolutionTask(
    task_name="saturation_indices",
    run_template=si_template,
    composition_template=comp_template,
)
```

## Multi-solution tasks (MIX, reaction transport)

```python
from phreeqc_batch import MultiSolutionTask, MultiSolutionBatchRunner

mix_template = PhreeqcTemplate(r"""
SOLUTION 1
{solution_1}
SOLUTION 2
{solution_2}

MIX 1
    1   {f1}
    2   {f2}

EQUILIBRIUM_PHASES 1
    Calcite     0   0
    Gypsum      0   0

SELECTED_OUTPUT
    -reset                  false
    -saturation_indices     Calcite Gypsum
    -equilibrium_phases     Calcite Gypsum
END
""")

task = MultiSolutionTask(
    task_name="mixing",
    run_template=mix_template,
    composition_templates={
        "solution_1": comp_template,
        "solution_2": comp_template,
    },
)

jobs = [
    {
        "id": f"mix_{int(f*100):02d}",
        "compositions": {"solution_1": brine_a, "solution_2": recharge_water},
        "f1": f, "f2": 1 - f,
    }
    for f in [0.1, 0.3, 0.5, 0.7, 0.9]
]

runner = MultiSolutionBatchRunner(task=task)
results = runner.run(jobs, phreeqc=backend)
```

## Parallel execution

For large batches, use `run_parallel`. Each worker process creates and caches its own backend.

```python
def make_backend():
    return PhreeqpyBackend.create_from_database(Path("databases/pitzer.dat"))

results = runner.run_parallel(
    df,
    backend_factory=make_backend,
    n_workers=4,
)
```

The `backend_factory` must be picklable (a module-level function or `staticmethod`, not a lambda).

## Custom backend

If `phreeqpy` ever stops being maintained, or a faster binding shows up, you
can swap the backend by implementing this Protocol — the rest of the package
doesn't care which one you use.

```python
class MyBackend:
    def run(self, input: str) -> None:
        ...
    def get_selected_output_array(self) -> list:
        ...
```

## Examples

See [`examples/`](examples/) for runnable scripts:

- `01_density_single.py` — minimal single-sample density calculation.
- `02_density_batch.py` — batch density over a DataFrame of brine samples.
- `03_brine_mixing.py` — two-brine mixing with carbonate/sulfate equilibration.
- `04_saturation_indices_puna.py` — saturation indices over a public dataset of salars from the Puna region.

## Status

Alpha. The core API (templates, tasks, runners, backend) is stable and tested.
Future work may include additional backend implementations and richer
post-processing utilities. Open to feedback and contributions.

## License

MIT