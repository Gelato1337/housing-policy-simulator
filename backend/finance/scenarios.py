"""
Personal-finance scenario comparator.

Deterministic cash-flow projection for comparing individual housing/investing
decisions. Separate from the agent-based policy simulator.

Two or more scenarios are projected year by year and compared on:
  - net worth (home equity + investment portfolio - debt)
  - total interest paid to the bank
  - total housing cost
  - liquid investments

NEW: variable-rate mortgages. Real Finnish mortgages are mostly Euribor-linked
variable rate, so the borrower's rate moves with a benchmark. We model:

  effective_rate(year) = benchmark_path[year] + margin    (variable)
  effective_rate       = mortgage_rate                     (fixed)

When a variable rate changes, the monthly payment is RECALCULATED on the
remaining balance over the remaining term (this is how Finnish annuity loans
actually behave: the term stays fixed, the payment moves). This is what makes
the 2022-2023 squeeze visible: a 1.5% loan whose Euribor leg jumps to 4%
roughly doubles the monthly payment overnight.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


def monthly_payment(principal: float, annual_rate: float, years: int) -> float:
    """Standard annuity payment for a given principal, rate, term in years."""
    if years <= 0:
        return principal
    r = annual_rate / 12.0
    n = years * 12
    if r <= 0:
        return principal / n
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


@dataclass
class Assumptions:
    """Shared economic assumptions across all scenarios being compared."""
    horizon_years: int = 30
    stock_return: float = 0.07
    house_appreciation: float = 0.02
    rent_inflation: float = 0.02
    general_inflation: float = 0.02
    income: float = 45_000.0
    monthly_budget: float = 1_800.0
    real_terms: bool = False
    # Annual benchmark (e.g. 12-month Euribor) rate, one entry per year
    # starting at year 1. If shorter than the horizon, the last value is
    # held constant for the remaining years. If empty, defaults to a flat
    # 2.5% (roughly the current 12-month Euribor as of early 2026).
    benchmark_path: List[float] = field(default_factory=list)
    # Optional per-year house price growth path (e.g. fed from the ABM).
    # If empty, the scalar house_appreciation is used for every year.
    appreciation_path: List[float] = field(default_factory=list)

    def benchmark_at(self, year: int) -> float:
        """Benchmark rate for a given simulation year (year >= 1)."""
        if not self.benchmark_path:
            return 0.025
        idx = min(year - 1, len(self.benchmark_path) - 1)
        idx = max(0, idx)
        return self.benchmark_path[idx]

    def appreciation_at(self, year: int) -> float:
        """House price growth for a given year (year >= 1)."""
        if not self.appreciation_path:
            return self.house_appreciation
        idx = min(year - 1, len(self.appreciation_path) - 1)
        idx = max(0, idx)
        return self.appreciation_path[idx]


@dataclass
class VarianceConfig:
    """Defines how far the bull and bear branches deviate from the base case.

    Each delta is an ADDITIVE shift applied to the relevant annual rate for
    the whole horizon. Signs are chosen so "bull" is the optimistic branch
    for an owner: lower mortgage rates, higher house appreciation, higher
    stock returns; "bear" is the mirror image.

    Defaults encode the user's stated examples: stocks roughly +15% / -5%
    around a 7% base (so +8 / -12 deltas), mortgage rates +/-1.5pp, and
    house appreciation +/-3pp.
    """
    enabled: bool = False
    rate_delta: float = 0.015          # +/- on mortgage/benchmark rate
    appreciation_delta: float = 0.03   # +/- on annual house price growth
    stock_delta_bull: float = 0.08     # added to stock_return in bull
    stock_delta_bear: float = 0.12     # subtracted from stock_return in bear


def _branch_assumptions(a: "Assumptions", v: VarianceConfig, branch: str) -> "Assumptions":
    """Return a copy of `a` perturbed for 'bull' | 'base' | 'bear'."""
    import copy
    b = copy.deepcopy(a)
    if branch == "base":
        return b

    if branch == "bull":
        # Owner-optimistic: lower rates, faster appreciation, stronger stocks
        rate_sign, appr_sign = -1.0, +1.0
        b.stock_return = a.stock_return + v.stock_delta_bull
    else:  # bear
        rate_sign, appr_sign = +1.0, -1.0
        b.stock_return = a.stock_return - v.stock_delta_bear

    # Shift the scalar drivers
    b.house_appreciation = a.house_appreciation + appr_sign * v.appreciation_delta
    b.rent_inflation = max(0.0, a.rent_inflation + appr_sign * v.appreciation_delta * 0.5)

    # Shift any explicit paths too, so a pulled ABM/Euribor path still moves
    if a.benchmark_path:
        b.benchmark_path = [max(0.0, x + rate_sign * v.rate_delta)
                            for x in a.benchmark_path]
    if a.appreciation_path:
        b.appreciation_path = [x + appr_sign * v.appreciation_delta
                               for x in a.appreciation_path]
    return b


@dataclass
class Scenario:
    """A single life-path. Not all fields apply to every kind.

    IMPORTANT — fair-comparison model:
      `down_payment` is interpreted as STARTING LIQUID CAPITAL: the savings
      you have on day 0. Every scenario starts from this same amount so the
      comparison is apples-to-apples (a buyer and a renter with the same
      €50k start should be compared from the same €50k, not have one of
      them silently forfeit it). When you buy, the down payment is spent
      from this capital and the remainder stays invested. When you rent,
      the whole amount stays invested.

    kind:
      "buy_now"            amortizing mortgage; spend down payment from
                           starting capital, remainder invested
      "rent_then_buy"      rent + invest for wait_years, then buy using the
                           accumulated pot as the down payment
      "rent_forever"       never buy; the whole starting capital stays
                           invested and you pay rent every year
      "swiss_interest_only" put deposit down, pay interest only FOREVER
                           (never amortize). Frees cash to invest; equity
                           never grows from principal paydown.
    """
    name: str
    kind: str
    home_price: float = 250_000.0
    down_payment: float = 50_000.0   # = starting liquid capital (see above)
    loan_years: int = 25
    # rate_type "fixed": use mortgage_rate for the whole loan.
    # rate_type "variable": effective rate = benchmark_path[year] + margin,
    #   recomputed each year, payment re-amortized over remaining term.
    rate_type: str = "fixed"
    mortgage_rate: float = 0.030     # used when rate_type == "fixed"
    margin: float = 0.010            # bank spread over benchmark (variable)
    wait_years: int = 0
    monthly_rent: float = 0.0        # €/month; if 0, auto = 0.4%/mo of price
    reno_total: float = 0.0
    reno_years: int = 0
    upkeep_rate: float = 0.015


@dataclass
class YearState:
    year: int
    net_worth: float
    home_equity: float
    investments: float
    debt: float
    cumulative_interest: float
    cumulative_housing_cost: float
    home_value: float
    effective_rate: float            # the mortgage rate actually in force


def _effective_rate(s: Scenario, a: Assumptions, year: int) -> float:
    """The mortgage rate in force for scenario s in a given year."""
    if s.rate_type == "variable":
        return max(0.0, a.benchmark_at(year) + s.margin)
    return s.mortgage_rate


def project_scenario(s: Scenario, a: Assumptions) -> List[YearState]:
    """Project one scenario year by year. Returns horizon+1 states (incl. y0)."""
    history: List[YearState] = []

    owns = False
    home_value = 0.0
    debt = 0.0
    mpayment = 0.0
    investments = 0.0
    cum_interest = 0.0
    cum_housing = 0.0
    loan_years_left = 0
    current_rate = 0.0

    monthly_budget = a.monthly_budget

    def est_rent(price: float) -> float:
        return s.monthly_rent if s.monthly_rent > 0 else price * 0.004

    # Initial setup. KEY: every scenario starts with the SAME liquid
    # capital (s.down_payment). Buying spends part of it; the rest stays
    # invested. This makes all scenarios comparable from an identical
    # starting net worth.
    starting_capital = s.down_payment

    if s.kind == "buy_now":
        owns = True
        home_value = s.home_price
        principal = max(0.0, s.home_price - s.down_payment)
        debt = principal
        loan_years_left = s.loan_years
        current_rate = _effective_rate(s, a, 1)
        mpayment = monthly_payment(principal, current_rate, s.loan_years)
        # The down payment is spent buying the house; if starting capital
        # exceeds it (rare with these defaults) the rest stays invested.
        investments = max(0.0, starting_capital - s.down_payment)
    elif s.kind == "swiss_interest_only":
        # Swiss model: put the deposit down, borrow the rest, and pay
        # INTEREST ONLY forever. The principal is never amortized; it's
        # conceptually repaid only on sale/death. Net worth subtracts debt
        # every year so this is automatic.
        owns = True
        home_value = s.home_price
        debt = max(0.0, s.home_price - s.down_payment)
        loan_years_left = a.horizon_years
        current_rate = _effective_rate(s, a, 1)
        mpayment = 0.0
        investments = max(0.0, starting_capital - s.down_payment)
    elif s.kind in ("rent_then_buy", "rent_forever"):
        owns = False
        # Whole starting capital stays invested while renting.
        investments = starting_capital

    history.append(YearState(
        year=0,
        net_worth=investments + (home_value - debt),
        home_equity=home_value - debt,
        investments=investments,
        debt=debt,
        cumulative_interest=0.0,
        cumulative_housing_cost=0.0,
        home_value=home_value,
        effective_rate=current_rate,
    ))

    for year in range(1, a.horizon_years + 1):
        annual_budget = monthly_budget * 12

        # rent_then_buy transitions to ownership after wait_years
        if s.kind == "rent_then_buy" and not owns and year > s.wait_years:
            # Home price grows along the appreciation path during the wait.
            grown_factor = 1.0
            for wy in range(1, s.wait_years + 1):
                grown_factor *= (1 + a.appreciation_at(wy))
            grown_price = s.home_price * grown_factor
            # Put down the larger of (the scenario's stated down payment)
            # and (20% of the now-grown price), but never more than the
            # accumulated investment pot. Whatever's left stays invested.
            desired_down = max(s.down_payment, grown_price * 0.20)
            down = min(investments, desired_down)
            investments -= down
            home_value = grown_price
            principal = max(0.0, grown_price - down)
            debt = principal
            loan_years_left = s.loan_years
            current_rate = _effective_rate(s, a, year)
            mpayment = monthly_payment(principal, current_rate, s.loan_years)
            owns = True

        housing_spent = 0.0
        if s.kind == "swiss_interest_only" and debt > 0:
            # Interest only — debt never declines. Rate can still be variable.
            new_rate = _effective_rate(s, a, year)
            current_rate = new_rate
            interest = debt * current_rate
            cum_interest += interest
            housing_spent += interest
        elif owns and debt > 0 and loan_years_left > 0:
            # For variable loans, recompute the rate and re-amortize the
            # payment over the remaining term whenever the rate changes.
            new_rate = _effective_rate(s, a, year)
            if s.rate_type == "variable" and abs(new_rate - current_rate) > 1e-9:
                current_rate = new_rate
                mpayment = monthly_payment(debt, current_rate, loan_years_left)

            r = current_rate / 12.0
            for _ in range(12):
                if debt <= 0:
                    break
                interest = debt * r
                principal_paid = min(mpayment - interest, debt)
                if principal_paid < 0:
                    # Payment doesn't even cover interest (extreme rate spike).
                    # Negative amortization: balance grows. We still record the
                    # full interest as paid out of cash (the bank wants it).
                    principal_paid = 0.0
                    interest = mpayment
                debt -= principal_paid
                cum_interest += interest
                housing_spent += (interest + principal_paid)
            loan_years_left -= 1

        if owns:
            upkeep = home_value * s.upkeep_rate
            housing_spent += upkeep
            if s.reno_total > 0 and s.reno_years > 0 and year <= s.reno_years:
                reno_this_year = s.reno_total / s.reno_years
                housing_spent += reno_this_year
                home_value += reno_this_year * 0.70
            home_value *= (1 + a.appreciation_at(year))
        else:
            rent = est_rent(s.home_price) * ((1 + a.rent_inflation) ** (year - 1))
            housing_spent += rent * 12

        cum_housing += housing_spent

        leftover = annual_budget - housing_spent
        investments *= (1 + a.stock_return)
        investments += leftover
        if investments < 0:
            investments = 0.0

        net_worth = investments + (home_value - debt)

        history.append(YearState(
            year=year,
            net_worth=net_worth,
            home_equity=home_value - debt,
            investments=investments,
            debt=debt,
            cumulative_interest=cum_interest,
            cumulative_housing_cost=cum_housing,
            home_value=home_value,
            effective_rate=current_rate,
        ))

    if a.real_terms:
        out = []
        for st in history:
            f = (1 + a.general_inflation) ** st.year
            out.append(YearState(
                year=st.year,
                net_worth=st.net_worth / f,
                home_equity=st.home_equity / f,
                investments=st.investments / f,
                debt=st.debt / f,
                cumulative_interest=st.cumulative_interest / f,
                cumulative_housing_cost=st.cumulative_housing_cost / f,
                home_value=st.home_value / f,
                effective_rate=st.effective_rate,
            ))
        return out

    return history


def _project_one(s: Scenario, a: Assumptions) -> Dict:
    """Project a single scenario under one assumption set -> result dict."""
    hist = project_scenario(s, a)
    return {
        "series": [
            {
                "year": st.year,
                "net_worth": round(st.net_worth, 2),
                "home_equity": round(st.home_equity, 2),
                "investments": round(st.investments, 2),
                "debt": round(st.debt, 2),
                "cumulative_interest": round(st.cumulative_interest, 2),
                "cumulative_housing_cost": round(st.cumulative_housing_cost, 2),
                "home_value": round(st.home_value, 2),
                "effective_rate": round(st.effective_rate, 5),
            }
            for st in hist
        ],
        "final": {
            "net_worth": round(hist[-1].net_worth, 2),
            "total_interest_paid": round(hist[-1].cumulative_interest, 2),
            "total_housing_cost": round(hist[-1].cumulative_housing_cost, 2),
            "investments": round(hist[-1].investments, 2),
            "home_equity": round(hist[-1].home_equity, 2),
        },
    }


def _shift_scenario_rate(s: Scenario, delta: float) -> Scenario:
    """Return a copy of s with fixed mortgage rate shifted (variable loans
    are shifted via the benchmark path instead, so leave those alone)."""
    import copy
    s2 = copy.deepcopy(s)
    if s2.rate_type == "fixed":
        s2.mortgage_rate = max(0.0, s2.mortgage_rate + delta)
    return s2


def compare(scenarios: List[Scenario], a: Assumptions,
            variance: "VarianceConfig | None" = None) -> Dict:
    """Project all scenarios. If variance is enabled, each scenario gets
    bear/base/bull branches; otherwise just the single base projection."""
    results = {}
    for s in scenarios:
        if variance is not None and variance.enabled:
            branches = {}
            for branch in ("bear", "base", "bull"):
                a_b = _branch_assumptions(a, variance, branch)
                # Fixed-rate loans: also move the scenario's own rate.
                if branch == "bull":
                    s_b = _shift_scenario_rate(s, -variance.rate_delta)
                elif branch == "bear":
                    s_b = _shift_scenario_rate(s, +variance.rate_delta)
                else:
                    s_b = s
                branches[branch] = _project_one(s_b, a_b)
            results[s.name] = {
                "kind": s.kind,
                "variance": True,
                "branches": branches,
                # keep "series"/"final" pointing at base for back-compat
                "series": branches["base"]["series"],
                "final": branches["base"]["final"],
            }
        else:
            r = _project_one(s, a)
            r["kind"] = s.kind
            r["variance"] = False
            results[s.name] = r
    return results
