"""Personal-finance scenario comparator.

Deterministic cash-flow projection for comparing individual housing/investing
decisions. Separate from the agent-based policy simulator.
"""
from .scenarios import (Assumptions, Scenario, VarianceConfig,
                        compare, project_scenario)
from .forecast import forecast_prices
from .historical import HISTORICAL_SERIES, get_series, list_series

__all__ = ["Assumptions", "Scenario", "VarianceConfig",
           "compare", "project_scenario",
           "forecast_prices",
           "HISTORICAL_SERIES", "get_series", "list_series"]
