import math

import pytest

from finance_channel import finance_math as fm


def test_compound_growth_matches_closed_form():
    g = fm.compound_growth(monthly=200, annual_rate_pct=7, years=30)
    r, n = 0.07 / 12, 360
    expected = 200 * ((1 + r) ** n - 1) / r
    assert math.isclose(g.final_balance, expected, rel_tol=1e-9)
    assert g.total_contributed == 72_000
    assert math.isclose(g.total_growth, expected - 72_000, rel_tol=1e-9)
    assert len(g.years) == 31 and g.years[-1] == 30


def test_compound_growth_with_initial_and_zero_rate():
    g = fm.compound_growth(initial=1000, monthly=100, annual_rate_pct=0, years=2)
    assert g.final_balance == pytest.approx(1000 + 2400)
    assert g.total_growth == pytest.approx(0)


def test_compound_growth_rejects_bad_years():
    with pytest.raises(ValueError):
        fm.compound_growth(monthly=1, annual_rate_pct=5, years=0)


def test_debt_payoff_known_case():
    p = fm.debt_payoff(balance=5000, apr_pct=22, monthly_payment=150)
    assert p.paid_off
    assert p.months == 52
    assert p.total_paid == pytest.approx(5000 + p.total_interest)
    assert p.balance_by_month[-1] == pytest.approx(0, abs=0.01)


def test_debt_payoff_never_when_payment_below_interest():
    p = fm.debt_payoff(balance=10_000, apr_pct=24, monthly_payment=150)  # interest 200/mo
    assert not p.paid_off
    assert math.isinf(p.total_interest)


def test_inflation_erosion():
    r = fm.inflation_erosion(amount=10_000, inflation_rate_pct=3, years=20)
    assert r.final_value == pytest.approx(10_000 / 1.03 ** 20)
    assert 44 < r.percent_lost < 46


def test_years_months():
    assert fm.years_months(38) == "3 years 2 months"
    assert fm.years_months(12) == "1 year"
    assert fm.years_months(1) == "1 month"
