"""Smoke test: run a few scenarios and print final-year metrics."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from simulator import (
    PolicyConfig, FormulaPolicy, PRESETS,
    progressive_multi_home_tax, vacancy_tax,
    run_simulation,
)


def make_cfg(preset_name: str) -> PolicyConfig:
    p = PRESETS[preset_name]
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


def main():
    print(f"{'Scenario':<28} {'Own':>6} {'Burden':>8} {'Over40':>7} {'P/Inc':>6} {'Multi':>7} {'Gini':>6}")
    print("-" * 75)
    for name in ["baseline", "loan10", "tokyo", "vienna", "combined"]:
        cfg = make_cfg(name)
        history = run_simulation(cfg, years=50, seed=42)
        final = history[-1]
        print(f"{name:<28} "
              f"{final['homeownership_rate']*100:>5.1f}% "
              f"{final['housing_burden_median']*100:>7.1f}% "
              f"{final['overburdened_pct']*100:>6.1f}% "
              f"{final['price_to_income']:>5.2f} "
              f"{final['multi_owner_pct']*100:>6.1f}% "
              f"{final['wealth_gini']:>5.2f}")


if __name__ == "__main__":
    main()
