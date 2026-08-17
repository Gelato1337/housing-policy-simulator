"""
Simulation step. One call advances the world by one year.

The step is composed of named phases. Each phase is a pure function on the
world (mutating it) so they can be tested individually and rearranged.

Phases in order:
  1.  aging              — bump ages, reset per-year flags
  2.  income_drift       — wages move; save 10% of income
  3.  depreciation       — Tokyo rule, if enabled
  4.  collect_rents      — landlords receive rent; renters pay rent
  5.  apply_construction — build new units (some marked public)
  6.  forced_sales       — death/retirement put units on the market
  7.  public_allocation  — fill public stock with lowest-income households
  8.  marketplace        — buyers match with listings
  9.  rental_matching    — remaining empty units rent to homeless
  10. maintenance        — condition drifts based on occupancy type
  11. price_drift        — supply-demand pressure moves prices
  12. bankruptcy         — households with deep negative savings fire-sell
  13. formula_policies   — every user/built-in formula policy applies
"""
from __future__ import annotations

import math
import numpy as np
from typing import List, Tuple

from .agents import Household, Mortgage, Property, World
from .mortgage import amortize_year, create_mortgage
from .policies import (
    FormulaPolicy, HouseholdView, PolicyConfig, PropertyView,
)


# ===========================================================================
# Mortgage math
# ===========================================================================

def max_loan(income: float, years: int, stress_rate: float) -> float:
    """Standard mortgage formula, stress-tested at higher rate.

    Banks size loans so monthly payment ≤ 35% of monthly income at the
    stress rate, not the actual rate. This protects them in rate spikes.
    """
    monthly_pay = income / 12 * 0.35
    r = stress_rate / 12
    n = years * 12
    if r <= 0:
        return monthly_pay * n
    return monthly_pay * (math.pow(1 + r, n) - 1) / (r * math.pow(1 + r, n))


def max_purchase_price(h: Household, cfg: PolicyConfig) -> float:
    """How expensive a property this household can afford to buy."""
    loan = max_loan(h.income, cfg.max_loan_years, cfg.stress_rate)
    from_loan = loan / cfg.max_ltv
    from_savings = h.savings / (1 - cfg.max_ltv) if cfg.max_ltv < 1 else 1e12
    return min(from_loan, from_savings)


# ===========================================================================
# Phases
# ===========================================================================

def phase_aging(world: World) -> None:
    """Age everyone one year; clear per-year transient flags."""
    for h in world.households:
        h.age += 1
        h.housing_cost_last_year = 0.0
        h.first_time_buyer = False
    for p in world.properties:
        p.age += 1


def phase_income_drift(world: World, rng: np.random.Generator) -> None:
    """Incomes drift with shocks; households save 10% of income."""
    factors = np.clip(rng.normal(1.02, 0.05, len(world.households)), 0.7, 1.5)
    for h, f in zip(world.households, factors):
        h.income *= float(f)
        h.savings += h.income * 0.10


def phase_depreciation(world: World, cfg: PolicyConfig) -> None:
    """Tokyo-style: building value decays ~3.3%/y; rebuilt after ~30y."""
    if not cfg.depreciation:
        return
    for p in world.properties:
        p.building_value *= 0.967
        if p.building_value < (p.land_value + p.building_value) * 0.05 and p.age > 30:
            # Demolish and rebuild — building restored, land unchanged
            p.building_value = p.land_value * 1.5
            p.age = 0
            p.condition = 1.0
        p.update_value()


