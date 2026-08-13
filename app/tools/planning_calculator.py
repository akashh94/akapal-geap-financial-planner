"""Financial planning calculator tools for the planner agent.

Pure-python time-value-of-money helpers (FV / PV / PMT / NPER) so the planner
can answer concrete planning questions without a heavy dependency.

Sign convention: POSITIVE payments are money in (contributions that grow a
balance), NEGATIVE payments are money out (withdrawals). Callers pass
positive monthly_contribution and positive monthly_withdrawal; the helpers
handle the sign internally.
"""

from __future__ import annotations

import math
from typing import Any


def _round2(value: float) -> float:
    return round(value, 2)


def future_value(
    present_value: float,
    rate_per_period: float,
    n_periods: float,
    payment: float = 0.0,
    payment_at_beginning: bool = False,
) -> float:
    """Future value of an investment.

    Args:
        present_value: Current amount invested.
        rate_per_period: Periodic interest rate (e.g. 0.05/12 for monthly).
        n_periods: Number of periods.
        payment: Periodic contribution (positive = money in, negative = money out).
        payment_at_beginning: True if payments occur at the start of each period.
    """
    if rate_per_period == 0:
        return _round2(present_value + payment * n_periods)
    fvif = (1 + rate_per_period) ** n_periods
    fv = present_value * fvif
    if payment:
        factor = (fvif - 1) / rate_per_period
        if payment_at_beginning:
            factor *= 1 + rate_per_period
        fv += payment * factor
    return _round2(fv)


def present_value(
    future_value_: float,
    rate_per_period: float,
    n_periods: float,
    payment: float = 0.0,
) -> float:
    """Present value of a future sum or stream of payments.

    ``payment`` is positive for money in: future contributions reduce the
    lump sum you need today, so they are subtracted.
    """
    if rate_per_period == 0:
        return _round2(future_value_ - payment * n_periods)
    pvif = (1 + rate_per_period) ** -n_periods
    pv = future_value_ * pvif
    if payment:
        annuity = (1 - pvif) / rate_per_period
        pv -= payment * annuity
    return _round2(pv)


def payment(
    present_value: float,
    rate_per_period: float,
    n_periods: float,
    future_value_: float = 0.0,
    payment_at_beginning: bool = False,
) -> float:
    """Periodic payment needed to amortize a loan or hit a savings goal.

    Returns a positive value for a savings contribution and a negative value
    for a loan payment (money out).
    """
    if rate_per_period == 0:
        return _round2((future_value_ - present_value) / n_periods)
    fvif = (1 + rate_per_period) ** n_periods
    denominator = ((fvif - 1) / rate_per_period) * (
        1 + rate_per_period if payment_at_beginning else 1
    )
    return _round2((future_value_ - present_value * fvif) / denominator)


def n_periods(
    present_value: float,
    rate_per_period: float,
    payment: float,
    future_value_: float,
) -> float:
    """Number of periods to reach a goal (used for 'when can I retire').

    Closed-form NPER for payments at the start of each period, matching
    ``future_value``'s ``payment_at_beginning`` convention: a positive
    payment is money flowing into the account, a negative payment is money
    flowing out (e.g. retirement withdrawals).
    """
    if rate_per_period == 0:
        if payment == 0:
            raise ValueError("Cannot determine periods with no rate and no payment.")
        return _round2((future_value_ - present_value) / payment)
    if payment == 0:
        if present_value == 0:
            return 0.0
        return _round2(
            math.log(future_value_ / present_value) / math.log(1 + rate_per_period)
        )
    # n = log((payment*(1+r) + fv*r) / (payment*(1+r) + pv*r)) / log(1+r).
    # A positive n requires the ratio to exceed 1, which means the two
    # terms must share a sign and the numerator's magnitude must be larger.
    num = payment * (1 + rate_per_period) + future_value_ * rate_per_period
    den = payment * (1 + rate_per_period) + present_value * rate_per_period
    if num * den <= 0 or abs(num) <= abs(den):
        raise ValueError("Goal is not reachable with the given payment and rate.")
    return _round2(math.log(num / den) / math.log(1 + rate_per_period))


def retirement_projection(
    current_age: int,
    retirement_age: int,
    current_savings: float,
    monthly_contribution: float,
    expected_annual_return: float,
    monthly_withdrawal: float,
    life_expectancy: int,
) -> dict[str, Any]:
    """Project retirement savings at retirement age and its depletion age.

    Args:
        current_age: Current age in years.
        retirement_age: Planned retirement age.
        current_savings: Current retirement balance.
        monthly_contribution: Monthly amount saved until retirement (positive).
        expected_annual_return: Expected annual return (e.g. 0.06 for 6%).
        monthly_withdrawal: Monthly amount withdrawn in retirement (positive).
        life_expectancy: Age to which the user expects to live.

    Returns a dict with the projected balance at retirement, how long the
    nest egg lasts, and whether the plan is sustainable.
    """
    years_to_retirement = max(0, retirement_age - current_age)
    monthly_rate = expected_annual_return / 12.0
    n_months = years_to_retirement * 12

    balance_at_retirement = future_value(
        present_value=current_savings,
        rate_per_period=monthly_rate,
        n_periods=n_months,
        payment=monthly_contribution,
        payment_at_beginning=True,
    )

    if balance_at_retirement <= 0:
        return {
            "balance_at_retirement": 0.0,
            "years_nest_egg_lasts": 0.0,
            "sustainable": False,
            "reason": "Projected balance at retirement is non-positive.",
        }

    # How many months can the balance fund the monthly withdrawal? Withdrawals
    # are money out, so they pass as a NEGATIVE payment to n_periods (which
    # expects positive = money in). A negative balance means the nest egg
    # grows faster than it is withdrawn → never depletes.
    if monthly_withdrawal <= 0:
        months = float("inf")
    else:
        try:
            months = n_periods(
                present_value=balance_at_retirement,
                rate_per_period=monthly_rate,
                payment=-monthly_withdrawal,
                future_value_=0.0,
            )
        except ValueError:
            # Withdrawals never deplete the balance (returns outpace spending).
            months = float("inf")
    years_nest_egg_lasts = months if months == float("inf") else months / 12.0
    retirement_span = max(0, life_expectancy - retirement_age)
    sustainable = (
        years_nest_egg_lasts == float("inf") or years_nest_egg_lasts >= retirement_span
    )

    return {
        "balance_at_retirement": balance_at_retirement,
        "years_nest_egg_lasts": years_nest_egg_lasts,
        "retirement_span_needed": retirement_span,
        "sustainable": sustainable,
        "monthly_contribution_needed": None,
    }


def savings_goal_projection(
    goal_amount: float,
    current_savings: float,
    monthly_contribution: float,
    expected_annual_return: float,
    years: float,
) -> dict[str, Any]:
    """Project progress toward a savings goal after ``years``."""
    balance = future_value(
        present_value=current_savings,
        rate_per_period=expected_annual_return / 12.0,
        n_periods=years * 12,
        payment=monthly_contribution,
        payment_at_beginning=True,
    )
    return {
        "projected_balance": balance,
        "goal_amount": goal_amount,
        "gap": _round2(goal_amount - balance),
        "on_track": balance >= goal_amount,
    }
