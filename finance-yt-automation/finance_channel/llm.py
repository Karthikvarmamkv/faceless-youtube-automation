"""Claude integration: topic ideas, video plans, compliance review, metadata.

Uses the Anthropic Python SDK with:
  - model `claude-opus-5` (configurable in config.yaml)
  - adaptive thinking (on by default) + the `effort` parameter
  - structured outputs (`output_config.format` with a strict JSON schema)
  - prompt caching on the stable channel-context system block
  - server-side refusal fallbacks (`fallbacks: "default"`), so a safety
    classifier decline is retried on Anthropic's recommended fallback model
    instead of failing the run. Disable with `llm.fallbacks: false`.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from .config import Config, require_env
from .schemas import IdeaBatch, ScriptReview, VideoMetadata, VideoPlan, to_strict_json_schema

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

FINANCE_RULES = """\
Content rules for this finance education channel (non-negotiable):
1. General education only. Never tell the viewer what they personally should
   do with their money, and never recommend a specific stock, fund, coin, or
   provider by name as something to buy or sell.
2. Never promise or imply guaranteed returns. When citing long-run market
   returns, say "historically" or "assuming", and note returns are not
   guaranteed and can be negative in any given year.
3. No get-rich-quick framing, price predictions, hype slang, or urgency
   pressure ("act now", "before it's too late").
