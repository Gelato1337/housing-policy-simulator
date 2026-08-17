"""
Comprehensive tests for the personal decision comparator.

API note (the thing that bites you):
  * project_scenario(s, a)  -> list[YearState]  (attribute access: st.net_worth)
  * compare([s], a)         -> dict; ["x"]["series"] is list[dict] and
                               ["x"]["final"] is a dict (subscript access)

Focus areas (several pin bugs fixed after user feedback):
  1. Fair comparison: every scenario starts from the SAME liquid capital.
  2. rent_then_buy actually deploys the accumulated pot as a down payment.
  3. rent_forever genuinely pays rent every year (and respects monthly_rent).
  4. Swiss interest-only economics (more interest, less equity, market bet).
  5. Variable-rate transmission and the real-terms deflation.
  6. Determinism and monotone sanity checks.

Run just these:  pytest tests/test_finance_comparator.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from finance import Assumptions, Scenario, compare, project_scenario  # noqa: E402


# ---------------------------------------------------------------------------
# 1. FAIR COMPARISON — the big fix
# ---------------------------------------------------------------------------

def test_all_scenarios_start_from_same_net_worth():
    a = Assumptions(horizon_years=30, monthly_budget=1800)
    cap = 50_000
    scns = [
        Scenario("Buy", "buy_now", home_price=250000, down_payment=cap,
                 loan_years=25, mortgage_rate=0.035),
        Scenario("RentFwd", "rent_forever", home_price=250000,
                 down_payment=cap, monthly_rent=900),
        Scenario("Swiss", "swiss_interest_only", home_price=250000,
                 down_payment=cap, mortgage_rate=0.02),
        Scenario("RentBuy", "rent_then_buy", home_price=250000,
                 down_payment=cap, loan_years=25, mortgage_rate=0.035,
                 wait_years=3),
    ]
    r = compare(scns, a)
    for n in r:
        y0 = r[n]["series"][0]["net_worth"]
        assert abs(y0 - cap) < 1.0, (
            f"{n}: year-0 net worth {y0} != starting capital {cap}")


def test_buy_now_does_not_forfeit_the_down_payment():
    a = Assumptions(horizon_years=1, monthly_budget=1500)
    buy = Scenario("Buy", "buy_now", home_price=200000, down_payment=40000,
                   loan_years=25, mortgage_rate=0.03)
    rent = Scenario("Rent", "rent_forever", home_price=200000,
                    down_payment=40000, monthly_rent=800)
    r = compare([buy, rent], a)
    assert abs(r["Buy"]["series"][0]["net_worth"]
               - r["Rent"]["series"][0]["net_worth"]) < 1.0


# ---------------------------------------------------------------------------
# 2. rent_then_buy deploys the accumulated pot
# ---------------------------------------------------------------------------

def test_rent_then_buy_actually_buys_and_takes_a_mortgage():
    a = Assumptions(horizon_years=20, monthly_budget=2000,
                    house_appreciation=0.02)
    s = Scenario("RTB", "rent_then_buy", home_price=250000,
                 down_payment=50000, loan_years=25, mortgage_rate=0.03,
                 wait_years=4)
    hist = project_scenario(s, a)
    assert hist[3].home_value == 0.0
    assert hist[3].debt == 0.0
    assert hist[10].home_value > 0.0
    assert hist[10].debt > 0.0


def test_rent_then_buy_pot_grows_during_wait():
    a = Assumptions(horizon_years=15, monthly_budget=2200, stock_return=0.06)
    s = Scenario("RTB", "rent_then_buy", home_price=250000,
                 down_payment=50000, loan_years=25, mortgage_rate=0.03,
                 wait_years=5, monthly_rent=900)
    hist = project_scenario(s, a)
    assert hist[5].investments > 50000


# ---------------------------------------------------------------------------
# 3. rent_forever genuinely pays rent
# ---------------------------------------------------------------------------

def test_rent_forever_charges_rent_every_year():
    a = Assumptions(horizon_years=30, monthly_budget=1800)
    s = Scenario("RF", "rent_forever", home_price=250000,
                 down_payment=50000, monthly_rent=1000)
    hist = project_scenario(s, a)
    costs = [h.cumulative_housing_cost for h in hist]
    assert costs[0] == 0.0
    assert costs[-1] > 0.0
    assert all(costs[i] <= costs[i + 1] for i in range(len(costs) - 1))
    assert costs[-1] > 360_000


def test_rent_forever_respects_explicit_monthly_rent():
    a = Assumptions(horizon_years=20, monthly_budget=2500, rent_inflation=0.0)
    low = Scenario("low", "rent_forever", home_price=250000,
                   down_payment=50000, monthly_rent=800)
    high = Scenario("high", "rent_forever", home_price=250000,
                    down_payment=50000, monthly_rent=1600)
    r = compare([low, high], a)
    assert (r["high"]["final"]["total_housing_cost"]
            > r["low"]["final"]["total_housing_cost"] * 1.8)


def test_rent_forever_auto_rent_when_zero():
    a = Assumptions(horizon_years=10, monthly_budget=2000)
    s = Scenario("RF", "rent_forever", home_price=250000,
                 down_payment=50000, monthly_rent=0.0)
    hist = project_scenario(s, a)
    assert hist[-1].cumulative_housing_cost > 0.0


# ---------------------------------------------------------------------------
# 4. Swiss interest-only economics
# ---------------------------------------------------------------------------

def test_swiss_more_interest_less_equity_than_amortizing():
    a = Assumptions(horizon_years=30, stock_return=0.07, monthly_budget=1800)
    am = Scenario("Am", "buy_now", home_price=250000, down_payment=50000,
                  loan_years=25, mortgage_rate=0.03)
    sw = Scenario("Sw", "swiss_interest_only", home_price=250000,
                  down_payment=50000, mortgage_rate=0.03)
    r = compare([am, sw], a)
    assert (r["Sw"]["final"]["total_interest_paid"]
            > r["Am"]["final"]["total_interest_paid"])
    assert (r["Sw"]["final"]["home_equity"]
            < r["Am"]["final"]["home_equity"])


def test_swiss_wins_iff_stocks_beat_mortgage():
    am = Scenario("Am", "buy_now", home_price=250000, down_payment=50000,
                  loan_years=25, mortgage_rate=0.03)
    sw = Scenario("Sw", "swiss_interest_only", home_price=250000,
                  down_payment=50000, mortgage_rate=0.03)
    hi = Assumptions(horizon_years=30, stock_return=0.08, monthly_budget=1800)
    lo = Assumptions(horizon_years=30, stock_return=0.01, monthly_budget=1800)
    r_hi = compare([am, sw], hi)
    r_lo = compare([am, sw], lo)
    assert r_hi["Sw"]["final"]["net_worth"] > r_hi["Am"]["final"]["net_worth"]
    assert r_lo["Sw"]["final"]["net_worth"] < r_lo["Am"]["final"]["net_worth"]


# ---------------------------------------------------------------------------
# 5. Variable rate + real terms
# ---------------------------------------------------------------------------

def test_variable_rate_follows_benchmark_path():
    a = Assumptions(horizon_years=10,
                    benchmark_path=[0.005, 0.005, 0.04, 0.04, 0.04])
    s = Scenario("V", "buy_now", home_price=250000, down_payment=50000,
                 loan_years=25, rate_type="variable", margin=0.01)
    hist = project_scenario(s, a)
    assert abs(hist[1].effective_rate - 0.015) < 1e-6
    assert abs(hist[3].effective_rate - 0.05) < 1e-6


def test_real_terms_deflates_everything():
    base = Assumptions(horizon_years=25, monthly_budget=1800,
                       general_inflation=0.03, real_terms=False)
    real = Assumptions(horizon_years=25, monthly_budget=1800,
                       general_inflation=0.03, real_terms=True)
    s = Scenario("B", "buy_now", home_price=250000, down_payment=50000,
                 loan_years=25, mortgage_rate=0.03)
    rn = compare([s], base)["B"]["final"]["net_worth"]
    rr = compare([s], real)["B"]["final"]["net_worth"]
    assert rr < rn
    assert rr < rn * 0.75


def test_real_terms_year0_unchanged():
    base = Assumptions(horizon_years=10, real_terms=False,
                       general_inflation=0.03)
    real = Assumptions(horizon_years=10, real_terms=True,
                       general_inflation=0.03)
    s = Scenario("B", "buy_now", home_price=250000, down_payment=50000,
                 loan_years=25, mortgage_rate=0.03)
    assert (compare([s], base)["B"]["series"][0]["net_worth"]
            == compare([s], real)["B"]["series"][0]["net_worth"])


# ---------------------------------------------------------------------------
# 6. Determinism & structure
# ---------------------------------------------------------------------------

def test_comparator_is_deterministic():
    a = Assumptions(horizon_years=20)
    s = Scenario("x", "buy_now", home_price=250000, down_payment=50000,
                 loan_years=25, mortgage_rate=0.03)
    assert compare([s], a)["x"]["final"] == compare([s], a)["x"]["final"]


def test_series_length_matches_horizon():
    a = Assumptions(horizon_years=17)
    s = Scenario("x", "buy_now", home_price=250000, down_payment=50000,
                 loan_years=25, mortgage_rate=0.03)
    assert len(compare([s], a)["x"]["series"]) == 18


def test_longer_fixed_loan_pays_more_total_interest():
    a = Assumptions(horizon_years=40, monthly_budget=2500)
    short = Scenario("s", "buy_now", home_price=250000, down_payment=50000,
                     loan_years=10, mortgage_rate=0.035)
    long = Scenario("l", "buy_now", home_price=250000, down_payment=50000,
                    loan_years=40, mortgage_rate=0.035)
    r = compare([short, long], a)
    assert (r["l"]["final"]["total_interest_paid"]
            > 3 * r["s"]["final"]["total_interest_paid"])