def phase_collect_rents(world: World, cfg: PolicyConfig) -> None:
    """Landlords collect rent; renters pay; owner-occupiers pay mortgages.

    Also: every household pays an implicit tax burden representing
    income tax + social security. This is what makes housing burden a
    meaningful fraction of *disposable* income, not gross.

    Real Finnish tax+SSI is roughly 30% on median incomes (effective rate
    blends progressive tax + ~7% SSI - some deductions). We approximate
    with a flat 30% which is good enough at this level of model.
    """
    pmap = {p.id: p for p in world.properties}
    DISPOSABLE_FRACTION = 0.70  # roughly net-of-tax-and-SSI

    for h in world.households:
        # The household's disposable income is what their housing cost
        # should be measured against.
        disposable = h.income * DISPOSABLE_FRACTION
        hcost = 0.0

        # Landlord income: rent received on properties they own but don't occupy
        for pid in h.properties:
            p = pmap.get(pid)
            if p is None:
                continue
            if p.occupant_id != -1 and p.occupant_id != h.id:
                # 5% gross yield × 70% net of maintenance & vacancy reserves
                h.savings += p.value * cfg.base_rent_yield * 0.7

        # Mortgage payments — actual amortization
        # We compute total mortgage cost across ALL the household's mortgages.
        # The portion attributed to their *residence* is housing cost;
        # the portion on rental properties offsets rental income.
        for m in h.mortgages:
            if m.balance <= 0:
                continue
            paid = amortize_year(m)
            h.savings -= paid
            if m.property_id == h.residence:
                hcost += paid
            # For rental mortgages, payment is just an investment cost
            # already netted into savings; don't count toward housing burden

        # Renter: pay rent
        if h.is_renter and h.residence != -1:
            p = pmap.get(h.residence)
            if p is not None:
                rate = cfg.public_rent_yield if p.is_public else cfg.base_rent_yield
                rent = p.value * rate
                h.savings -= rent
                hcost += rent

        # Owner-occupier without mortgage: maintenance + property tax proxy.
        # Properties depreciate (~1%/year) and there's annual upkeep cost,
        # plus implicit property tax. Total ~2% of value for a paid-off home.
        if not h.is_renter and h.residence != -1:
            p = pmap.get(h.residence)
            if p is not None:
                has_mortgage = any(m.property_id == h.residence and m.balance > 0
                                   for m in h.mortgages)
                if not has_mortgage:
                    upkeep = p.value * 0.020
                    h.savings -= upkeep
                    hcost += upkeep
                else:
                    # Mortgage holders ALSO pay upkeep + property tax,
                    # though smaller because much of "housing cost" is the
                    # mortgage itself. Use ~0.8% for ongoing operating cost.
                    upkeep = p.value * 0.008
                    h.savings -= upkeep
                    hcost += upkeep

        # Living tax burden charged against income tracker
        # (we don't actually move money since income is gross and we never
        # added the disposable portion to savings; this just keeps the
        # burden ratio honest)
        h.housing_cost_last_year = hcost


def phase_construction(
    world: World, cfg: PolicyConfig, rng: np.random.Generator
) -> None:
    """Add new units to the stock; a fraction are public housing."""
    n_new = int(len(world.properties) * cfg.construction_rate)
    n_public = int(n_new * cfg.public_share)
    next_id = max((p.id for p in world.properties), default=-1) + 1
    for i in range(n_new):
        q = float(np.clip(rng.normal(1.05, 0.2), 0.5, 1.7))
        total = 180_000 * q
        p = Property(
            id=next_id,
            quality=q,
            condition=1.0,
            land_value=total * 0.4,
            building_value=total * 0.6,
            age=0,
            is_public=(i < n_public),
        )
        p.update_value()
        world.properties.append(p)
        next_id += 1


def phase_forced_sales(world: World, rng: np.random.Generator) -> List[Tuple]:
    """
    Death and retirement put units on the market.

    Returns a list of (seller, property) tuples for the marketplace phase.
    Note that public housing doesn't get sold — it stays in the public pool.
    """
    pmap = {p.id: p for p in world.properties}
    listings: List[Tuple] = []
    rolls = rng.random(len(world.households))

    for h, r in zip(world.households, rolls):
        if h.age > 80 and r < 0.15:
            # Sell everything (modeling death/move-to-care)
            for pid in list(h.properties):
                p = pmap.get(pid)
                if p is None or p.is_public:
                    continue
                listings.append((h, p))
                h.properties.remove(pid)
                if h.residence == pid:
                    h.residence = -1
                p.owner_id = -1
                if p.occupant_id == h.id:
                    p.occupant_id = -1
        elif h.age > 65 and r < 0.03 and len(h.properties) > 1:
            # Retiree downsizes — sell the last property
            pid = h.properties[-1]
            p = pmap.get(pid)
            if p is not None and not p.is_public:
                listings.append((h, p))
                h.properties.pop()
                p.owner_id = -1
                if p.occupant_id == h.id:
                    p.occupant_id = -1

    # Also list newly-built non-public properties
    listed_ids = {p.id for _, p in listings}
    for p in world.properties:
        if p.owner_id == -1 and not p.is_public and p.id not in listed_ids:
            listings.append((None, p))

    return listings


