"""Brine mixing with precipitation screening.

Mixes two brines in different ratios and equilibrates with carbonate
and sulfate minerals. Demonstrates MultiSolutionTask and
MultiSolutionBatchRunner.

The two brines are kept fixed across all mixing ratios; only the
fractions vary per job.
"""
from pathlib import Path

import pandas as pd

from phreeqpy_tools import (
    PhreeqcTemplate,
    MultiSolutionTask,
    MultiSolutionBatchRunner,
    PhreeqpyBackend,
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

MIX 1
    1   {f1}
    2   {f2}

EQUILIBRIUM_PHASES 1
    Calcite     0   0
    Gypsum      0   0
    Anhydrite   0   0
    Dolomite    0   0

SELECTED_OUTPUT
    -reset                  false
    -pH                     true
    -temperature            true
    -saturation_indices     Calcite Gypsum Anhydrite Dolomite
    -equilibrium_phases     Calcite Gypsum Anhydrite Dolomite
END
""")

# ---------------------------------------------------------------------------
# Compositions
# ---------------------------------------------------------------------------

formation_water = {
    "units": "mmol/L", "temp": 25, "pH": 7.2, "pe": 4,
    "Ca": 10, "Na": 5, "Cl": 5, "SO4": 8, "HCO3": 0,
}

recharge_water = {
    "units": "mmol/L", "temp": 40, "pH": 8.0, "pe": 4,
    "Ca": 2, "Na": 20, "Cl": 20, "SO4": 0, "HCO3": 15,
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
        "compositions": {
            "solution_1": formation_water,
            "solution_2": recharge_water,
        },
        "f1": f1,
        "f2": 1 - f1,
    })

runner = MultiSolutionBatchRunner(task=task)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    DB_PATH = Path(__file__).parent.parent / "databases" / "pitzer.dat"
    backend = PhreeqpyBackend.create_from_database(DB_PATH)

    results = runner.run(jobs, phreeqc=backend)

    # Collect saturation indices across all mixing ratios.
    rows = []
    for r in results:
        # Each result.data has one row per simulation step;
        # for MIX + EQUILIBRIUM_PHASES, this is typically one row.
        row = {"id": r.id}
        row.update(r.data.iloc[0].to_dict())
        rows.append(row)

    summary = pd.DataFrame(rows)
    print(summary.to_string(index=False))