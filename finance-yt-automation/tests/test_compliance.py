import pytest

from finance_channel.compliance import has_critical, scan


@pytest.mark.parametrize("text,rule", [
    ("These returns are guaranteed!", "guaranteed-returns"),
    ("This strategy is risk-free.", "risk-free"),
    ("There is no risk here.", "risk-free"),
    ("You should buy TSLA today.", "specific-buy-sell-call"),
    ("Just buy $AAPL", "specific-buy-sell-call"),
    ("Go buy Tesla stock", "specific-buy-sell-call"),
    ("This is the ultimate get rich quick plan.", "get-rich-quick"),
    ("This is financial advice.", "personal-advice"),
])
def test_critical_rules(text, rule):
    findings = scan(text)
    assert any(f.rule == rule and f.severity == "critical" for f in findings), findings
    assert has_critical(findings)


@pytest.mark.parametrize("text,rule", [
    ("This stock will skyrocket.", "price-prediction"),
    ("The market always goes up.", "absolute-language"),
    ("Act now before it's too late!", "urgency-pressure"),
    ("The 2026 contribution limit is going up.", "dated-figure"),
])
def test_warning_rules(text, rule):
    findings = scan(text)
    assert any(f.rule == rule and f.severity == "warning" for f in findings), findings
    assert not has_critical(findings)


@pytest.mark.parametrize("text", [
    "Past returns are not guaranteed.",
    "No investment is risk-free.",
    "There are no guaranteed returns in investing.",
    "Historically, broad index funds have returned about 10% a year, but nothing is guaranteed.",
    "Quick note: this is general education, not financial advice.",
    "Assuming a 7% average annual return, you'd have about $244,000.",
])
def test_safe_phrasing_is_not_flagged(text):
    assert not has_critical(scan(text)), scan(text)
