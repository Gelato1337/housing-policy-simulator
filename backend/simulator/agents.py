"""
Core data classes for the housing simulation.

Performance notes:
- Using slots dataclasses to reduce per-instance memory and lookup time.
- eq=False suppresses the auto-generated __eq__/__hash__ that show up
  hot in profiles (we never compare agents structurally; identity is enough).
- Property.value is a plain attribute kept in sync via update_value(),
  not a @property — the property version was the single largest hot spot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(eq=False, slots=True)
class Mortgage:
    """A loan attached to a property.

    Tracks declining balance with monthly amortization at a fixed rate over a
    fixed term. We update yearly (12 monthly payments collapsed) for speed.
    """
    property_id: int
    original_principal: float    # initial loan amount, EUR
    balance: float               # current outstanding balance, EUR
    annual_rate: float           # nominal interest rate, e.g. 0.03 = 3%
    term_years: int              # original term, e.g. 25
    years_remaining: int         # decrements each step until 0
    monthly_payment: float       # fixed payment amount (interest+principal)


@dataclass(eq=False, slots=True)
class Household:
    """A single household agent."""
    id: int
    age: int
    income: float
    savings: float
    properties: List[int] = field(default_factory=list)
    residence: int = -1
    is_renter: bool = True
    landlord_id: int = -1
    housing_cost_last_year: float = 0.0
    first_time_buyer: bool = False
    has_owned_before: bool = False
    # Buyer's ideal property quality (0.4–1.8), drawn at init.
    quality_preference: float = 1.0
    # Active mortgages. A household can have multiple (e.g. investor with
    # several properties), each tied to a specific property by property_id.
    mortgages: List[Mortgage] = field(default_factory=list)


@dataclass(eq=False, slots=True)
class Property:
    """A single housing unit. `value` is kept in sync via update_value()."""
    id: int
    quality: float
    condition: float
    land_value: float
    building_value: float
    age: int = 0
    owner_id: int = -1
    occupant_id: int = -1
    is_public: bool = False
    value: float = 0.0  # cached = land_value + building_value

    def update_value(self) -> None:
        self.value = self.land_value + self.building_value


@dataclass(eq=False)
class World:
    """The full simulation state."""
    households: List[Household]
    properties: List[Property]
    year: int = 0
