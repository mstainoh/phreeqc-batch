"""Brine mixing example: saturation indices and precipitation screening.

Two solutions are mixed 50/50 and allowed to equilibrate with carbonate
and sulfate minerals. Demonstrates ``MultiSolutionTask`` with
``EQUILIBRIUM_PHASES``.

Run with::

    python examples/brine_mixing.py

Requires phreeqpy and a pitzer.dat (or equivalent) database.
"""
from pathlib import Path
import pandas as pd
from phreeqpy_tools import (
    PhreeqcTemplate,
    MultiSolutionTask,
    PhreeqpyBackend,
)
import phreeqpy.iphreeqc.phreeqc_dll as phreeqc_mod

# ---------------------------------------------------------------------------
# Composition template — minimal: pH, temp, pe, units, ions
# ---------------------------------------------------------------------------

COMP_TEMPLATE = PhreeqcTemplate("""\
    temp    {temp}
    pH      {pH}
    pe      {pe}
    units   {units}
    Ca      {Ca}
    Na      {Na}
    Cl      {Cl}    charge      
    S(6)  AS SO4  {SO4}
    C(+4) AS HCO3    {HCO3}
""")

# ---------------------------------------------------------------------------
# Run template — MIX + EQUILIBRIUM_PHASES + SELECTED_OUTPUT
# ---------------------------------------------------------------------------

MIX_TEMPLATE = PhreeqcTemplate("""\
SOLUTION 1
{solution_1}
SOLUTION 2
{solution_2}

MIX 1
    1   {fraction_1}
    2   {fraction_2}

EQUILIBRIUM_PHASES 1
    Calcite         0   0
    Gypsum          0   0
    Anhydrite       0   0
    Dolomite        0   0

SELECTED_OUTPUT
    -file           mezcla_output.txt
    -reset          false
    -pH             true
    -temperature    true
    -saturation_indices     Calcite Gypsum Anhydrite Dolomite
    -equilibrium_phases     Calcite Gypsum Anhydrite Dolomite
END
""")

# ---------------------------------------------------------------------------
# Compositions
# ---------------------------------------------------------------------------

# Formation water: Ca-SO4 type
units = 'mg/kgw'
formation_water = {
    "temp": 25, "pH": 7.2, "pe": 4, "units": units,
    "Ca": 1000, "SO4": 8000, "Na": 500000, "Cl": 500000, "HCO3": 0,
}

# Recharge water: Ca-HCO3 type, warmer
recharge_water = {
    "temp": 40, "pH": 8.0, "pe": 4, "units": units,
    "Ca": 2000, "SO4": 0, "Na": 200000, "Cl": 200000, "HCO3": 15,
}

# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

task = MultiSolutionTask(
    task_name="brine_mixing",
    run_template=MIX_TEMPLATE,
    composition_templates={
        "solution_1": COMP_TEMPLATE,
        "solution_2": COMP_TEMPLATE,
    },
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    db = 'pitzer'
    DB_PATH = Path(__file__).parent.parent / "databases" / f"{db}.dat"
    assert DB_PATH.exists(), 'Cannot find database path'
    backend = PhreeqpyBackend.create_from_database(DB_PATH)
    result = task.run(
        phreeqc=backend,
        id_="mix_50_50",
        compositions={
            "solution_1": formation_water,
            "solution_2": recharge_water,
        },
        fraction_1=0.5,
        fraction_2=0.5,
    )

    df = result.data
    print(df.to_string(index=False))

    # Minerals that precipitated (moles > 0 means precipitation occurred)
    precip_cols = [c for c in df.columns if c.startswith("d_")]
    if precip_cols:
        print("\n--- Precipitation (mol) ---")
        print(df[precip_cols].to_string(index=False))

    # Saturation indices
    si_cols = [c for c in df.columns if c.startswith("si_")]
    if si_cols:
        print("\n--- Saturation Indices ---")
        print(df[si_cols].to_string(index=False))