"""Batch density calculation over a DataFrame of brine samples.

Demonstrates SolutionBatchRunner: a table of samples in, a table of
densities out. The runner pulls only the columns the composition
template needs and ignores the rest.
"""
from pathlib import Path

import pandas as pd

from phreeqc_batch import (
    PhreeqcTemplate,
    SolutionTask,
    SolutionBatchRunner,
    PhreeqpyBackend,
    results_to_curve_dict,
)

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

COMP_TEMPLATE = PhreeqcTemplate("""\
    units   {units}
    temp    {temp}
    pH      {pH}
    Na      {Na}
    Cl      {Cl}
    Ca      {Ca}
    Mg      {Mg}
""")

RUN_TEMPLATE = PhreeqcTemplate("""\
SOLUTION 1
{composition_str}

USER_PUNCH
    -headings density
    10 PUNCH RHO

SELECTED_OUTPUT
    -reset false
END
""")

# ---------------------------------------------------------------------------
# Sample table
# ---------------------------------------------------------------------------

# Note: 'notes' is irrelevant to PHREEQC — the runner ignores it
# because it's not in COMP_TEMPLATE.keys().
df = pd.DataFrame([
    {"sample_id": "PW01", "units": "mmol/L", "temp": 25, "pH": 7.0,
     "Na": 100, "Cl": 100, "Ca": 2, "Mg": 1, "notes": "shallow well"},
    {"sample_id": "PW02", "units": "mmol/L", "temp": 25, "pH": 6.8,
     "Na": 200, "Cl": 210, "Ca": 5, "Mg": 3, "notes": "mid depth"},
    {"sample_id": "PW03", "units": "mmol/L", "temp": 25, "pH": 7.2,
     "Na": 500, "Cl": 510, "Ca": 10, "Mg": 5, "notes": "deep brine"},
])

# ---------------------------------------------------------------------------
# Task and runner
# ---------------------------------------------------------------------------

task = SolutionTask(
    task_name="density",
    run_template=RUN_TEMPLATE,
    composition_template=COMP_TEMPLATE,
)

runner = SolutionBatchRunner(task=task, id_col="sample_id")

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    DB_PATH = Path(__file__).parent.parent / "databases" / "pitzer.dat"
    backend = PhreeqpyBackend.create_from_database(DB_PATH)

    results = runner.run(df, phreeqc=backend)

    # Each result.data is a one-row DataFrame with column 'density'.
    # Flatten into a per-sample table:
    curves = results_to_curve_dict(results)
    out = pd.DataFrame({
        "sample_id": list(curves.keys()),
        "density": [df_["density"].iloc[0] for df_ in curves.values()],
    })

    print(out.to_string(index=False))