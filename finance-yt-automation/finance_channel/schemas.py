"""Structured-output schemas for every Claude call.

Kept flat and explicit (no numeric constraints, nullable optionals) so they
translate cleanly into JSON Schema for the API's structured outputs.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChartSpec(BaseModel):
    type: Literal["compound_growth", "debt_payoff", "bar_comparison", "inflation_erosion"]
    title: str = Field(description="Short on-screen chart title, <= 40 chars")
    # compound_growth
    initial_amount: Optional[float] = Field(None, description="compound_growth: starting balance")
    monthly_contribution: Optional[float] = Field(None, description="compound_growth: monthly deposit")
    annual_rate_pct: Optional[float] = Field(None, description="compound_growth: assumed annual return, e.g. 7")
    years: Optional[int] = Field(None, description="compound_growth / inflation_erosion: time horizon in years")
    # debt_payoff
    balance: Optional[float] = Field(None, description="debt_payoff: starting debt")
    apr_pct: Optional[float] = Field(None, description="debt_payoff: interest rate APR, e.g. 22")
    monthly_payment: Optional[float] = Field(None, description="debt_payoff: fixed monthly payment")
    # bar_comparison
    labels: Optional[list[str]] = Field(None, description="bar_comparison: 2-5 short labels")
    values: Optional[list[float]] = Field(None, description="bar_comparison: one value per label")
    value_prefix: Optional[str] = Field(None, description="bar_comparison: e.g. '$'")
    value_suffix: Optional[str] = Field(None, description="bar_comparison: e.g. '%'")
    # inflation_erosion
    amount: Optional[float] = Field(None, description="inflation_erosion: cash amount today")
    inflation_rate_pct: Optional[float] = Field(None, description="inflation_erosion: assumed yearly inflation")


class StatSpec(BaseModel):
    value: str = Field(description="The big number or short phrase, e.g. '$1,000' or '3-6 months'")
    label: str = Field(description="One short line explaining the number")


class Scene(BaseModel):
    kind: Literal["narration", "chart", "stat"]
    section: str = Field(description="Chapter label this scene belongs to, 1-4 words")
    narration: str = Field(description="Exact words spoken during this scene")
    footage_query: str = Field(description="narration scenes: 2-4 word stock-footage search; else ''")
    chart: Optional[ChartSpec] = Field(None, description="Required when kind == 'chart'")
    stat: Optional[StatSpec] = Field(None, description="Required when kind == 'stat'")


class VideoPlan(BaseModel):
    title_idea: str
    hook: str = Field(description="The opening line; must earn the next 5 seconds")
    scenes: list[Scene]
    thumbnail_text: str = Field(description="2-4 punchy words for the thumbnail")
    key_claims: list[str] = Field(
        description="Every factual claim or statistic a human should verify before publishing"
    )


class ReviewIssue(BaseModel):
    severity: Literal["critical", "warning", "info"]
    scene_index: int = Field(description="0-based scene index, or -1 for the whole script")
    problem: str
    fix: str


class ScriptReview(BaseModel):
    issues: list[ReviewIssue]
    revised_narrations: list[str] = Field(
        description="Corrected narration for EVERY scene, same count and order as the input"
    )
    fact_check: list[str] = Field(
        description="Claims that still need human verification against a primary source"
    )
    summary: str


class VideoMetadata(BaseModel):
    title: str = Field(description="<= 90 chars, specific and honest, no clickbait lies")
    description: str = Field(description="2-3 short paragraphs; first line is the hook")
    tags: list[str] = Field(description="10-15 relevant lowercase tags")
    hashtags: list[str] = Field(description="3-5 hashtags, include #shorts for vertical")


class TopicIdea(BaseModel):
    pillar: str
    topic: str = Field(description="Specific video topic, <= 90 chars")
    angle: str = Field(description="Why a viewer would click, one sentence")


class IdeaBatch(BaseModel):
    ideas: list[TopicIdea]


def to_strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a pydantic model into a strict JSON Schema for structured outputs.

    Inlines $refs, marks every property required, forbids extra properties, and
    drops keywords the API doesn't need (titles, defaults).
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return walk(dict(defs[name]))
            out = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if out.get("type") == "object" and "properties" in out:
                out["required"] = list(out["properties"].keys())
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(raw)
