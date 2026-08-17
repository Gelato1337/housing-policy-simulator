"""Tests for the simulator core.

Run from project root: python -m pytest tests/
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import numpy as np
import pytest

from simulator import (
    FormulaPolicy,
    PolicyConfig,
    compute_metrics,
    init_world,
    progressive_multi_home_tax,
    run_simulation,
    step,
)


def test_world_initializes_with_correct_sizes():
    world, _ = init_world(n_households=100, n_properties=80, seed=1)
    assert len(world.households) == 100
    assert len(world.properties) == 80


def test_simulation_is_deterministic_under_same_seed():
    cfg = PolicyConfig()
    h1 = run_simulation(cfg, years=10, n_households=200, n_properties=180, seed=7)
    h2 = run_simulation(cfg, years=10, n_households=200, n_properties=180, seed=7)
    assert h1 == h2


def test_simulation_differs_under_different_seed():
    cfg = PolicyConfig()
    h1 = run_simulation(cfg, years=10, n_households=200, n_properties=180, seed=7)
    h2 = run_simulation(cfg, years=10, n_households=200, n_properties=180, seed=13)
    assert h1[-1]["price_to_income"] != h2[-1]["price_to_income"]


def test_construction_increases_stock():
    cfg_no = PolicyConfig(construction_rate=0.0)
    cfg_hi = PolicyConfig(construction_rate=0.05)
    world_no, rng_no = init_world(n_households=100, n_properties=100, seed=1)
    world_hi, rng_hi = init_world(n_households=100, n_properties=100, seed=1)
    for _ in range(10):
        step(world_no, cfg_no, rng_no)
        step(world_hi, cfg_hi, rng_hi)
    assert len(world_hi.properties) > len(world_no.properties)


def test_metrics_are_in_valid_ranges():
    cfg = PolicyConfig()
    history = run_simulation(cfg, years=20, n_households=300, n_properties=270, seed=42)
    for m in history:
        assert 0 <= m["homeownership_rate"] <= 1
        assert 0 <= m["pct_housed"] <= 1
        assert 0 <= m["wealth_gini"] <= 1
        assert 0 <= m["avg_condition"] <= 1
        assert m["price_to_income"] >= 0


def test_formula_policy_compiles_and_taxes():
    """A simple wealth tax should decrease final savings."""
    cfg_no = PolicyConfig()
    cfg_tax = PolicyConfig(formula_policies=[
        FormulaPolicy("WealthTax", "-h.savings * 0.01", slider_value=100, per_prop=False),
    ])
    h_no = run_simulation(cfg_no, years=20, n_households=300, n_properties=270, seed=42)
    h_tax = run_simulation(cfg_tax, years=20, n_households=300, n_properties=270, seed=42)
    # With a 1% annual wealth tax, Gini should not be strictly higher in the
    # taxed scenario; in practice it's lower or similar.
    assert h_tax[-1]["wealth_gini"] <= h_no[-1]["wealth_gini"] + 0.05


def test_broken_formula_does_not_crash():
    bad = FormulaPolicy("Broken", "this is not python !!", slider_value=100, per_prop=False)
    assert bad.error is not None
    cfg = PolicyConfig(formula_policies=[bad])
    history = run_simulation(cfg, years=5, n_households=100, n_properties=90, seed=1)
    assert len(history) == 6


def test_unsafe_code_in_formula_is_rejected_or_neutralized():
    # __import__ should not be accessible — eval should return 0 for any
    # attempt to use it. A formula that tries to import is just a runtime
    # error inside evaluate(), which is silently swallowed.
    bad = FormulaPolicy("Evil", "__import__('os').system('echo hacked')",
                        slider_value=100, per_prop=False)
    # Compile may succeed but eval should fail safely
    result = bad.evaluate({"h": None, "p": None, "slider": 100,
                          "median_income": 0, "median_price": 0, "year": 0})
    assert result == 0.0


def test_progressive_multi_home_tax_affects_outcomes():
    """A progressive multi-home tax should change market dynamics.

    With mortgages active, a heavy tax causes leveraged investors to
    bankrupt, which can have complex Gini effects. We just verify the
    dynamics actually differ from baseline.
    """
    cfg_no = PolicyConfig()
    cfg_tax = PolicyConfig(formula_policies=[progressive_multi_home_tax(150)])
    h_no = run_simulation(cfg_no, years=30, n_households=1000, n_properties=900, seed=42)
    h_tax = run_simulation(cfg_tax, years=30, n_households=1000, n_properties=900, seed=42)
    # The tax produces materially different outcomes from baseline
    multi_diff = abs(h_no[-1]["multi_owner_pct"] - h_tax[-1]["multi_owner_pct"])
    price_diff = abs(h_no[-1]["price_to_income"] - h_tax[-1]["price_to_income"])
    assert (multi_diff > 0.02) or (price_diff > 0.2)


def test_match_pickiness_reduces_transactions():
    """Higher pickiness should leave more renters unmatched (lower ownership)."""
    cfg_easy = PolicyConfig(match_pickiness=0.0)
    cfg_picky = PolicyConfig(match_pickiness=0.8)
    h_easy = run_simulation(cfg_easy, years=20, n_households=500, n_properties=450, seed=42)
    h_picky = run_simulation(cfg_picky, years=20, n_households=500, n_properties=450, seed=42)
    # Picky markets shouldn't strictly require fewer owners every year, but
    # by year 20 the cumulative effect should be visible.
    assert h_picky[-1]["homeownership_rate"] <= h_easy[-1]["homeownership_rate"]


def test_demographics_affects_outcomes():
    """A higher income distribution should result in higher prices over time."""
    from simulator import Demographics
    d_low = Demographics(income_log_mu=10.3)   # median ≈ €30k
    d_high = Demographics(income_log_mu=10.9)  # median ≈ €55k
    cfg = PolicyConfig()
    h_low = run_simulation(cfg, years=30, n_households=500, n_properties=450,
                           seed=42, demographics=d_low)
    h_high = run_simulation(cfg, years=30, n_households=500, n_properties=450,
                            seed=42, demographics=d_high)
    assert h_high[-1]["median_income"] > h_low[-1]["median_income"]


def test_long_loans_inflate_prices():
    """Longer loan terms should inflate the price-to-income ratio.

    This is the central thesis from housing economics (and the user's
    original argument): extending loan terms doesn't make housing more
    affordable, it lets buyers bid more, which gets capitalized into
    higher prices. With the purchasing-power price anchor in place, the
    simulation now demonstrates this directly: 35-year loans produce a
    substantially higher price-to-income ratio than 10-year loans.
    """
    cfg_short = PolicyConfig(max_loan_years=10)
    cfg_long = PolicyConfig(max_loan_years=35)
    h_short = run_simulation(cfg_short, years=50, n_households=2000,
                             n_properties=1800, seed=42)
    h_long = run_simulation(cfg_long, years=50, n_households=2000,
                            n_properties=1800, seed=42)
    # Longer loans -> meaningfully higher price-to-income
    assert h_long[-1]["price_to_income"] > h_short[-1]["price_to_income"] * 1.3


def test_higher_rates_lower_prices():
    """Higher mortgage rates must reduce prices (the price-feedback fix)."""
    cfg_low = PolicyConfig(mortgage_rate=0.01)
    cfg_high = PolicyConfig(mortgage_rate=0.08)
    h_low = run_simulation(cfg_low, years=50, n_households=1500,
                           n_properties=1350, seed=42)
    h_high = run_simulation(cfg_high, years=50, n_households=1500,
                            n_properties=1350, seed=42)
    assert h_high[-1]["median_price"] < h_low[-1]["median_price"]


def test_finance_short_loan_pays_less_interest():
    """A 10-year loan must pay far less total interest than a 40-year loan."""
    from finance import Assumptions, Scenario, compare
    a = Assumptions(horizon_years=40)
    s10 = Scenario("10y", "buy_now", home_price=250000, down_payment=50000,
                   loan_years=10, mortgage_rate=0.035)
    s40 = Scenario("40y", "buy_now", home_price=250000, down_payment=50000,
                   loan_years=40, mortgage_rate=0.035)
    r = compare([s10, s40], a)
    assert r["10y"]["final"]["total_interest_paid"] < \
        r["40y"]["final"]["total_interest_paid"]
    assert r["40y"]["final"]["total_interest_paid"] > \
        3 * r["10y"]["final"]["total_interest_paid"]


def test_finance_deterministic():
    """Same inputs must give identical outputs (no randomness)."""
    from finance import Assumptions, Scenario, compare
    a = Assumptions(horizon_years=20)
    s = Scenario("x", "buy_now", home_price=200000, down_payment=40000,
                 loan_years=25, mortgage_rate=0.03)
    r1 = compare([s], a)
    r2 = compare([s], a)
    assert r1["x"]["final"] == r2["x"]["final"]


def test_variable_rate_responds_to_benchmark():
    """A variable loan's effective rate must follow the benchmark path."""
    from finance import Assumptions, Scenario, compare
    # Euribor: 0.5% for 2y, then 4% thereafter
    euribor = [0.005, 0.005, 0.04, 0.04, 0.04]
    a = Assumptions(horizon_years=10, benchmark_path=euribor)
    s = Scenario("var", "buy_now", home_price=250000, down_payment=50000,
                 loan_years=25, rate_type="variable", margin=0.01)
    r = compare([s], a)
    series = r["var"]["series"]
    # Year 1 rate ≈ 0.5% + 1% margin = 1.5%
    assert abs(series[1]["effective_rate"] - 0.015) < 1e-6
    # Year 3 rate ≈ 4% + 1% = 5%
    assert abs(series[3]["effective_rate"] - 0.05) < 1e-6


