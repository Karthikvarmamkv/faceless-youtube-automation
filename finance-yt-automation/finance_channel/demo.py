"""A built-in sample plan so the renderer can be tested with no API keys."""

from __future__ import annotations

from .schemas import ChartSpec, Scene, StatSpec, VideoPlan


def demo_plan() -> VideoPlan:
    return VideoPlan(
        title_idea="What $200 a month becomes in 30 years",
        hook="Two hundred dollars a month doesn't sound like much.",
        thumbnail_text="$200/month = ?",
        key_claims=["Long-run stock market average return assumption of 7% per year"],
        scenes=[
            Scene(kind="narration", section="Intro",
                  narration="Two hundred dollars a month doesn't sound like much. "
                            "But give it thirty years and something surprising happens.",
                  footage_query="coins stacking"),
            Scene(kind="chart", section="The math",
                  narration="Assuming a seven percent average annual return, you'd put in "
                            "seventy two thousand dollars, and end up with about two hundred "
                            "forty four thousand.",
                  footage_query="",
                  chart=ChartSpec(type="compound_growth", title="$200/month for 30 years",
                                  monthly_contribution=200, annual_rate_pct=7, years=30)),
            Scene(kind="stat", section="The math",
                  narration="Most of that money is growth, not deposits.",
                  footage_query="",
                  stat=StatSpec(value="70%", label="of the final balance came from growth")),
            Scene(kind="narration", section="Takeaway",
                  narration="Time does the heavy lifting. Starting early matters more than "
                            "starting big. Follow for more simple money math.",
                  footage_query="sunrise city skyline"),
        ],
    )
