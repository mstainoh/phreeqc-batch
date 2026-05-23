"""Single-solution density calculation.

The minimal example: load a backend, define a composition template and a
run template, build a SolutionTask, and run it on one composition dict.
"""
from pathlib import Path

from phreeqc_batch import (
    PhreeqcTemplate,
    SolutionTask,
    PhreeqpyBackend,
)

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

# Composition: a simple Na-Cl brine with explicit density and temperature.
COMP_TEMPLATE = PhreeqcTemplate("""\
    units   {units}
    temp    {temp}
    pH      {pH}
    Na      {Na}
    Cl      {Cl}
""")

# Run block: PHREEQC computes solution properties; we punch density (RHO).
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
# Task
# ---------------------------------------------------------------------------

task = SolutionTask(
    task_name="density",
    run_template=RUN_TEMPLATE,
    composition_template=COMP_TEMPLATE,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    DB_PATH = Path(__file__).parent.parent / "databases" / "pitzer.dat"
    backend = PhreeqpyBackend.create_from_database(DB_PATH)

    sample = {
        "units": "mmol/L",
        "temp": 25,
        "pH": 7.0,
        "Na": 100,
        "Cl": 100,
    }

    result = task.run(phreeqc=backend, id_="sample_01", composition=sample)

    print(f"Task: {result.task_name}")
    print(f"ID:   {result.id}")
    print(f"Density = {result.data['density'].iloc[0]:.4f} g/cm3")