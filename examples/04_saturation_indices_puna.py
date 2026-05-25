"""Saturation indices over a brine sample table from the Puna region.

Computes saturation indices for the main evaporite minerals (halite, sylvite,
calcite, gypsum, anhydrite) across a set of brines from salars in Argentina,
Chile and Bolivia. Demonstrates the typical batch workflow on real-shape data.

Data source
-----------
Table 5: Average hydrochemical values of the different salars in the Puna
region (Ericksen, 1987). Figures in mg/L.
"""
from io import StringIO
from pathlib import Path

import pandas as pd

from phreeqc_batch import (
    PhreeqcTemplate,
    SolutionTask,
    SolutionBatchRunner,
    PhreeqpyBackend,
    results_to_curve_dict,
    get_database_path
)

# ---------------------------------------------------------------------------
# Raw data — Ericksen (1987), Table 5. Concentrations in mg/L.
# ---------------------------------------------------------------------------

RAW_DATA = """\
Country	Salar	Cl	SO4	HCO3	Na	K	Ca	Mg	Li	B
Argentina	Hombre Muerto	194800	11100	n.d.	121900	9340	1000	268	914	1455
Argentina	Rincon	190500	15990	n.d.	122200	6570	280	2120	350	1609
Argentina	Pocitos	190600	7440	n.d.	123100	3400	600	1290	97	708
Argentina	Pastos Grandes	178700	26080	n.d.	118200	4730	740	2980	440	2220
Argentina	Centenario	192700	19980	n.d.	112300	8170	320	7550	1020	3765
Argentina	Rio Grande	148900	10610	n.d.	92400	3710	800	2600	420	1673
Argentina	Arizaro	190700	8260	n.d.	119500	160	760	1840	160	138
Chile	Atacama1	183100	16140	560	103000	12900	520	6130	760	1705
Chile	Atacama2	182800	25500	220	98000	19500	300	8500	1200	1673
Chile	Atacama3	189500	15900	230	91100	23600	450	9650	1570	1416
Chile	Surire	131380	11430	n.d.	73200	13200	890	3830	540	3700
Chile	Azufrear	172130	87990	0	60000	14960	88	48640	86	740
Chile	Laco	109630	15360	620	62200	4800	820	6251	101	1078
Chile	Huasco	112980	26700	n.d.	65000	13500	610	5880	480	2333
Chile	San Martin	68000	1570	415	30100	2410	8469	1646	170	985
Chile	Ascotan	70000	25000	2900	45000	3530	920	5125	186	2520
Bolivia	Uyuni	191800	13200	592	94900	13500	461	11800	700	1136
Bolivia	Empexa	120000	34100	430	67200	3400	259	8480	213	702
Bolivia	Coipasa	186000	25300	785	100400	9080	253	12120	338	2208
Bolivia	Pastos Grandes	194000	2460	n.d.	101000	14200	3100	3480	1640	3041
Bolivia	Canapa	126000	17900	n.d.	68900	12000	600	1670	712	2011
"""

# ---------------------------------------------------------------------------
# Load and clean
# ---------------------------------------------------------------------------

df = pd.read_csv(StringIO(RAW_DATA), sep="\t")

# Replace "not detected" with zero — PHREEQC needs numeric values.
df = df.replace("n.d.", 0)
ion_cols = ["Cl", "SO4", "HCO3", "Na", "K", "Ca", "Mg", "Li", "B"]
df[ion_cols] = df[ion_cols].astype(float)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

# Composition template: no density, estimated pH (6.5) and temperature — PHREEQC will
# estimate the missing intensive properties. For high-TDS brines this is a
# simplification, but it keeps the example focused on saturation indices.
# Cl is used to balance meq for missing data - remove "charge" to left composition as is

comp_template = PhreeqcTemplate("""\
    units   mg/L
    Cl      {Cl} charge         # remove to left composition as reported
    S(6)    {SO4} as SO4
    C(4)    {HCO3} as HCO3
    Na      {Na}
    K       {K}
    Ca      {Ca}
    Mg      {Mg}
    Li      {Li}
    B       {B} as B
    temp    20
    ph      6.5
""")

# Run template: equilibrate the solution and report saturation indices
# for the main evaporite minerals expected in these systems
si_template = PhreeqcTemplate(r"""
SOLUTION 1
{composition_str}

USER_PUNCH
    -headings density
    10 PUNCH RHO

SELECTED_OUTPUT
    -reset                  false
    -saturation_indices     Halite Sylvite Calcite Gypsum Anhydrite
    -user_punch             true
    -ph                     true
END
""")

# ---------------------------------------------------------------------------
# Task + runner
# ---------------------------------------------------------------------------

task = SolutionTask(
    task_name="saturation_indices",
    run_template=si_template,
    composition_template=comp_template,
)

runner = SolutionBatchRunner(task=task, id_col="Salar")

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    DB_PATH = get_database_path('pitzer')
    backend = PhreeqpyBackend.create_from_database(DB_PATH)

    results = runner.run(df, phreeqc=backend)

    # Collect SI columns into a per-sample table.
    curves = results_to_curve_dict(results)
    si_table = pd.DataFrame({
        sample_id: curve.iloc[0].to_dict()
        for sample_id, curve in curves.items()
    }).T

    print(si_table.round(2).to_string())