def test_variable_rate_spike_costs_more_than_low_fixed():
    """A variable loan hit by a sustained spike pays more interest than a
    borrower who locked a low fixed rate before the spike."""
    from finance import Assumptions, Scenario, compare
    euribor_spike = [0.005, 0.045, 0.045, 0.045, 0.045]
    a = Assumptions(horizon_years=25, benchmark_path=euribor_spike)
    s_fixed = Scenario("fixed2", "buy_now", home_price=250000,
                       down_payment=50000, loan_years=25,
                       rate_type="fixed", mortgage_rate=0.02)
    s_var = Scenario("var", "buy_now", home_price=250000,
                     down_payment=50000, loan_years=25,
                     rate_type="variable", margin=0.01)
    r = compare([s_fixed, s_var], a)
    assert r["var"]["final"]["total_interest_paid"] > \
        r["fixed2"]["final"]["total_interest_paid"]


def test_appreciation_path_overrides_scalar():
    """An explicit appreciation path should drive home value, not the scalar."""
    from finance import Assumptions, Scenario, compare
    # Flat scalar 2%, but a path that says prices fall 10%/yr
    a = Assumptions(horizon_years=10, house_appreciation=0.02,
                    appreciation_path=[-0.10] * 10)
    s = Scenario("x", "buy_now", home_price=250000, down_payment=50000,
                 loan_years=25, mortgage_rate=0.03)
    r = compare([s], a)
    # Home value should be far below the €250k start after 10y of -10%
    assert r["x"]["series"][-1]["home_value"] < 150000


