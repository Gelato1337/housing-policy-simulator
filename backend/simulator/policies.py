"""
Policy system.

Every policy is a class with a single method `apply(world, rng, ctx)`.
Built-in policies are imported and registered at module level. Custom policies
created at runtime via expression strings are wrapped in `FormulaPolicy`.

Two kinds of policy:

- Structural policies (LoanTerm, LTV, Construction, PublicHousing,
  Depreciation): these don't fit a per-household formula because they shape
  the marketplace mechanism. They're consumed as configuration by other
  simulation steps (marketplace, construction).

- Formula policies (MultiHomeTax, VacancyTax, custom ones): these run per
  household per year and return a euro delta to add to `h.savings`. Both
  built-in tax policies and custom user policies use the same FormulaPolicy
  class.

To add a new structural policy: subclass Policy, expose its config on the
PolicyConfig dataclass below, and read it from the relevant step in
step.py.

To add a new formula policy: just instantiate FormulaPolicy with an
expression string. No code changes needed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Policy configuration object — flows through every simulation step
# ---------------------------------------------------------------------------

@dataclass
class PolicyConfig:
    """Configuration for a single simulation run."""
    # Structural levers
    max_loan_years: int = 25
    max_ltv: float = 0.90
    construction_rate: float = 0.005  # fraction of stock per year
    public_share: float = 0.0         # fraction of new builds that are public
    depreciation: bool = False        # Tokyo-style building depreciation
    stress_rate: float = 0.06         # rate banks stress-test affordability at
    mortgage_rate: float = 0.030      # actual interest rate on issued loans
    base_rent_yield: float = 0.05
    public_rent_yield: float = 0.030

    # Match-acceptance friction. 0 = always accept (frictionless market),
    # 1 = highly picky (most matches fail).
    match_pickiness: float = 0.0

    # Formula policies (zero or more)
    formula_policies: List["FormulaPolicy"] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------

# Whitelist of safe builtins for formula expressions. Anything not in here is
# unavailable, including __import__, eval, exec, file I/O, etc.
SAFE_BUILTINS = {
    "abs": abs, "min": min, "max": max, "round": round, "pow": pow,
    "int": int, "float": float, "bool": bool,
    "True": True, "False": False, "None": None,
}

# Math functions exposed in formulas
SAFE_MATH = {
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "exp": math.exp,
    "floor": math.floor, "ceil": math.ceil, "pi": math.pi, "e": math.e,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
}


class FormulaPolicy:
    """
    A policy expressed as a Python expression that returns euros to add to
    h.savings.

    Available names inside the expression:
      - h.age, h.income, h.savings, h.num_props, h.renter, h.first_time_buyer,
        h.residence_value, h.total_prop_value
      - p.value, p.land_value, p.building_value, p.age, p.condition,
        p.is_residence, p.is_rented, p.is_vacant, p.property_index
        (only when per_prop=True; the expression runs once per property)
      - slider: the policy's slider value (0–200 by convention)
      - median_income, median_price, year
      - math functions: sqrt, log, exp, sin, cos, floor, ceil, pi, e
      - builtins: abs, min, max, round, pow, int, float

    For per-property policies, the expression is evaluated once per property
    the household owns, and the results are summed.
    """

    def __init__(
        self,
        name: str,
        formula: str,
        slider_value: float = 100.0,
        per_prop: bool = True,
        enabled: bool = True,
    ):
        self.name = name
        self.formula = formula
        self.slider_value = slider_value
        self.per_prop = per_prop
        self.enabled = enabled
        self._compiled = None
        self._error: Optional[str] = None
        self.compile()

    def compile(self) -> None:
        """Compile the formula. Errors are stored on `self._error`."""
        try:
            self._compiled = compile(self.formula, f"<policy:{self.name}>", "eval")
            self._error = None
        except SyntaxError as e:
            self._compiled = None
            self._error = f"Syntax error: {e.msg}"

    @property
    def error(self) -> Optional[str]:
        return self._error

    def evaluate(self, namespace: Dict) -> float:
        """Run the formula in the given namespace. Returns 0 on any error."""
        if self._compiled is None or not self.enabled:
            return 0.0
        try:
            safe_globals = {"__builtins__": SAFE_BUILTINS, **SAFE_MATH}
            result = eval(self._compiled, safe_globals, namespace)
            if isinstance(result, (int, float)) and math.isfinite(result):
                return float(result)
            return 0.0
        except Exception:
            return 0.0


# ---------------------------------------------------------------------------
# Helper namespaces for formula evaluation
# ---------------------------------------------------------------------------

class HouseholdView:
    """Read-only adapter exposing household attributes to formulas."""
    __slots__ = ("age", "income", "savings", "num_props", "renter",
                 "residence_value", "total_prop_value", "first_time_buyer")

    def __init__(self, h, residence_value, total_prop_value):
        self.age = h.age
        self.income = h.income
        self.savings = h.savings
        self.num_props = len(h.properties)
        self.renter = h.is_renter
        self.residence_value = residence_value
        self.total_prop_value = total_prop_value
        self.first_time_buyer = h.first_time_buyer


class PropertyView:
    """Read-only adapter exposing property attributes to formulas."""
    __slots__ = ("value", "land_value", "building_value", "age",
                 "condition", "is_residence", "is_rented", "is_vacant",
                 "property_index")

    def __init__(self, p, is_residence, is_rented, is_vacant, property_index):
        self.value = p.value
        self.land_value = p.land_value
        self.building_value = p.building_value
        self.age = p.age
        self.condition = p.condition
        self.is_residence = is_residence
        self.is_rented = is_rented
        self.is_vacant = is_vacant
        self.property_index = property_index


# ---------------------------------------------------------------------------
# Built-in formula policy factories
# ---------------------------------------------------------------------------

def progressive_multi_home_tax(slider: float = 0.0) -> FormulaPolicy:
    return FormulaPolicy(
        name="Progressive multi-home tax",
        formula="-p.value * (slider/1000) * (p.property_index - 1) if p.property_index > 1 else 0",
        slider_value=slider,
        per_prop=True,
        enabled=slider > 0,
    )


def vacancy_tax(slider: float = 0.0) -> FormulaPolicy:
    return FormulaPolicy(
        name="Vacancy tax",
        formula="-p.value * (slider/1000) if (p.is_vacant and not p.is_residence) else 0",
        slider_value=slider,
        per_prop=True,
        enabled=slider > 0,
    )


# ---------------------------------------------------------------------------
# Templates available to the UI
# ---------------------------------------------------------------------------

POLICY_TEMPLATES = {
    "luxury": {
        "name": "Luxury home tax",
        "formula": "-(p.value - 500000) * 0.01 * slider/100 if p.value > 500000 else 0",
        "slider_value": 50,
        "per_prop": True,
        "hint": "1% tax on property value above €500k.",
    },
    "first_buyer": {
        "name": "First-buyer credit",
        "formula": "5000 * slider/100 if h.first_time_buyer else 0",
        "slider_value": 100,
        "per_prop": False,
        "hint": "€5,000 one-time bonus for first-time buyers.",
    },
    "elderly": {
        "name": "Elderly housing relief",
        "formula": "p.value * 0.005 * slider/100 if (h.age > 70 and p.is_residence) else 0",
        "slider_value": 100,
        "per_prop": True,
        "hint": "0.5% rebate on primary residence value for households 70+.",
    },
    "lvt": {
        "name": "Land value tax",
        "formula": "-p.land_value * 0.01 * slider/100",
        "slider_value": 50,
        "per_prop": True,
        "hint": "Henry George style: tax on land value only (1%).",
    },
    "inherit": {
        "name": "Inheritance leak",
        "formula": "-h.total_prop_value * 0.005 * slider/100 if h.age > 82 else 0",
        "slider_value": 100,
        "per_prop": False,
        "hint": "Approximates wealth dispersion on death (0.5%/year past age 82).",
    },
    "income_targeted": {
        "name": "Below-median ownership subsidy",
        "formula": ("3000 * slider/100 "
                    "if (h.first_time_buyer and h.income < median_income) else 0"),
        "slider_value": 100,
        "per_prop": False,
        "hint": "€3,000 bonus for first-time buyers below median income.",
    },
}
