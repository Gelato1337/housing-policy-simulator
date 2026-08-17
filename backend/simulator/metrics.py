"""
Aggregate metrics computed after each step.

Add a new metric: write a function that takes a World and returns a number,
then register it in `compute_metrics`.
"""
from __future__ import annotations

import numpy as np
from typing import Dict, List

from .agents import World


# Approximate fraction of gross income that's disposable after Finnish
# income tax + social security. ~30-35% effective rate on median earners,
# so disposable ≈ 70% of gross.
DISPOSABLE_FRACTION = 0.70


def _median(xs: List[float]) -> float:
    if not xs:
        return 0.0
    return float(np.median(xs))


def _gini(xs: List[float]) -> float:
    """Gini coefficient of a non-negative list."""
    arr = np.array(sorted(xs), dtype=float)
    n = len(arr)
    total = arr.sum()
    if total <= 0 or n == 0:
        return 0.0
    cum = np.cumsum(arr) / total
    area = cum.sum() / n
    return float(1 - 2 * area + 1 / n)


def compute_metrics(world: World) -> Dict[str, float]:
    """All headline metrics for a single year."""
    N = len(world.households)
    if N == 0:
        return {}

    pmap = {p.id: p for p in world.properties}

    incomes = [h.income for h in world.households]
    # Disposable income — what's left after taxes + SSI.
    # Housing burden is measured against this, not gross income.
    disposables = [h.income * DISPOSABLE_FRACTION for h in world.households]

    prices = [p.value for p in world.properties if p.owner_id != -1]
    # Burden = housing cost / disposable income (the realistic measure)
    burdens = [h.housing_cost_last_year / (h.income * DISPOSABLE_FRACTION)
               for h in world.households if h.income > 0]
    wealth = [sum(pmap[pid].value for pid in h.properties if pid in pmap)
              for h in world.households]
    # Mortgage debt: total outstanding balance per household
    mortgage_debt = [sum(m.balance for m in h.mortgages)
                     for h in world.households]

    owners = sum(1 for h in world.households if not h.is_renter and h.residence != -1)
    housed = sum(1 for h in world.households if h.residence != -1)
    multi = sum(1 for h in world.households if len(h.properties) >= 2)
    overburdened = sum(1 for b in burdens if b > 0.40)
    severely_overburdened = sum(1 for b in burdens if b > 0.60)

    median_income = _median(incomes)
    median_disposable = _median(disposables)
    median_price = _median(prices)
    median_debt = _median(mortgage_debt)

    return {
        "homeownership_rate": owners / N,
        "pct_housed": housed / N,
        "multi_owner_pct": multi / N,
        # P/I uses gross income (the standard published metric)
        "price_to_income": (median_price / median_income) if median_income else 0.0,
        # Burden is against disposable
        "housing_burden_median": _median(burdens),
        "overburdened_pct": overburdened / max(1, len(burdens)),
        "severely_overburdened_pct": severely_overburdened / max(1, len(burdens)),
        "disposable_share_median": 1.0 - _median(burdens),
        "wealth_gini": _gini(wealth),
        "avg_condition": float(np.mean([p.condition for p in world.properties])),
        "median_income": median_income,
        "median_disposable": median_disposable,
        "median_price": median_price,
        "median_mortgage_debt": median_debt,
    }