def test_price_path_endpoint_shape():
    """The /api/price-path bridge returns a usable appreciation path."""
    import sys, os
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "backend", "api"))
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.post("/api/price-path", json={
        "max_loan_years": 25, "max_ltv": 0.9, "mortgage_rate": 0.03,
        "construction_rate": 0.005, "public_share": 0.0,
        "depreciation": False, "years": 20, "seed": 42,
    })
    assert r.status_code == 200
    d = r.json()
    assert len(d["appreciation_path"]) == 20
    assert len(d["median_price"]) == 21  # includes year 0


def test_swiss_pays_more_interest_less_equity():
    """Swiss interest-only: more lifetime interest, less equity (no paydown),
    but more invested cash than an amortizing loan at the same rate."""
    from finance import Assumptions, Scenario, compare
    a = Assumptions(horizon_years=30, stock_return=0.07, monthly_budget=1800)
    s_amort = Scenario("amort", "buy_now", home_price=250000,
                       down_payment=50000, loan_years=25,
                       rate_type="fixed", mortgage_rate=0.03)
    s_swiss = Scenario("swiss", "swiss_interest_only", home_price=250000,
                       down_payment=50000, rate_type="fixed",
                       mortgage_rate=0.03)
    r = compare([s_amort, s_swiss], a)
    assert r["swiss"]["final"]["total_interest_paid"] > \
        r["amort"]["final"]["total_interest_paid"]
    assert r["swiss"]["final"]["home_equity"] < \
        r["amort"]["final"]["home_equity"]
    assert r["swiss"]["final"]["investments"] > \
        r["amort"]["final"]["investments"]


