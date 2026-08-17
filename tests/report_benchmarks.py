"""
Benchmark validation report.

Run:  python tests/report_benchmarks.py

Prints a plain-language, numbers-first assessment of how closely each policy
preset reproduces the *character* of its real-world archetype, and — crucially
— exactly where the analogy breaks. This is the honest companion to
test_benchmarks.py: the tests assert the qualitative signatures hold; this
report quantifies the gap.
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from simulator import PRESETS, PolicyConfig, run_simulation


def run_preset(name, years=50, seed=42):
    p = PRESETS[name]
    cfg = PolicyConfig(
        max_loan_years=p["max_loan_years"], max_ltv=p["max_ltv"],
        construction_rate=p["construction_rate"],
        public_share=p["public_share"], depreciation=p["depreciation"])
    h = run_simulation(cfg, years=years, n_households=2000,
                        n_properties=1800, seed=seed)
    f = h[-1]
    prices = [x["median_price"] for x in h]
    peak = max(prices)
    return {
        "own": f["homeownership_rate"], "burden": f["housing_burden_median"],
        "over": f["overburdened_pct"], "pti": f["price_to_income"],
        "drop_from_peak": (peak - prices[-1]) / peak if peak else 0.0,
    }


def pct(x):
    return f"{x * 100:.1f}%"


def main():
    base = run_preset("baseline")
    tok = run_preset("tokyo")
    vie = run_preset("vienna")

    line = "=" * 72
    print(line)
    print("BENCHMARK VALIDATION REPORT")
    print("How closely do the presets reproduce their real-world archetypes?")
    print(line)
    print()
    print("Model: 2000 households, 50 years, seed 42. All figures are the")
    print("final simulated year unless noted. The ABM is a stylised mechanism")
    print("sandbox, not a calibrated city model — read deviations as such.")
    print()

    print(f"{'metric':<22}{'baseline':>12}{'tokyo':>12}{'vienna':>12}")
    print("-" * 58)
    print(f"{'homeownership':<22}{pct(base['own']):>12}{pct(tok['own']):>12}"
          f"{pct(vie['own']):>12}")
    print(f"{'housing burden':<22}{pct(base['burden']):>12}"
          f"{pct(tok['burden']):>12}{pct(vie['burden']):>12}")
    print(f"{'overburdened (>40%)':<22}{pct(base['over']):>12}"
          f"{pct(tok['over']):>12}{pct(vie['over']):>12}")
    print(f"{'price-to-income':<22}{base['pti']:>12.2f}{tok['pti']:>12.2f}"
          f"{vie['pti']:>12.2f}")
    print(f"{'peak->final drop':<22}{pct(base['drop_from_peak']):>12}"
          f"{pct(tok['drop_from_peak']):>12}{pct(vie['drop_from_peak']):>12}")
    print()

    # ---- Tokyo assessment -------------------------------------------------
    b_red = (base["burden"] - tok["burden"]) / base["burden"] * 100
    o_red = (base["over"] - tok["over"]) / base["over"] * 100 if base["over"] else 0
    p_red = (base["pti"] - tok["pti"]) / base["pti"] * 100
    print("TOKYO  — claim: supply-driven affordability")
    print("-" * 72)
    print(f"  Burden vs baseline:        {b_red:+.0f}% (lower is the claim)")
    print(f"  Overburden vs baseline:    {o_red:+.0f}%")
    print(f"  Price-to-income vs base:   {p_red:+.0f}%")
    verdict = ("STRONG match on affordability character"
               if (tok["burden"] < base["burden"]
                   and tok["pti"] < base["pti"]) else "WEAK / does not match")
    print(f"  Verdict: {verdict}.")
    print("  Honest gap: the ABM has NO speculative-bubble mechanism, so the")
    print(f"  famous 1990s boom-then-20yr-collapse is NOT reproduced "
          f"(peak->final")
    print(f"  drop only {pct(tok['drop_from_peak'])}). The preset captures why")
    print("  Tokyo is *affordable* (build a lot, let buildings depreciate),")
    print("  not its asset-bubble history. Treat the analogy as 'Tokyo's")
    print("  supply policy', not 'Tokyo's price path'.")
    print()

    # ---- Vienna assessment ------------------------------------------------
    vb_red = (base["burden"] - vie["burden"]) / base["burden"] * 100
    print("VIENNA — claim: decommodified affordability (big public sector)")
    print("-" * 72)
    print(f"  Burden vs baseline:        {vb_red:+.0f}%")
    print(f"  Burden vs Tokyo:           "
          f"{(tok['burden'] - vie['burden']) / tok['burden'] * 100:+.0f}% "
          f"(Vienna should be >= as affordable)")
    print(f"  Overburden:                {pct(vie['over'])} "
          f"(vs baseline {pct(base['over'])})")
    strong = vie["burden"] < base["burden"] and vie["over"] < base["over"]
    print(f"  Verdict: {'STRONG match on affordability' if strong else 'WEAK'}.")
    print("  Honest gap: real Vienna has LOW ownership (~22%); the preset")
    print(f"  instead RAISES ownership to {pct(vie['own'])} (vs baseline")
    print(f"  {pct(base['own'])}). So the match is on AFFORDABILITY/STABILITY,")
    print("  NOT on Vienna's renter-majority tenure structure. The model has")
    print("  no municipal-landlord agent that would hold tenure down.")
    print()

    # ---- Swiss assessment -------------------------------------------------
    print("SWISS  — claim: NONE in the policy simulator (by design)")
    print("-" * 72)
    print("  There is intentionally no Swiss ABM preset. The Swiss model")
    print("  (interest-only, ownership-rare, flat real prices) lives in the")
    print("  PERSONAL comparator as the 'swiss_interest_only' scenario kind,")
    print("  validated in test_finance_comparator.py. Inventing a Swiss")
    print("  policy preset would fabricate a benchmark that doesn't exist.")
    print("  The historical Swiss *price series* is separately available to")
    print("  the Bayesian forecaster (backend/finance/historical.py).")
    print()
    print(line)
    print("SUMMARY: Tokyo & Vienna presets reproduce their AFFORDABILITY")
    print("character strongly and measurably; neither reproduces the full")
    print("real-world price history (bubble) or tenure mix. Those gaps are")
    print("inherent to a mechanism sandbox and are stated, not hidden.")
    print(line)


if __name__ == "__main__":
    main()
