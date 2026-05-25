"""Acidification of a lithium brine with concentrated sulfuric acid.

Simulates stepwise addition of H₂SO₄ (98 % w/w, ~18.4 mol/L) to a
Salar de Atacama brine (Cl-dominant, high Li). Tracks pH drop, sulfate
mineral saturation indices, and precipitation as acid is added.

Demonstrates a single-solution PHREEQC workflow using ``SolutionTask``
with a REACTION block. The composition template fills the brine; the
acid dosing lives in the run template as fixed parameters.

Key geochemical notes:

- HCO₃ acts as the primary pH buffer: it is consumed first, so the pH
  drops slowly until the carbonate buffer is exhausted, then plummets.
- B(OH)₄⁻ / B(OH)₃ provides a secondary buffer.
- Adding SO₄ via H₂SO₄ pushes Gypsum / Anhydrite towards saturation,
  especially with Ca²⁺ already present. Watch for SI > 0 indicating
  scaling risk.
"""
from pathlib import Path

import pandas as pd

from phreeqc_batch import (
    PhreeqcTemplate,
    SolutionTask,
    PhreeqpyBackend,
    get_database_path
)

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
ACID_CONC_MOL_PER_L = 18.38

COMP_TEMPLATE = PhreeqcTemplate("""\
    density {density}
    temp    {temp}
    pH      {pH}
    units   mg/kgw
    Na      {Na}
    K       {K}
    Ca      {Ca}
    Mg      {Mg}
    Cl      {Cl}   charge
    S(6)    {SO4}  as SO4
    B       {B}    as B
    Li      {Li}
    C(4)    {HCO3} as HCO3
""")

# reaction template
ACID_RUN_TEMPLATE = PhreeqcTemplate("""\
SOLUTION 1  Brine sample
{composition_str}

    USER_PUNCH
    -headings pH H2SO4_vol_mL B HCO3 CO2_as_HCO3 DIC_as_HCO3 Cl SO4 Cl_SO4 a_w Density
    10 cl = TOT("Cl") * GFW("Cl") * 1000
    20 so4 = TOT("S(6)") * GFW("SO4") * 1000
    30 ratio = cl / so4
    31 pH = -LA("H+")
    37 a_w = ACT("H2O")
    50 h2so4_vol = RXN * GFW("H2SO4") / {acid_conc_pct} / {acid_density} 
    60 b = TOT("B") * GFW("B") * 1000
    70 hco3 = MOL("HCO3-") * GFW("HCO3") * 1000
    80 co2 = MOL("CO2") * GFW("HCO3") * 1000
    90 dic = TOT("C(4)") * GFW("HCO3") * 1000
    100 PUNCH pH, h2so4_vol, b, hco3, co2, dic, cl, so4, ratio, a_w, RHO

    SELECTED_OUTPUT
      -reset False
      -solution true
      -pH true
      -saturation_indices Halite Gypsum Calcite
    END

USE SOLUTION 1

EQUILIBRIUM_PHASES 1
    Gypsum      0   0
    Anhydrite   0   0
    Calcite     0   0

REACTION 1
    H2SO4   1.0
    {acid_total_mol} in {n_steps} steps
""")

# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

task = SolutionTask(
    task_name="acidification",
    run_template=ACID_RUN_TEMPLATE,
    composition_template=COMP_TEMPLATE,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    DB_PATH = get_database_path('pitzer')
    backend = PhreeqpyBackend.create_from_database(DB_PATH)

    # Salar de Atacama brine (representative, mg/kgw).
    brine = {
        "density": 1.22,
        "temp": 25,
        "pH": 6.5,
        "Na": 103000,
        "K": 12900,
        "Ca": 520,
        "Mg": 6130,
        "Cl": 183100,
        "SO4": 16140,
        "B": 1705,
        "Li": 760,
        "HCO3": 560,
    }

    # Dosing: ~0.05 mol H2SO4 per kg of water, in steps.
    acid_total_mol = 0.05
    n_steps = 30

    # H2SO4 98% w/w physical properties for volume conversion in USER_PUNCH.
    acid_conc_pct = 0.98    # mass fraction
    acid_density = 1.84     # g/mL

    result = task.run(
        phreeqc=backend,
        id_="atacama_acid",
        composition=brine,
        acid_total_mol=acid_total_mol,
        n_steps=n_steps,
        acid_conc_pct=acid_conc_pct,
        acid_density=acid_density,
    )

    df = result.data

    # First row is the unreacted brine (from SOLUTION 1 → END).
    # Subsequent rows are the REACTION steps.
    print(f"Task: {result.task_name}")
    print(f"ID:   {result.id}")
    print(f"Rows: {len(df)} (1 initial + {n_steps} reaction steps)")
    print()

    display_cols = [c for c in df.columns if c in (
        "pH", "H2SO4_vol_mL", "HCO3", "CO2_as_HCO3", "DIC_as_HCO3",
        "B", "Cl", "SO4", "Cl_SO4", "a_w", "Density",
    )]
    print(df.round(3).to_string(index=False))