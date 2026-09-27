"""Deterministic finance math.

Every number shown on screen is computed here, never by the language model.
Claude chooses the scenario (e.g. "$200/month at 7% for 30 years"); this module
does the arithmetic, and the verified results are fed back into the script
review so the narration matches the chart exactly.

Conventions: monthly compounding, contributions/payments at month end.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GrowthResult:
    years: list[int]                 # 0..N
    balance: list[float]             # balance at end of each year
    contributed: list[float]         # cumulative money put in
    final_balance: float
    total_contributed: float
    total_growth: float


def compound_growth(
    *, initial: float = 0.0, monthly: float = 0.0, annual_rate_pct: float, years: int,
) -> GrowthResult:
    """Future value with monthly compounding and monthly contributions."""
    if years <= 0:
        raise ValueError("years must be positive")
    if years > 80:
        raise ValueError("years must be 80 or fewer")
    r = annual_rate_pct / 100 / 12
    bal = float(initial)
    put_in = float(initial)
    yrs, bals, contrib = [0], [bal], [put_in]
    for month in range(1, years * 12 + 1):
        bal = bal * (1 + r) + monthly
        put_in += monthly
        if month % 12 == 0:
            yrs.append(month // 12)
            bals.append(bal)
            contrib.append(put_in)
    return GrowthResult(
        years=yrs, balance=bals, contributed=contrib,
        final_balance=bal, total_contributed=put_in, total_growth=bal - put_in,
    )


@dataclass
class PayoffResult:
    months: int                      # months to pay off (0 if never)
    paid_off: bool
    total_interest: float
    total_paid: float
    balance_by_month: list[float] = field(default_factory=list)


def debt_payoff(
    *, balance: float, apr_pct: float, monthly_payment: float, max_months: int = 600,
) -> PayoffResult:
    """Months and interest to pay off a balance with a fixed monthly payment."""
    if balance <= 0:
        raise ValueError("balance must be positive")
    r = apr_pct / 100 / 12
    bal = float(balance)
    interest_total = 0.0
    paid = 0.0
    series = [bal]
    months = 0
    while bal > 0.005 and months < max_months:
        interest = bal * r
        if monthly_payment <= interest:
            return PayoffResult(
                months=0, paid_off=False, total_interest=float("inf"),
                total_paid=float("inf"), balance_by_month=series,
            )
        interest_total += interest
        payment = min(monthly_payment, bal + interest)
        bal = bal + interest - payment
        paid += payment
        months += 1
        series.append(max(bal, 0.0))
    return PayoffResult(
        months=months, paid_off=bal <= 0.005, total_interest=interest_total,
        total_paid=paid, balance_by_month=series,
    )


@dataclass
class InflationResult:
    years: list[int]
    purchasing_power: list[float]    # today's-money value of `amount` each year
    final_value: float
    percent_lost: float


def inflation_erosion(*, amount: float, inflation_rate_pct: float, years: int) -> InflationResult:
    """What `amount` of cash is worth in today's money after `years` of inflation."""
    if years <= 0:
        raise ValueError("years must be positive")
    i = inflation_rate_pct / 100
    yrs = list(range(0, years + 1))
    vals = [amount / (1 + i) ** t for t in yrs]
    return InflationResult(
        years=yrs, purchasing_power=vals, final_value=vals[-1],
        percent_lost=(1 - vals[-1] / amount) * 100 if amount else 0.0,
    )


def years_months(months: int) -> str:
    """38 -> '3 years 2 months'."""
    y, m = divmod(months, 12)
    parts = []
    if y:
        parts.append(f"{y} year{'s' if y != 1 else ''}")
    if m or not parts:
        parts.append(f"{m} month{'s' if m != 1 else ''}")
    return " ".join(parts)
