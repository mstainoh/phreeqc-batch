"""Brine mixing with precipitation screening.

Mixes two brines in different ratios and equilibrates with carbonate
and sulfate minerals. Demonstrates MultiSolutionTask and
MultiSolutionBatchRunner.

The two brines are kept fixed across all mixing ratios; only the
fractions vary per job.
"""
from pathlib import Path

import pandas as pd

from phreeqc_batch import (
    PhreeqcTemplate,
    MultiSolutionTask,
    FullSweepRunner,
    ParamSweepRunner,
    PhreeqpyBackend,
    get_database_path
)

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

COMP_TEMPLATE = PhreeqcTemplate("""\
    units   {units}
    temp    {temp}
    pH      {pH}
    pe      {pe}
    Ca      {Ca}
    Na      {Na}
    Cl      {Cl}
    S(6)    {SO4}
    C(4)    {HCO3}
""")

MIX_RUN_TEMPLATE = PhreeqcTemplate("""\
SOLUTION 1
{solution_1}
SOLUTION 2
{solution_2}

EQUILIBRIUM_PHASES 1
    Calcite     0   0
    Gypsum      0   0
    Anhydrite   0   0

MIX 1
    1   {f1}
    2   {f2}

USER_PUNCH
    -headings density
    10 PUNCH RHO

SELECTED_OUTPUT
    -reset                  false
    -pH                     true
    -temperature            true
    -saturation_indices     Calcite Gypsum Anhydrite
    -user_punch             true
END
""")

# ---------------------------------------------------------------------------
# Compositions
# ---------------------------------------------------------------------------

recharge_water = {
    "units": "mmol/L", "temp": 25, "pH": 7.2, "pe": 4,
    "Ca": 2, "Na": 5, "Cl": 5, "SO4": 2, "HCO3": 0,
}

formation_water = {
    "units": "mmol/L", "temp": 10, "pH": 8.0, "pe": 4,
    "Ca": 40, "Na": 350, "Cl": 335, "SO4": 40, "HCO3": 15,
}

compositions = {
            "solution_1": formation_water,
            "solution_2": recharge_water,
        }
# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

task = MultiSolutionTask(
    task_name="brine_mixing",
    run_template=MIX_RUN_TEMPLATE,
    composition_templates={
        "solution_1": COMP_TEMPLATE,
        "solution_2": COMP_TEMPLATE,
    },
)

# ---------------------------------------------------------------------------
# Jobs: vary the mixing ratio across runs
# ---------------------------------------------------------------------------

jobs = []
for f1 in [0.1, 0.3, 0.5, 0.7, 0.9]:
    jobs.append({
        "id": f"mix_{int(f1*100):02d}_{int((1-f1)*100):02d}",
        "f1": f1,
        "f2": 1 - f1,
    })

runner = ParamSweepRunner(task=task, compositions=compositions)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    DB_PATH = get_database_path('pitzer')
    backend = PhreeqpyBackend.create_from_database(DB_PATH)

    results = runner.run(jobs, phreeqc=backend)

    # Collect saturation indices across all mixing ratios.
    rows = []
    for r in results:
        row = {"id": r.id}
        row.update(r.data.iloc[-1].to_dict())
        rows.append(row)

    summary = pd.DataFrame(rows)
    print(summary.to_string(index=False))