# %% [markdown]
# # Batch parameter sweep example
#
# This notebook shows how to use the simulator from Python directly (no API)
# to run parameter sweeps and analyze results. Open in Jupyter/VS Code or
# convert to `.ipynb` with `jupytext --to ipynb explore.py`.

# %%
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath('.')), 'backend'))
# Or if running from notebooks/ subdirectory:
sys.path.insert(0, os.path.abspath('../backend'))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from simulator import (
    PolicyConfig, FormulaPolicy, PRESETS,
    progressive_multi_home_tax, vacancy_tax,
    run_simulation, POLICY_TEMPLATES,
)

# %% [markdown]
# ## 1. Single scenario

# %%
cfg = PolicyConfig(
    max_loan_years=25,
    max_ltv=0.90,
    construction_rate=0.005,
)
history = run_simulation(cfg, years=50, seed=42)
df = pd.DataFrame(history)
df.tail()

# %% [markdown]
# ## 2. Compare presets

# %%
def cfg_from_preset(name):
    p = PRESETS[name]
    formulas = []
    if p["multi_home_tax"] > 0:
        formulas.append(progressive_multi_home_tax(p["multi_home_tax"]))
    if p["vacancy_tax"] > 0:
        formulas.append(vacancy_tax(p["vacancy_tax"]))
    return PolicyConfig(
        max_loan_years=p["max_loan_years"],
        max_ltv=p["max_ltv"],
        construction_rate=p["construction_rate"],
        public_share=p["public_share"],
        depreciation=p["depreciation"],
        formula_policies=formulas,
    )

frames = []
for name in PRESETS:
    h = run_simulation(cfg_from_preset(name), years=50, seed=42)
    sub = pd.DataFrame(h)
    sub["scenario"] = name
    frames.append(sub)
all_results = pd.concat(frames, ignore_index=True)

# %%
fig, axes = plt.subplots(2, 2, figsize=(12, 7))
metrics = [
    ("homeownership_rate", "Homeownership rate"),
    ("housing_burden_median", "Median housing burden"),
    ("price_to_income", "Price-to-income"),
    ("overburdened_pct", "% overburdened (>40%)"),
]
for ax, (col, title) in zip(axes.flat, metrics):
    for sc, grp in all_results.groupby("scenario"):
        ax.plot(grp["year"], grp[col], label=sc, alpha=0.8, linewidth=2)
    ax.set_title(title)
    ax.set_xlabel("year")
    ax.grid(alpha=0.3)
axes[0,0].legend(loc="best", fontsize=9)
plt.tight_layout()
plt.show()

# %% [markdown]
# ## 3. Parameter sweep: construction rate vs housing burden
#
# A real research use-case: sweep one parameter, hold others fixed, see how
# outcomes change. Replicate over multiple seeds to estimate variability.

# %%
construction_rates = np.linspace(0.002, 0.05, 12)
seeds = [42, 7, 13, 99, 142]

results = []
for cr in construction_rates:
    for s in seeds:
        cfg = PolicyConfig(construction_rate=cr)
        h = run_simulation(cfg, years=50, seed=s,
                           n_households=1000, n_properties=900)
        final = h[-1]
        results.append({
            "construction_rate": cr,
            "seed": s,
            "burden": final["housing_burden_median"],
            "price_to_income": final["price_to_income"],
            "ownership": final["homeownership_rate"],
        })

sweep_df = pd.DataFrame(results)
sweep_df.head()

# %%
agg = sweep_df.groupby("construction_rate").agg(["mean", "std"])
fig, ax = plt.subplots(figsize=(10, 5))
ax.errorbar(agg.index, agg[("burden","mean")], yerr=agg[("burden","std")],
            marker="o", capsize=4, label="Housing burden")
ax2 = ax.twinx()
ax2.errorbar(agg.index, agg[("price_to_income","mean")],
             yerr=agg[("price_to_income","std")],
             marker="s", capsize=4, color="C1", label="Price/income")
ax.set_xlabel("Construction rate (per year)")
ax.set_ylabel("Median housing burden", color="C0")
ax2.set_ylabel("Price-to-income", color="C1")
ax.set_title("Effect of construction rate on outcomes (n_seeds=5, year 50)")
plt.tight_layout()
plt.show()

# %% [markdown]
# ## 4. Custom policy: design and test
#
# Express a new policy idea as a formula, run, evaluate.

# %%
# Idea: tax that escalates *quadratically* on multi-ownership rather than linearly
quad_tax = FormulaPolicy(
    name="Quadratic multi-home tax",
    formula="-p.value * 0.01 * (p.property_index - 1)**2 if p.property_index > 1 else 0",
    slider_value=100, per_prop=True,
)

cfg_lin = PolicyConfig(formula_policies=[progressive_multi_home_tax(100)])
cfg_quad = PolicyConfig(formula_policies=[quad_tax])

h_lin = pd.DataFrame(run_simulation(cfg_lin, years=50, seed=42))
h_quad = pd.DataFrame(run_simulation(cfg_quad, years=50, seed=42))

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(h_lin["year"], h_lin["multi_owner_pct"], label="Linear escalation")
ax.plot(h_quad["year"], h_quad["multi_owner_pct"], label="Quadratic escalation")
ax.set_xlabel("Year"); ax.set_ylabel("% households owning 2+ properties")
ax.legend(); ax.grid(alpha=0.3)
plt.title("Different escalation curves on the multi-home tax")
plt.tight_layout()
plt.show()
