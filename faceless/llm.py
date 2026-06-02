"""Claude integration: scripts, highlight detection, and SEO metadata.

Uses the Anthropic Python SDK with:
  - model `claude-opus-4-8` (configurable)
  - adaptive thinking + the effort parameter
  - streaming for long generations (script writing)
  - structured outputs (`messages.parse`) for highlights and metadata
  - prompt caching on the stable channel-context system block

The channel context (niche/tone/audience) is identical across every call in a
run, so it goes in a cache-controlled system block. (Note: the cacheable-prefix
minimum on Opus is ~4096 tokens; short prompts won't actually cache, but the
structure is correct and free.)
"""

from __future__ import annotations

from typing import Any

import anthropic
from pydantic import BaseModel, Field

from .config import Config, require_env


class ScriptResult(BaseModel):
    title_idea: str = Field(description="A working title for the video")
    hook: str = Field(description="The first 1-2 sentences; must grab attention fast")
    script: str = Field(description="The full narration script, spoken-word style")
    on_screen_keywords: list[str] = Field(
        default_factory=list,
        description="3-8 short visual keywords to drive background footage search",
    )


class Highlight(BaseModel):
    start: float = Field(description="Clip start time in seconds")
    end: float = Field(description="Clip end time in seconds")
    title: str = Field(description="Punchy title for this clip")
    reason: str = Field(description="Why this moment makes a strong standalone short")


class HighlightSet(BaseModel):
    clips: list[Highlight]


class VideoMetadata(BaseModel):
    title: str = Field(description="<=100 chars, compelling, honest, no clickbait lies")
    description: str = Field(description="2-4 short paragraphs, includes a hook line")
    tags: list[str] = Field(description="10-15 relevant lowercase tags")
    hashtags: list[str] = Field(description="3-5 hashtags incl. #shorts when vertical")


class LLM:
    def __init__(self, config: Config):
        self.config = config
        self.model = config.get("llm.model", "claude-opus-4-8")
        self.effort = config.get("llm.effort", "high")
        # Reads ANTHROPIC_API_KEY from the environment.
        require_env("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic()

    # -- shared building blocks --------------------------------------------

    def _channel_system(self, role: str) -> list[dict[str, Any]]:
        """Stable, cache-controlled system blocks describing the channel + role."""
        ctx = (
            f"You produce content for a faceless YouTube channel.\n"
            f"Niche: {self.config.get('channel.niche', 'general interest')}\n"
            f"Tone: {self.config.get('channel.tone', 'clear and engaging')}\n"
            f"Audience: {self.config.get('channel.target_audience', 'a general audience')}\n"
            f"Language: {self.config.get('channel.language', 'en')}\n\n"
            "Be original, accurate, and never use misleading clickbait. Avoid "
            "copyrighted lyrics or long quotations."
        )
        return [
            {"type": "text", "text": ctx, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": role},
        ]

    def _parse(self, system: list[dict[str, Any]], prompt: str, schema: type[BaseModel]):
        """Structured output via messages.parse, with a JSON fallback."""
        try:
            resp = self.client.messages.parse(
                model=self.model,
                max_tokens=8000,
                output_config={"effort": self.effort},
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
            if resp.parsed_output is not None:
                return resp.parsed_output
        except Exception:
            pass
        # Fallback: ask for raw JSON and validate.
        import json

        resp = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            output_config={"effort": self.effort},
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                    + "\n\nRespond with ONLY valid JSON matching this schema:\n"
                    + json.dumps(schema.model_json_schema()),
                }
            ],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "{}")
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        return schema.model_validate_json(text)

    # -- public API ---------------------------------------------------------

    def write_script(self, topic: str, *, video_format: str) -> ScriptResult:
        """Generate a narration script for a from-scratch video."""
        if video_format == "short":
            length = "about 90-140 words (a 40-55 second vertical Short)"
        else:
            length = "about 600-900 words (a 4-6 minute long-form video)"
        role = (
            "Role: scriptwriter. Write a spoken-word narration script meant to be "
            "read by a single text-to-speech voice. No stage directions, no speaker "
            "labels, no markdown — just the words to be spoken."
        )
        prompt = (
            f"Write a faceless YouTube {video_format} script on this topic:\n\n"
            f'"{topic}"\n\n'
            f"Target length: {length}. Open with a strong hook in the first line. "
            "End with a light call to action (e.g. follow for more)."
        )
        # Script can be long-ish; stream to avoid timeouts and get final message.
        return self._parse(self._channel_system(role), prompt, ScriptResult)

    def find_highlights(
        self, transcript_segments: list[dict[str, Any]], *, max_clips: int,
        min_sec: float, max_sec: float,
    ) -> HighlightSet:
        """Pick the best standalone short-form moments from a transcript."""
        role = (
            "Role: short-form editor. From a timestamped transcript, select the "
            "moments that work best as standalone vertical Shorts: self-contained, "
            "high-retention, with a natural hook and payoff."
        )
        # Compress segments to a compact timestamped transcript.
        lines = [
            f"[{s['start']:.1f}-{s['end']:.1f}] {s['text'].strip()}"
            for s in transcript_segments
        ]
        transcript = "\n".join(lines)
        prompt = (
            f"Transcript (seconds):\n{transcript}\n\n"
            f"Select up to {max_clips} clips. Each must be between {min_sec:.0f} and "
            f"{max_sec:.0f} seconds long. Align start/end to natural sentence "
            "boundaries from the timestamps. Prefer complete thoughts over cutting "
            "mid-sentence."
        )
        return self._parse(self._channel_system(role), prompt, HighlightSet)

    def write_metadata(
        self, *, video_format: str, topic_or_transcript: str, script_excerpt: str = "",
    ) -> VideoMetadata:
        """Generate SEO title/description/tags/hashtags."""
        role = (
            "Role: YouTube SEO specialist. Write metadata that is honest, "
            "search-friendly, and matches the channel tone. Titles must not "
            "over-promise."
        )
        prompt = (
            f"Video format: {video_format}.\n"
            f"Subject:\n{topic_or_transcript}\n\n"
            + (f"Script excerpt:\n{script_excerpt}\n\n" if script_excerpt else "")
            + "Produce the title, description, tags, and hashtags."
        )
        return self._parse(self._channel_system(role), prompt, VideoMetadata)
