"""
World initialization: create N households and M properties with realistic
distributions, then perform initial allocation (assign owners and tenants).

Demographic parameters are passed via a `Demographics` dataclass so the
API can expose them as sliders without changing function signatures.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np

from .agents import Household, Property, World


@dataclass
class Demographics:
    """Parameters controlling the initial population's distributions."""
    income_log_mu: float = 10.6       # ln(€40k) ≈ 10.6; € median ≈ exp(mu)
    income_log_sigma: float = 0.4     # Income inequality (higher = more unequal)
    age_mean: float = 45.0
    age_sd: float = 15.0
    base_price: float = 180_000.0     # Property price at quality=1.0
    land_fraction: float = 0.4
    initial_owner_share: float = 0.60
    initial_investor_share: float = 0.05
    # Quality preference: each household has an ideal quality. The spread
    # controls how heterogeneous tastes are. Low spread = everyone wants
    # similar things (homogeneous market); high spread = picky distinct tastes.
    quality_pref_spread: float = 0.25


def init_world(
    n_households: int = 2000,
    n_properties: int = 1800,
    seed: int = 42,
    demographics: Demographics | None = None,
) -> Tuple[World, np.random.Generator]:
    """Create a fresh world. Returns the world and the seeded RNG."""
    d = demographics or Demographics()
    rng = np.random.default_rng(seed)

    # Households ---------------------------------------------------------------
    households = []
    for i in range(n_households):
        age = int(np.clip(rng.normal(d.age_mean, d.age_sd), 20, 85))
        income = float(np.clip(rng.lognormal(d.income_log_mu, d.income_log_sigma),
                               15_000, 250_000))
        savings_mean = income * 0.5 * (age - 20) / 30
        savings = max(0.0, float(rng.normal(savings_mean, income * 0.3)))
        # Quality preference centered on 1.0 (market average) with configurable
        # spread. Clipped to the same range that properties span.
        quality_pref = float(np.clip(rng.normal(1.0, d.quality_pref_spread), 0.4, 1.8))
        households.append(Household(
            id=i, age=age, income=income, savings=savings,
            quality_preference=quality_pref,
        ))

    # Properties ---------------------------------------------------------------
    properties = []
    for i in range(n_properties):
        q = float(np.clip(rng.normal(1.0, 0.25), 0.4, 1.8))
        c = float(np.clip(rng.normal(0.75, 0.15), 0.2, 1.0))
        total = d.base_price * q
        age_p = max(0, int(rng.normal(25, 15)))
        p = Property(
            id=i,
            quality=q,
            condition=c,
            land_value=total * d.land_fraction,
            building_value=total * (1 - d.land_fraction),
            age=age_p,
        )
        p.update_value()
        properties.append(p)

    world = World(households=households, properties=properties)
    _initial_allocation(world, d.initial_owner_share, d.initial_investor_share)
    return world, rng


def _initial_allocation(world: World, owner_share: float, investor_share: float) -> None:
    """
    Assign initial property ownership and tenancy.

    Sort households by wealth descending, properties by value descending.
    Top `owner_share` become owners (richest get nicest). A subset also pick
    up a second property (investors). Remaining renters fill what's left.

    Initial owners are given partially-amortized mortgages reflecting their
    age — younger owners have more remaining, older ones have less. This
    avoids the unrealistic outcome where 60% of the simulated population
    starts mortgage-free.
    """
    from .mortgage import create_mortgage

    N = len(world.households)
    by_wealth = sorted(world.households,
                       key=lambda h: h.income + h.savings * 0.1,
                       reverse=True)
    by_price = sorted(world.properties, key=lambda p: p.value, reverse=True)

    n_owners = int(N * owner_share)
    pi = 0
    for k in range(min(n_owners, len(by_price))):
        h = by_wealth[k]
        p = by_price[pi]
        pi += 1
        h.properties.append(p.id)
        h.residence = p.id
        h.is_renter = False
        h.has_owned_before = True
        p.owner_id = h.id
        p.occupant_id = h.id

        # Initial mortgage: assume they bought at age 30 (or current age,
        # whichever is later) with a 25-year loan at 3% on 80% LTV.
        # Years into the loan = age - 30. If they're 55+, the loan is
        # paid off (no mortgage). Otherwise create a partially-amortized one.
        purchase_age = 30
        years_held = max(0, h.age - purchase_age)
        full_term = 25
        if years_held < full_term:
            original_principal = p.value * 0.80
            m = create_mortgage(p.id, original_principal,
                                annual_rate=0.030, term_years=full_term)
            # Advance the mortgage by years_held years
            from .mortgage import amortize_year
            for _ in range(years_held):
                amortize_year(m)
            if m.balance > 0:
                h.mortgages.append(m)

    n_inv = int(N * investor_share)
    for k in range(n_inv):
        if pi >= len(by_price):
            break
        h = by_wealth[k]
        p = by_price[pi]
        pi += 1
        h.properties.append(p.id)
        p.owner_id = h.id
        # Investor property: also give a mortgage, but assume more recent
        # purchase (investors actively buy and sell)
        years_held = min(5, max(0, h.age - 35))
        original_principal = p.value * 0.75
        m = create_mortgage(p.id, original_principal,
                            annual_rate=0.030, term_years=20)
        from .mortgage import amortize_year
        for _ in range(years_held):
            amortize_year(m)
        if m.balance > 0:
            h.mortgages.append(m)

    rentable = [p for p in world.properties if p.owner_id != -1 and p.occupant_id == -1]
    ri = 0
    for k in range(n_owners, N):
        if ri >= len(rentable):
            break
        h = by_wealth[k]
        p = rentable[ri]
        ri += 1
        h.residence = p.id
        h.is_renter = True
        h.landlord_id = p.owner_id
        p.occupant_id = h.id
