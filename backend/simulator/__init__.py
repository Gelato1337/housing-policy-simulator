"""Housing market agent-based simulation.

Public API:
  - run_simulation(cfg, years, ...) -> list of metrics per year
  - PolicyConfig: simulation configuration
  - FormulaPolicy: user-defined or built-in formula policies
  - POLICY_TEMPLATES: example formula policies
  - init_world / step: lower-level primitives for custom loops
  - compute_metrics: aggregate metrics for a World
"""
from .agents import Household, Property, World
from .metrics import compute_metrics
from .policies import (
    FormulaPolicy,
    POLICY_TEMPLATES,
    PolicyConfig,
    progressive_multi_home_tax,
    vacancy_tax,
)
from .runner import PRESETS, run_simulation
from .step import step
from .world import Demographics, init_world

__all__ = [
    "Household", "Property", "World",
    "init_world", "Demographics", "step",
    "compute_metrics",
    "PolicyConfig", "FormulaPolicy", "POLICY_TEMPLATES", "PRESETS",
    "progressive_multi_home_tax", "vacancy_tax",
    "run_simulation",
]