def phase_public_allocation(world: World) -> None:
    """
    Allocate empty public units to lowest-income needy households.
    'Needy' = homeless or currently rent-burdened (>30% of income).
    """
    public_empty = [p for p in world.properties if p.is_public and p.occupant_id == -1]
    if not public_empty:
        return

    def is_needy(h: Household) -> bool:
        if h.residence == -1:
            return True
        if h.is_renter and h.income > 0 and h.housing_cost_last_year / h.income > 0.30:
            return True
        return False

    needy = sorted([h for h in world.households if is_needy(h)],
                   key=lambda x: x.income)
    pmap = {p.id: p for p in world.properties}

    for p, h in zip(public_empty, needy):
        if h.residence != -1:
            old = pmap.get(h.residence)
            if old is not None and old.occupant_id == h.id:
                old.occupant_id = -1
        h.residence = p.id
        h.is_renter = True
        p.occupant_id = h.id


def phase_marketplace(
    world: World, cfg: PolicyConfig, listings: List[Tuple], rng: np.random.Generator
) -> Tuple[List[Tuple], int]:
    """
    Match buyers with listings.

    Wealthier buyers get pick of more expensive properties. Renters who can
    afford something become primary buyers; existing owners occasionally
    become investors.

    Returns the still-available listings and the count of unmet primary
    buyers (used by price drift).
    """
    pmap = {p.id: p for p in world.properties}
    rolls = rng.random(len(world.households))

    buyers = []
    for h, r in zip(world.households, rolls):
        max_price = max_purchase_price(h, cfg)
        if max_price < 50_000:
            continue
        if h.is_renter and h.residence != -1:
            buyers.append((h, max_price, "primary"))
        elif not h.is_renter and len(h.properties) >= 1 and r < 0.05:
            # Investor interest; multi-home tax burden lives in formula
            # policies, not here, so we don't discount the probability.
            buyers.append((h, max_price, "invest"))

    buyers.sort(key=lambda b: b[1], reverse=True)

    # Sort listings by value descending. Use a "taken" mask to mark
    # purchased properties without rebuilding the list. Buyers (richest
    # first) scan from the front and take the first untaken listing
    # within budget. This is O((N+M) log M) vs the previous O(N*M).
    sorted_listings = sorted(listings, key=lambda x: x[1].value, reverse=True)
    n_listings = len(sorted_listings)
    taken = [False] * n_listings
    available_count = n_listings
    unmet_primary = 0

    # Pointer cache: each buyer starts scanning from `start_idx`, the
    # first listing they could possibly afford (skipping listings priced
    # above their budget). Since buyers are sorted richest-first, each
    # poorer buyer's start_idx only moves forward, never back.
    start_idx = 0

    for buyer, max_price, kind in buyers:
        if available_count == 0:
            if kind == "primary":
                unmet_primary += 1
            continue

        # Advance start_idx to first listing within this buyer's budget.
        while start_idx < n_listings and sorted_listings[start_idx][1].value > max_price:
            start_idx += 1
        if start_idx >= n_listings:
            if kind == "primary":
                unmet_primary += 1
            continue

        # Search through affordable listings; for each candidate run the
        # match acceptance roll. Limit to MAX_VIEWINGS to keep complexity
        # bounded and to model finite buyer patience within a year.
        # Empirically, US buyers see ~8-10 homes before deciding, but most
        # don't end up offering on the first few; only a few make it to
        # offer stage. Lower limit makes pickiness have visible effect.
        MAX_VIEWINGS = 5
        idx = start_idx
        viewings = 0
        accepted = False
        while idx < n_listings and viewings < MAX_VIEWINGS:
            if taken[idx]:
                idx += 1
                continue
            viewings += 1
            seller, prop = sorted_listings[idx]
            v = prop.value
            sale_price = min((v + max_price) * 0.5, max_price)
            down_payment = sale_price * (1 - cfg.max_ltv)
            if buyer.savings < down_payment:
                idx += 1
                continue

            # Match acceptance: rolled once per (buyer, property) viewing.
            # Acceptance probability depends on:
            #   - price stretch: how close to buyer's max are they paying?
            #     stretch near 1.0 means stretching to absolute ceiling.
            #   - quality fit: distance between property quality and the
            #     buyer's preferred quality (both in [0.4, 1.8]).
            # When cfg.match_pickiness = 0, acceptance is always 1.0
            # (frictionless market). At pickiness = 1, only good matches
            # at comfortable price get accepted with reasonable probability.
            # Note: this only applies to primary buyers, not investors
            # (investors care only about cash flow, not personal fit).
            if cfg.match_pickiness > 0 and kind == "primary":
                stretch = sale_price / max_price  # 0..1
                quality_dist = abs(prop.quality - buyer.quality_preference)
                # Acceptance falls with both stretch and quality distance,
                # scaled by pickiness. Tuned so at pickiness=0.5:
                #   stretch=0.7, q_dist=0.1 -> p_accept ≈ 0.55
                #   stretch=0.9, q_dist=0.3 -> p_accept ≈ 0.25
                penalty = (
                    1.2 * stretch * cfg.match_pickiness +
                    2.0 * quality_dist * cfg.match_pickiness
                )
                p_accept = max(0.02, 1.0 - penalty)
                if rng.random() > p_accept:
                    idx += 1
                    continue  # rejected; try the next listing

            # Accepted — execute the deal
            buyer.savings -= down_payment
            if seller is not None:
                cgt = 0.0
                if kind == "invest" or len(seller.properties) > 0:
                    cgt = max(0.0, sale_price - v) * 0.30
                # Seller must pay off any outstanding mortgage on this property
                # from the proceeds before pocketing the rest.
                outstanding = 0.0
                seller_mortgages = [m for m in seller.mortgages
                                    if m.property_id == prop.id]
                for m in seller_mortgages:
                    outstanding += m.balance
                    m.balance = 0.0
                    m.years_remaining = 0
                seller.mortgages = [m for m in seller.mortgages
                                    if m.property_id != prop.id]
                seller.savings += sale_price - cgt - outstanding

            prop.owner_id = buyer.id
            ratio = prop.building_value / max(1.0, v)
            prop.building_value = sale_price * ratio
            prop.land_value = sale_price * (1 - ratio)
            prop.update_value()
            buyer.properties.append(prop.id)

            # Originate a mortgage for the financed portion (sale - down).
            financed = sale_price - down_payment
            if financed > 0:
                buyer.mortgages.append(create_mortgage(
                    property_id=prop.id,
                    principal=financed,
                    annual_rate=cfg.mortgage_rate,
                    term_years=cfg.max_loan_years,
                ))

            if kind == "primary":
                if not buyer.has_owned_before:
                    buyer.first_time_buyer = True
                    buyer.has_owned_before = True
                if buyer.residence != -1:
                    old = pmap.get(buyer.residence)
                    if old is not None and old.occupant_id == buyer.id:
                        old.occupant_id = -1
                buyer.residence = prop.id
                buyer.is_renter = False
                buyer.landlord_id = -1
                prop.occupant_id = buyer.id

            taken[idx] = True
            available_count -= 1
            accepted = True
            break

        if not accepted and kind == "primary":
            unmet_primary += 1

    # Return remaining listings for price-drift calculation
    available = [sorted_listings[i] for i in range(n_listings) if not taken[i]]
    return available, unmet_primary


