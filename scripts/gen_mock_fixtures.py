#!/usr/bin/env python3
"""Generate static fixtures for the GitHub Pages *demo mode* mock backend.

The real app is a FastAPI backend (see backend/) plus a JS frontend. GitHub
Pages can only serve static files, so it cannot run the simulator. This script
runs the real backend endpoints once, offline, and writes their JSON responses
to a directory of static files. The Pages build then ships those alongside
`frontend/mock-api.js`, which intercepts `fetch('/api/...')` and serves them —
so the published demo shows *genuine* simulator output for the built-in
presets, with a banner making clear it is precomputed.

This is a convenience mirror, not the product. Custom slider values, custom
policies and arbitrary finance scenarios need the real backend — see HOSTING.md.

Usage:
    python scripts/gen_mock_fixtures.py --out frontend/mock

Deterministic: every run uses fixed seeds, so output is stable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Make the backend package importable regardless of CWD.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from simulator import (  # noqa: E402
    PRESETS,
    POLICY_TEMPLATES,
    PolicyConfig,
    progressive_multi_home_tax,
    run_simulation,
    vacancy_tax,
)
from finance import (  # noqa: E402
    Assumptions,
    Scenario,
    compare,
    forecast_prices,
    get_series,
    list_series,
)

# Default world size — matches the frontend's Sim-settings defaults, so a
# freshly-loaded demo page produces exactly the precomputed baseline.
N_HH, N_PROP, YEARS, SEED = 2000, 1800, 50, 42

# The structural fields that distinguish one preset from another. The mock
# fingerprints an incoming /api/simulate request on these to pick a fixture.
SIG_FIELDS = ["max_loan_years", "max_ltv", "construction_rate",
              "public_share", "depreciation", "multi_home_tax", "vacancy_tax"]


def preset_signature(p: dict) -> str:
    return "|".join(f"{k}={p.get(k)}" for k in SIG_FIELDS)


def cfg_from_preset(p: dict) -> PolicyConfig:
    formulas = []
    if p.get("multi_home_tax", 0) > 0:
        formulas.append(progressive_multi_home_tax(p["multi_home_tax"]))
    if p.get("vacancy_tax", 0) > 0:
        formulas.append(vacancy_tax(p["vacancy_tax"]))
    return PolicyConfig(
        max_loan_years=p["max_loan_years"], max_ltv=p["max_ltv"],
        construction_rate=p["construction_rate"], public_share=p["public_share"],
        depreciation=p["depreciation"], formula_policies=formulas,
    )


# Finance-page preset scenario groups, mirrored from frontend/finance.js so the
# comparator shows real numbers on load. The one loaded first is the default.
FINANCE_GROUPS = {
    "Loan length": [
        dict(name="10-year loan", kind="buy_now", home_price=250000, down_payment=50000, loan_years=10, mortgage_rate=0.035),
        dict(name="40-year loan", kind="buy_now", home_price=250000, down_payment=50000, loan_years=40, mortgage_rate=0.035),
    ],
    "Rent vs buy": [
        dict(name="Buy now", kind="buy_now", home_price=250000, down_payment=50000, loan_years=25, mortgage_rate=0.035),
        dict(name="Rent 3y then buy", kind="rent_then_buy", home_price=250000, down_payment=50000, loan_years=25, mortgage_rate=0.035, wait_years=3),
    ],
}


def gen(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"note": "Precomputed demo fixtures. See HOSTING.md for the live backend.",
                "simulate": {}, "finance_default": "Loan length"}

    def write(name: str, obj) -> None:
        path = os.path.join(out_dir, name)
        with open(path, "w") as f:
            json.dump(obj, f, separators=(",", ":"))
        print(f"  {name}  ({os.path.getsize(path)} bytes)")

    print("static GET endpoints:")
    write("presets.json", PRESETS)
    write("templates.json", POLICY_TEMPLATES)
    write("historical-series.json", {"series": list_series()})

    print("simulate (one per preset):")
    for pname, p in PRESETS.items():
        hist = run_simulation(cfg_from_preset(p), years=YEARS,
                              n_households=N_HH, n_properties=N_PROP, seed=SEED)
        fname = f"simulate-{pname}.json"
        write(fname, {"history": hist, "compile_errors": [],
                      "demo_preset": pname})
        manifest["simulate"][preset_signature(p)] = fname

    print("finance comparator (preset groups):")
    a = Assumptions()
    finance_fixtures = {}
    for gname, specs in FINANCE_GROUPS.items():
        scs = [Scenario(**s) for s in specs]
        finance_fixtures[gname] = compare(scs, a, None)
    write("finance-groups.json", finance_fixtures)

    print("forecasts (real historical series):")
    fc = {}
    for entry in list_series():
        key = entry["key"]
        s = get_series(key)
        r = forecast_prices(history=[float(x) for x in s["index"]],
                            income_history=None, horizon=10, pti_anchor=5.0, seed=0)
        r["series_label"] = s["label"]
        r["series_years"] = s["years"]
        r["series_note"] = s["note"]
        r["series_source"] = s["source"]
        fc[key] = r
    write("forecast-historical.json", fc)

    write("manifest.json", manifest)
    print(f"\nWrote fixtures to {out_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "frontend", "mock"),
                    help="output directory for fixture JSON files")
    gen(ap.parse_args().out)
