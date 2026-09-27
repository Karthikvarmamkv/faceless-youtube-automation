import pytest

from finance_channel import charts
from finance_channel.schemas import ChartSpec, StatSpec, VideoPlan, to_strict_json_schema


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_strict_schema_is_self_contained_and_closed():
    schema = to_strict_json_schema(VideoPlan)
    assert "$defs" not in schema
    for node in _walk(schema):
        assert "$ref" not in node
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def test_compute_chart_facts_use_real_math():
    d = charts.compute_chart(ChartSpec(type="compound_growth", title="t",
                                       monthly_contribution=200, annual_rate_pct=7, years=30))
    assert d.headline == "$243,994"
    assert "$72,000" in d.facts[0]


def test_compute_chart_rejects_missing_fields():
    with pytest.raises(ValueError):
        charts.compute_chart(ChartSpec(type="debt_payoff", title="t", balance=1000))
    with pytest.raises(ValueError):
        charts.compute_chart(ChartSpec(type="bar_comparison", title="t", labels=["a"], values=[1, 2]))


@pytest.mark.parametrize("w,h", [(108, 192), (192, 108)])
def test_render_frames_and_cards(tmp_path, w, h):
    d = charts.compute_chart(ChartSpec(type="inflation_erosion", title="t",
                                       amount=10_000, inflation_rate_pct=3, years=10))
    frames = charts.render_chart_frames(d, tmp_path / "f", width=w, height=h, n_frames=3)
    assert len(frames) == 3 and all(f.stat().st_size > 0 for f in frames)
    card = charts.render_stat_card(StatSpec(value="$1,000", label="starter fund"),
                                   tmp_path / "s.png", width=w, height=h)
    assert card.exists()
    thumb = charts.render_thumbnail("Test thumb", tmp_path / "t.png", width=128, height=72)
    assert thumb.exists()