def phase_rental_matching(world: World, cfg: PolicyConfig) -> None:
    """Remaining empty privately-owned units rent to homeless households.

    Same sorted+mask trick as the marketplace: sort empties by value desc,
    walk start pointer forward per (richer-first) homeless household.
    """
    empty = sorted(
        [p for p in world.properties
         if p.owner_id != -1 and p.occupant_id == -1 and not p.is_public],
        key=lambda p: p.value, reverse=True,
    )
    homeless = sorted(
        [h for h in world.households if h.residence == -1],
        key=lambda h: h.income, reverse=True,
    )
    if not empty or not homeless:
        return

    n = len(empty)
    taken = [False] * n
    start_idx = 0

    for h in homeless:
        budget_value = (h.income * 0.30) / cfg.base_rent_yield * 1.2
        while start_idx < n and empty[start_idx].value > budget_value:
            start_idx += 1
        if start_idx >= n:
            break
        idx = start_idx
        while idx < n and taken[idx]:
            idx += 1
        if idx >= n:
            break
        p = empty[idx]
        h.residence = p.id
        h.is_renter = True
        h.landlord_id = p.owner_id
        p.occupant_id = h.id
        taken[idx] = True


def phase_maintenance(world: World) -> None:
    """
    Properties under owner-occupancy improve; rented decline; vacant decline fast.
    Mechanism: this is your 'defect multiplier' from the original spec.
    """
    for p in world.properties:
        if p.owner_id == -1 and not p.is_public:
            continue
        if p.occupant_id != -1 and p.occupant_id == p.owner_id:
            p.condition = min(1.0, p.condition + 0.02)
        elif p.occupant_id != -1:
            p.condition = max(0.0, p.condition - 0.01)
        else:
            p.condition = max(0.0, p.condition - 0.03)