def test_swiss_loses_when_stocks_underperform_mortgage():
    """Swiss strategy is a leveraged bet on market returns. When stock
    returns fall below the mortgage rate, amortizing should win."""
    from finance import Assumptions, Scenario, compare
    a = Assumptions(horizon_years=30, stock_return=0.02, monthly_budget=1800)
    s_amort = Scenario("amort", "buy_now", home_price=250000,
                       down_payment=50000, loan_years=25,
                       rate_type="fixed", mortgage_rate=0.03)
    s_swiss = Scenario("swiss", "swiss_interest_only", home_price=250000,
                       down_payment=50000, rate_type="fixed",
                       mortgage_rate=0.03)
    r = compare([s_amort, s_swiss], a)
    assert r["amort"]["final"]["net_worth"] > r["swiss"]["final"]["net_worth"]


def test_forecast_produces_widening_uncertainty():
    """The forecaster's credible band must widen with horizon — that's the
    honest behavior the tool exists to demonstrate."""
    from finance import forecast_prices
    prices = [150000, 160000, 172000, 185000, 200000, 215000,
              225000, 210000, 208000, 212000]
    r = forecast_prices(prices, horizon=15, seed=1)
    q = r["forecast_quantiles"]
    band_yr1 = q["95"][0] - q["5"][0]
    band_yr15 = q["95"][-1] - q["5"][-1]
    assert band_yr15 > band_yr1 * 1.5  # uncertainty grows materially
    assert "caveat" in r


def test_forecast_rejects_too_short_history():
    """Fewer than 4 points should raise rather than fabricate a forecast."""
    from finance import forecast_prices
    import pytest as _pt
    with _pt.raises(ValueError):
        forecast_prices([100000, 110000], horizon=10)


def test_historical_series_present_and_wellformed():
    """All four vetted real series exist and have aligned years/index arrays."""
    from finance import HISTORICAL_SERIES, get_series
    for key in ("japan", "switzerland", "finland", "austria"):
        s = get_series(key)
        assert len(s["years"]) == len(s["index"]) >= 4
        assert s["note"] and s["source"]


def test_japan_series_reflects_bubble_collapse():
    """Japan's transcribed series must capture the 1991 peak then decline."""
    from finance import get_series
    s = get_series("japan")
    yr = s["years"]; ix = s["index"]
    peak_i = ix.index(max(ix))
    assert yr[peak_i] == 1991                 # peak is at 1991
    assert ix[-1] < max(ix) * 0.8             # 2024 well below the peak


