"""
Top-level simulation runner.

Use this from a notebook, CLI, or API. Returns a list of per-year metric
dicts so it's easy to convert to a pandas DataFrame for analysis.

Performance:
- World initialization is the same for any given (seed, N, M, demographics)
  combination, so we cache initial worlds keyed on a hash of those inputs.
  Each cached world is deep-copied before use so the cache doesn't get
  mutated by the simulation.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from typing import Dict, List

from .metrics import compute_metrics
from .policies import PolicyConfig
from .step import step
from .world import Demographics, init_world


def _demographics_key(d: Demographics | None) -> tuple:
    """Hashable representation of demographics for the LRU cache."""
    if d is None:
        d = Demographics()
    return (d.income_log_mu, d.income_log_sigma, d.age_mean, d.age_sd,
            d.base_price, d.land_fraction,
            d.initial_owner_share, d.initial_investor_share,
            d.quality_pref_spread)


@lru_cache(maxsize=32)
def _cached_init_raw(n_households: int, n_properties: int, seed: int, demo_key: tuple):
    """Cache initial world state by (seed, N, M, demographics)."""
    # Rebuild demographics from the key
    demographics = Demographics(
        income_log_mu=demo_key[0], income_log_sigma=demo_key[1],
        age_mean=demo_key[2], age_sd=demo_key[3],
        base_price=demo_key[4], land_fraction=demo_key[5],
        initial_owner_share=demo_key[6], initial_investor_share=demo_key[7],
        quality_pref_spread=demo_key[8],
    )
    world, _ = init_world(
        n_households=n_households,
        n_properties=n_properties,
        seed=seed,
        demographics=demographics,
    )
    return world.households, world.properties


def run_simulation(
    cfg: PolicyConfig,
    years: int = 50,
    n_households: int = 2000,
    n_properties: int = 1800,
    seed: int = 42,
    demographics: Demographics | None = None,
    record_year_0: bool = True,
) -> List[Dict[str, float]]:
    """Run a full simulation. Returns one metric dict per simulated year."""
    import numpy as np
    from .agents import World

    households, properties = _cached_init_raw(
        n_households, n_properties, seed, _demographics_key(demographics),
    )
    world = World(
        households=copy.deepcopy(households),
        properties=copy.deepcopy(properties),
        year=0,
    )
    rng = np.random.default_rng(seed + 1)

    history: List[Dict[str, float]] = []
    if record_year_0:
        m = compute_metrics(world)
        m["year"] = 0
        history.append(m)
    for _ in range(years):
        step(world, cfg, rng)
        m = compute_metrics(world)
        m["year"] = world.year
        history.append(m)
    return history


PRESETS: Dict[str, Dict] = {
    "baseline": dict(max_loan_years=25, max_ltv=0.90, construction_rate=0.005,
                     public_share=0.0, depreciation=False,
                     multi_home_tax=0.0, vacancy_tax=0.0),
    "loan10":   dict(max_loan_years=10, max_ltv=0.85, construction_rate=0.005,
                     public_share=0.0, depreciation=False,
                     multi_home_tax=0.0, vacancy_tax=0.0),
    "tokyo":    dict(max_loan_years=25, max_ltv=0.90, construction_rate=0.04,
                     public_share=0.0, depreciation=True,
                     multi_home_tax=0.0, vacancy_tax=0.0),
    "vienna":   dict(max_loan_years=25, max_ltv=0.90, construction_rate=0.015,
                     public_share=0.60, depreciation=False,
                     multi_home_tax=10.0, vacancy_tax=10.0),
    "combined": dict(max_loan_years=10, max_ltv=0.80, construction_rate=0.030,
                     public_share=0.20, depreciation=True,
                     multi_home_tax=30.0, vacancy_tax=40.0),
}
