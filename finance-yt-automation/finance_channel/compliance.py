"""Rule-based compliance scanner for finance scripts.

This is the first, deterministic line of defense. It catches the phrases that
most often get finance channels into trouble (promissory language, specific
buy/sell calls, get-rich-quick framing). A second Claude review pass handles
the nuance; this scanner runs before AND after that review so a problem can't
slip through if the model misses it.

This is not legal advice. It reduces risk; it does not make content compliant
in every jurisdiction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    severity: str        # "critical" | "warning"
    rule: str
    excerpt: str
    advice: str


# (severity, rule id, regex, advice)
_RULES: list[tuple[str, str, str, str]] = [
    ("critical", "guaranteed-returns",
     r"\bguarantee(?:d|s)?\b[^.?!]{0,40}\b(?:return|returns|profit|profits|income|gains?|money|results?)\b"
     r"|\b(?:return|returns|profit|profits|income|gains?)\b[^.?!]{0,30}\bguarantee(?:d|s)?\b",
     "Never promise returns. Say 'historically' or 'assuming' and note returns aren't guaranteed."),
    ("critical", "risk-free",
     r"\b(?:risk[- ]free|zero risk|no risk|can(?:'|no)?t lose|cannot lose|never lose|sure thing|safe bet)\b",
     "Every investment carries risk. Remove absolute safety claims."),
    ("critical", "get-rich-quick",
     r"\b(?:get rich quick|overnight millionaire|double your money (?:fast|quickly|overnight|in \w+ (?:days|weeks))"
     r"|quit your job (?:tomorrow|next week)|easy money|free money)\b",
     "Avoid get-rich-quick framing; it's misleading and a YouTube spam signal."),
    ("critical", "personal-advice",
     r"\b(?:this is|i'm giving you|take this as)\s+(?:financial|investment|tax|legal) advice\b",
     "The channel provides general education, not personalised advice."),
    ("warning", "price-prediction",
     r"\b(?:will|is going to|gonna)\s+(?:definitely\s+|certainly\s+)?(?:skyrocket|moon|explode|10x|100x|double|crash|collapse)\b",
     "Don't predict prices. Frame as scenarios or historical examples."),
    ("warning", "absolute-language",
     r"\b(?:always goes up|never goes down|always wins|can't go wrong|foolproof|100% (?:safe|certain|sure))\b",
     "Replace absolutes with 'historically' / 'over long periods' plus a caveat."),
    ("warning", "urgency-pressure",
     r"\b(?:act now|before it's too late|last chance|don't miss out|you're losing money every day you wait)\b",
     "Pressure tactics read as manipulative; state the trade-off calmly instead."),
    ("warning", "crypto-hype",
     r"\b(?:next bitcoin|to the moon|hodl|lambo|1000x)\b",
     "Hype slang undermines trust on an education channel."),
    ("warning", "dated-figure",
     r"\b(?:20[2-3]\d)\s+(?:contribution limit|tax bracket|standard deduction|limit)s?\b"
     r"|\bcontribution limit (?:is|of)\s+\$[\d,]+",
     "Year-specific limits change. Verify against an official source before publishing."),
]

_COMPILED = [(sev, rule, re.compile(rx, re.IGNORECASE), adv) for sev, rule, rx, adv in _RULES]

# Ticker detection must be case-sensitive (tickers are upper-case), so this
# rule is compiled separately with the verbs' case variants spelled out.
_BUY_SELL = (
    "critical", "specific-buy-sell-call",
    re.compile(
        r"\b(?:[Yy]ou should|[Yy]ou need to|[Gg]o|I'd|I would)\s+(?:buy|sell|short|dump|load up on)\s+"
        r"(?:shares of\s+)?(?:\$?[A-Z]{2,5}\b|[A-Z][a-z]+ stock)"
        r"|\b(?:[Bb]uy|[Ss]ell|[Ss]hort)\s+\$[A-Z]{1,5}\b"
    ),
    "No specific security recommendations. Explain the concept instead of telling viewers what to buy.",
)


# Rules whose phrases are fine when negated ("returns are NOT guaranteed",
# "no investment is risk-free").
_NEGATABLE = {"guaranteed-returns", "risk-free", "absolute-language"}
_NEGATION = re.compile(
    r"\b(?:not|no|never|nothing|none|nor|without|isn't|aren't|wasn't|won't|can't|cannot|doesn't|don't)\b"
    r"|n't\b",
    re.IGNORECASE,
)


def _negated(text: str, start: int, end: int, rule: str) -> bool:
    """True if the match is negated within its sentence.

    Looks at up to 25 chars before the match. For guaranteed-returns it also
    looks inside the match ("returns are not guaranteed"). Other rules skip the
    match itself, because phrases like "no risk" or "never goes down" contain a
    negation word but are still absolute claims.
    """
    before = text[max(0, start - 25):start]
    before = re.split(r"[.!?]", before)[-1]
    window = before + (text[start:end] if rule == "guaranteed-returns" else "")
    return bool(_NEGATION.search(window))


def scan(text: str) -> list[Finding]:
    """Return compliance findings for a block of narration."""
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for sev, rule, rx, advice in [*_COMPILED, _BUY_SELL]:
        for m in rx.finditer(text):
            if rule in _NEGATABLE and _negated(text, m.start(), m.end(), rule):
                continue
            excerpt = _context(text, m.start(), m.end())
            key = (rule, m.group(0).lower())
            if key in seen:
                continue
            seen.add(key)
            findings.append(Finding(severity=sev, rule=rule, excerpt=excerpt, advice=advice))
    return findings


def has_critical(findings: list[Finding]) -> bool:
    return any(f.severity == "critical" for f in findings)


def _context(text: str, start: int, end: int, pad: int = 30) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    snippet = text[s:e].replace("\n", " ").strip()
    return ("…" if s > 0 else "") + snippet + ("…" if e < len(text) else "")