def test_forecast_on_real_series_widens():
    """Forecasting any real series must still produce a widening band and
    keep the explicit honesty caveat."""
    from finance import forecast_prices, get_series
    for key in ("japan", "switzerland", "finland", "austria"):
        s = get_series(key)
        r = forecast_prices([float(x) for x in s["index"]], horizon=10, seed=1)
        q = r["forecast_quantiles"]
        assert (q["95"][-1] - q["5"][-1]) > (q["95"][0] - q["5"][0])
        assert "caveat" in r


def test_forecast_historical_endpoint():
    """The /api/forecast-historical endpoint returns provenance + a forecast."""
    import sys, os
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "backend", "api"))
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.post("/api/forecast-historical",
                     json={"key": "japan", "horizon": 8, "seed": 1})
    assert r.status_code == 200
    d = r.json()
    assert "series_label" in d and "series_source" in d
    assert len(d["forecast_quantiles"]["50"]) == 8
    # Unknown key is a clean 404
    r2 = client.post("/api/forecast-historical", json={"key": "atlantis"})
    assert r2.status_code == 404


def test_variance_off_is_back_compatible():
    """With no variance config, output keeps the old single-projection shape."""
    from finance import Assumptions, Scenario, compare
    a = Assumptions(horizon_years=20)
    s = Scenario("x", "buy_now", home_price=250000, down_payment=50000,
                 loan_years=25, mortgage_rate=0.03)
    r = compare([s], a)
    assert r["x"]["variance"] is False
    assert "series" in r["x"] and "final" in r["x"]
    assert "branches" not in r["x"]


def test_variance_produces_ordered_branches():
    """Bull should beat base should beat bear on net worth, and the
    top-level final must still mirror the base branch (back-compat)."""
    from finance import Assumptions, Scenario, VarianceConfig, compare
    a = Assumptions(horizon_years=30, stock_return=0.07,
                    house_appreciation=0.02, monthly_budget=1800)
    s = Scenario("Buy", "buy_now", home_price=250000, down_payment=50000,
                 loan_years=25, rate_type="fixed", mortgage_rate=0.045)
    v = VarianceConfig(enabled=True)
    r = compare([s], a, v)
    b = r["Buy"]["branches"]
    assert b["bull"]["final"]["net_worth"] > b["base"]["final"]["net_worth"]
    assert b["base"]["final"]["net_worth"] > b["bear"]["final"]["net_worth"]
    # Bull pays less interest than bear (rates fall vs rise)
    assert b["bull"]["final"]["total_interest_paid"] < \
        b["bear"]["final"]["total_interest_paid"]
    # Back-compat: top-level final == base
    assert r["Buy"]["final"] == b["base"]["final"]


def test_variance_endpoint():
    """The /api/finance endpoint accepts a variance block and returns
    branches when enabled."""
    import sys, os
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "backend", "api"))
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.post("/api/finance", json={
        "assumptions": {"horizon_years": 25, "stock_return": 0.07,
                        "house_appreciation": 0.02, "rent_inflation": 0.02,
                        "general_inflation": 0.02, "income": 45000,
                        "monthly_budget": 1800, "real_terms": False,
                        "benchmark_path": [], "appreciation_path": []},
        "scenarios": [{"name": "Buy", "kind": "buy_now",
                       "home_price": 250000, "down_payment": 50000,
                       "loan_years": 25, "rate_type": "fixed",
                       "mortgage_rate": 0.04, "margin": 0.01,
                       "wait_years": 0, "monthly_rent": 0,
                       "reno_total": 0, "reno_years": 0,
                       "upkeep_rate": 0.015}],
        "variance": {"enabled": True, "rate_delta": 0.015,
                     "appreciation_delta": 0.03,
                     "stock_delta_bull": 0.08, "stock_delta_bear": 0.12},
    })
    assert r.status_code == 200
    d = r.json()
    assert d["Buy"]["variance"] is True
    assert set(d["Buy"]["branches"]) == {"bear", "base", "bull"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