def phase_price_drift(
    world: World, cfg: "PolicyConfig", available_count: int, unmet: int
) -> None:
    """
    Prices move toward what buyers can actually pay, plus a short-run
    supply/demand pressure term.

    Economic logic: in any housing market the clearing price is anchored by
    purchasing power — what the marginal buyer can borrow plus their down
    payment. When mortgage rates rise (or loan terms shorten, or LTV caps
    tighten), max_purchase_price falls for everyone, and prices must fall to
    clear. This anchor is the dominant long-run force. On top of it we keep a
    smaller momentum/scarcity term for short-run dynamics.

    We compute the median buyer's max purchase price, compare it to the
    current median property price, and nudge all prices a fraction of the way
    toward the implied level each year (sticky prices — housing doesn't
    reprice instantly, it drifts over a few years).
    """
    # --- Purchasing-power anchor -------------------------------------------
    # Sample max purchase price across all households (not just active buyers,
    # so the anchor is stable). This reflects the credit environment: rate,
    # term, LTV, and the income distribution.
    powers = []
    for h in world.households:
        mp = max_purchase_price(h, cfg)
        if mp > 20_000:  # ignore households who can't buy anything
            powers.append(mp)
    if powers:
        powers.sort()
        median_power = powers[len(powers) // 2]
    else:
        median_power = 0.0

    owned_prices = sorted(p.value for p in world.properties if p.owner_id != -1)
    if owned_prices:
        median_price = owned_prices[len(owned_prices) // 2]
    else:
        median_price = 1.0

    if median_price > 0 and median_power > 0:
        # The market-clearing price isn't exactly the median buyer's ceiling;
        # historically homes trade around 75-90% of the median qualified
        # buyer's max (people don't all stretch to their absolute limit).
        target_price = median_power * 0.85
        # Ratio of where prices "should" be vs where they are.
        gap = target_price / median_price
        # Sticky adjustment: move ~20% of the way toward target per year.
        # Clamp the annual move to ±15% so a big rate shock takes a few
        # years to fully transmit (realistic — housing is sticky downward).
        anchor_drift = 1.0 + 0.20 * (gap - 1.0)
        anchor_drift = max(0.85, min(1.15, anchor_drift))
    else:
        anchor_drift = 1.0

    # --- Short-run supply/demand pressure ----------------------------------
    supply = max(1, available_count)
    pressure = unmet / supply
    pressure_drift = 1.0 + 0.03 * math.tanh(pressure - 1.0)

    # Combined: anchor dominates, pressure is a smaller modulation.
    drift = anchor_drift * pressure_drift

    for p in world.properties:
        if p.owner_id != -1:
            p.building_value *= drift
            p.land_value *= drift
            p.update_value()


def phase_bankruptcy(world: World) -> None:
    """
    Households with deep negative savings fire-sell their cheapest property
    at a 20% discount until they're solvent again.
    """
    pmap = {p.id: p for p in world.properties}
    for h in world.households:
        while h.savings < -50_000 and h.properties:
            cheapest = min(h.properties, key=lambda pid: pmap[pid].value)
            p = pmap[cheapest]
            # Fire-sale discount: 20% off market value
            sale_proceeds = p.value * 0.8
            # Pay off any mortgage on this property from the proceeds
            outstanding = 0.0
            for m in h.mortgages:
                if m.property_id == cheapest:
                    outstanding += m.balance
                    m.balance = 0.0
                    m.years_remaining = 0
            h.mortgages = [m for m in h.mortgages if m.property_id != cheapest]
            # Net proceeds to seller (can be negative if underwater)
            h.savings += sale_proceeds - outstanding
            p.building_value *= 0.8
            p.land_value *= 0.8
            p.update_value()
            p.owner_id = -1
            if p.occupant_id == h.id:
                p.occupant_id = -1
            h.properties.remove(cheapest)
            if h.residence == cheapest:
                h.residence = -1
                h.is_renter = True


def phase_formula_policies(world: World, cfg: PolicyConfig) -> None:
    """
    Run all enabled formula policies once per household per policy.
    Per-property policies run once per property the household owns.
    """
    policies = [p for p in cfg.formula_policies if p.enabled]
    if not policies:
        return

    pmap = {p.id: p for p in world.properties}
    incomes = sorted(h.income for h in world.households)
    prices = sorted(p.value for p in world.properties if p.owner_id != -1)
    median_income = incomes[len(incomes) // 2] if incomes else 0.0
    median_price = prices[len(prices) // 2] if prices else 0.0
    year = world.year

    for policy in policies:
        slider = policy.slider_value
        for h in world.households:
            # Build household view
            residence_value = (pmap[h.residence].value
                               if h.residence != -1 and h.residence in pmap else 0.0)
            total_prop_value = sum(pmap[pid].value for pid in h.properties if pid in pmap)
            h_view = HouseholdView(h, residence_value, total_prop_value)

            if policy.per_prop:
                # Run once per property and sum
                total = 0.0
                for idx, pid in enumerate(h.properties, start=1):
                    p = pmap.get(pid)
                    if p is None:
                        continue
                    p_view = PropertyView(
                        p,
                        is_residence=(pid == h.residence),
                        is_rented=(p.occupant_id != -1 and p.occupant_id != h.id),
                        is_vacant=(p.occupant_id == -1),
                        property_index=idx,
                    )
                    ns = {
                        "h": h_view, "p": p_view, "slider": slider,
                        "median_income": median_income, "median_price": median_price,
                        "year": year,
                    }
                    total += policy.evaluate(ns)
                h.savings += total
            else:
                # Run once per household with a dummy property view if any owned
                p_view = None
                if h.properties:
                    p = pmap.get(h.properties[0])
                    if p is not None:
                        p_view = PropertyView(
                            p,
                            is_residence=(p.id == h.residence),
                            is_rented=(p.occupant_id != -1 and p.occupant_id != h.id),
                            is_vacant=(p.occupant_id == -1),
                            property_index=1,
                        )
                ns = {
                    "h": h_view, "p": p_view, "slider": slider,
                    "median_income": median_income, "median_price": median_price,
                    "year": year,
                }
                h.savings += policy.evaluate(ns)


# ===========================================================================
# Top-level step
# ===========================================================================

def step(world: World, cfg: PolicyConfig, rng: np.random.Generator) -> None:
    """Advance the world by one year."""
    world.year += 1
    phase_aging(world)
    phase_income_drift(world, rng)
    phase_depreciation(world, cfg)
    phase_collect_rents(world, cfg)
    phase_construction(world, cfg, rng)
    listings = phase_forced_sales(world, rng)
    phase_public_allocation(world)
    available, unmet = phase_marketplace(world, cfg, listings, rng)
    phase_rental_matching(world, cfg)
    phase_maintenance(world)
    phase_price_drift(world, cfg, len(available), unmet)
    phase_bankruptcy(world)
    phase_formula_policies(world, cfg)
