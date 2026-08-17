"""Mortgage math utilities.

Annual amortization: we collapse 12 monthly payments per simulation year.
"""
from __future__ import annotations

import math

from .agents import Mortgage


def monthly_payment_amount(principal: float, annual_rate: float, term_years: int) -> float:
    """Standard amortizing mortgage payment.

    monthly_payment = P * r(1+r)^n / ((1+r)^n - 1)
    where r = monthly rate, n = total months.
    """
    r = annual_rate / 12.0
    n = term_years * 12
    if r <= 0:
        return principal / n if n > 0 else principal
    return principal * r * math.pow(1 + r, n) / (math.pow(1 + r, n) - 1)


def amortize_year(m: Mortgage) -> float:
    """
    Apply one year of payments. Returns total cash paid (interest + principal).
    Mutates m.balance and m.years_remaining in place.
    """
    if m.years_remaining <= 0 or m.balance <= 0:
        return 0.0

    r = m.annual_rate / 12.0
    total_paid = 0.0
    payments = 12

    for _ in range(payments):
        if m.balance <= 0:
            break
        interest = m.balance * r
        principal = min(m.monthly_payment - interest, m.balance)
        if principal < 0:
            # Interest exceeds payment; shouldn't happen for sane inputs but
            # guard against it by just paying interest
            principal = 0.0
            interest = m.monthly_payment
        m.balance -= principal
        total_paid += (interest + principal)

    m.years_remaining = max(0, m.years_remaining - 1)
    return total_paid


def create_mortgage(
    property_id: int,
    principal: float,
    annual_rate: float,
    term_years: int,
) -> Mortgage:
    """Create a new mortgage with the standard amortization payment."""
    monthly = monthly_payment_amount(principal, annual_rate, term_years)
    return Mortgage(
        property_id=property_id,
        original_principal=principal,
        balance=principal,
        annual_rate=annual_rate,
        term_years=term_years,
        years_remaining=term_years,
        monthly_payment=monthly,
    )