4. Prefer round, conservative, clearly-labelled assumptions (e.g. "assuming a
   7% average annual return"). Show the assumption on screen.
5. Avoid year-specific figures that change (tax brackets, contribution limits,
   interest-rate levels). If one is essential, list it in key_claims so a
   human verifies it before publishing.
6. Don't invent statistics or studies. If a claim needs a source, it goes in
   key_claims.
7. Be kind about money mistakes. No shaming, no fear-mongering.
"""


class RefusalError(RuntimeError):
    """Raised when the model (and its fallback) decline the request."""


class LLM:
    def __init__(self, config: Config):
        self.config = config
        self.model = config.get("llm.model", "claude-opus-5")
        self.effort = config.get("llm.effort", "high")
        self.use_fallbacks = bool(config.get("llm.fallbacks", True))
        require_env("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic()

    # -- shared building blocks --------------------------------------------

    def _system(self, role: str) -> list[dict[str, Any]]:
        """Stable, cache-controlled channel block + a per-call role block."""
        c = self.config.get
        pillars = "\n".join(f"  - {p}" for p in (c("pillars") or []))
        ctx = (
            "You produce content for a faceless personal-finance YouTube channel.\n"
            f"Channel name: {c('channel.name', 'the channel')}\n"
            f"Niche: {c('channel.niche', 'personal finance')}\n"
            f"Tone: {c('channel.tone', 'calm and clear')}\n"
            f"Audience: {c('channel.target_audience', 'adults learning about money')}\n"
            f"Region for examples: {c('channel.region', 'US')} "
            f"(currency symbol {c('channel.currency_symbol', '$')})\n"
            f"Language: {c('channel.language', 'en')}\n"
            f"Content pillars:\n{pillars}\n\n"
            f"{FINANCE_RULES}"
        )
        return [
            {"type": "text", "text": ctx, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": role},
        ]

    def _structured(self, role: str, prompt: str, schema: type[T], *, max_tokens: int = 16000) -> T:
        """One structured-output call, validated into the pydantic model."""
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=self._system(role),
            messages=[{"role": "user", "content": prompt}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": to_strict_json_schema(schema)},
            },
        )
        if self.use_fallbacks:
            resp = self.client.beta.messages.create(
                betas=[FALLBACK_BETA], fallbacks="default", **kwargs,
            )
        else:
            resp = self.client.messages.create(**kwargs)

        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise RefusalError(
                f"Claude declined this request (category: {category}). "
                "Rephrase the topic and try again."
            )
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Response hit max_tokens before finishing; raise max_tokens.")

        text = next((b.text for b in resp.content if b.type == "text"), "")
        if not text:
            raise RuntimeError("Claude returned no text content.")
        return schema.model_validate(json.loads(text))

    # -- public API ---------------------------------------------------------

    def brainstorm_ideas(self, *, count: int, pillar: str | None, avoid: list[str]) -> IdeaBatch:
        role = (
            "Role: content strategist. Propose specific, searchable video topics "
            "that a beginner would actually type into YouTube. Each topic must be "
            "answerable in one video and teachable with a simple number, chart, "
            "or rule of thumb."
        )
        scope = f'Only use the pillar "{pillar}".' if pillar else "Spread ideas across all pillars."
        avoid_txt = "\n".join(f"- {t}" for t in avoid[:200]) or "(none)"
        prompt = (
            f"Propose {count} new video topics. {scope}\n"
            "Use the exact pillar text from the channel's pillar list.\n\n"
            f"Do NOT repeat or closely paraphrase these existing topics:\n{avoid_txt}"
        )
        return self._structured(role, prompt, IdeaBatch)

    def plan_video(self, topic: str, *, video_format: str, pillar: str = "") -> VideoPlan:
        """Write the script as a sequence of visual scenes."""
        if video_format == "short":
            shape = (
                "a vertical YouTube Short: 110-150 spoken words total, 4-7 scenes, "
                "under 55 seconds. Hook in the first 2 seconds. Include exactly one "
                "chart OR stat scene that carries the key number."
            )
        else:
            shape = (
                "a 5-8 minute long-form video: 800-1200 spoken words total, 12-24 "
                "scenes, grouped into 4-7 sections (the `section` field becomes a "
                "YouTube chapter). Include 2-4 chart or stat scenes."
            )
        role = (
            "Role: scriptwriter and visual planner. You write narration for a single "
            "text-to-speech voice (no stage directions, speaker labels, or markdown) "
            "and decide what is on screen for each chunk of narration.\n\n"
            "Scene kinds:\n"
            "- narration: stock footage behind captions. Give a concrete, filmable "
            "footage_query (e.g. 'person reviewing bills', 'city skyline dusk').\n"
            "- chart: a data chart rendered from your parameters. The program computes "
            "the numbers itself, so pick realistic inputs and fill ONLY the fields for "
            "the chart type. compound_growth needs monthly_contribution and/or "
            "initial_amount, annual_rate_pct, years. debt_payoff needs balance, apr_pct, "
            "monthly_payment. inflation_erosion needs amount, inflation_rate_pct, years. "
            "bar_comparison needs 2-5 labels and matching values.\n"
            "- stat: one big number or phrase with a short label.\n\n"
            "In chart scenes, narrate what the chart shows but you may round the final "
            "figures; they will be corrected against the computed values afterward. "
            "Set footage_query to '' for chart and stat scenes."
        )
        prompt = (
            f'Plan {shape}\n\nTopic: "{topic}"'
            + (f"\nContent pillar: {pillar}" if pillar else "")
            + "\n\nEnd with a one-line, low-pressure call to follow for more. Do not "
            "include a disclaimer line; the program adds one."
        )
        return self._structured(role, prompt, VideoPlan)

    def review_script(
        self, plan: VideoPlan, *, computed_facts: list[str], scanner_findings: list[str],
    ) -> ScriptReview:
        """Second pass: fact-check against computed numbers + compliance edit."""
        role = (
            "Role: compliance editor and fact-checker for a finance education channel. "
            "Make the smallest edits that fix real problems. Keep the voice, pacing, "
            "and length. Numbers spoken in chart scenes MUST match the computed values "
            "given to you (rounding in a natural spoken way is fine, e.g. 'about "
            "$244,000'). Remove or soften anything that breaks the content rules. "
            "Flag anything you cannot verify."
        )
        scenes = [
            {"index": i, "kind": s.kind, "narration": s.narration,
             "chart": s.chart.model_dump(exclude_none=True) if s.chart else None,
             "stat": s.stat.model_dump() if s.stat else None}
            for i, s in enumerate(plan.scenes)
        ]
        prompt = (
            "Review this video script.\n\n"
            f"Scenes (JSON):\n{json.dumps(scenes, indent=2)}\n\n"
            "Computed values for the charts (ground truth):\n"
            + ("\n".join(f"- {f}" for f in computed_facts) or "- (no charts)")
            + "\n\nAutomated compliance scanner flagged:\n"
            + ("\n".join(f"- {f}" for f in scanner_findings) or "- (nothing)")
            + "\n\nWriter's list of claims to verify:\n"
            + ("\n".join(f"- {c}" for c in plan.key_claims) or "- (none)")
            + f"\n\nReturn revised_narrations with exactly {len(plan.scenes)} entries."
        )
        return self._structured(role, prompt, ScriptReview)

    def write_metadata(self, plan: VideoPlan, *, video_format: str, topic: str) -> VideoMetadata:
        role = (
            "Role: YouTube SEO specialist for a finance education channel. Titles are "
            "specific and curiosity-driven but never over-promise, never imply "
            "guaranteed results, and never use ALL CAPS words beyond one. Descriptions "
            "summarise what the viewer will learn. Do not add a disclaimer; the "
            "program appends one."
        )
        script = " ".join(s.narration for s in plan.scenes)
        prompt = (
            f"Video format: {video_format}.\nTopic: {topic}\n"
            f"Working title: {plan.title_idea}\n\nScript:\n{script[:6000]}\n\n"
            "Write the title, description, tags, and hashtags."
        )
        return self._structured(role, prompt, VideoMetadata)
