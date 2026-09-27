"""Finance visuals rendered locally with matplotlib.

- Animated data charts (compound growth, debt payoff, inflation erosion, bar
  comparison), rendered as a PNG frame sequence that "draws itself" and then
  holds on the final frame.
- Big-number stat cards.
- A fallback gradient background.
- YouTube thumbnails.

All numbers come from finance_math, never from the language model.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from . import finance_math as fm  # noqa: E402
from .schemas import ChartSpec, StatSpec  # noqa: E402
from .utils import compact_money, money  # noqa: E402

DEFAULT_THEME = {
    "background": "#0B1220",
    "accent": "#F5C542",
    "secondary": "#4FC3F7",
    "text": "#F2F4F8",
    "grid": "#243047",
}


@dataclass
class ChartData:
    """Computed chart series plus human-readable facts for the script review."""
    spec: ChartSpec
    facts: list[str]
    headline: str          # big on-screen result
    subline: str           # supporting line under the headline
    footnote: str          # assumption / caveat shown small
    payload: dict[str, Any]


def _need(spec: ChartSpec, *names: str) -> None:
    missing = [n for n in names if getattr(spec, n) in (None, [], "")]
    if missing:
        raise ValueError(f"{spec.type} chart is missing: {', '.join(missing)}")


def compute_chart(spec: ChartSpec, symbol: str = "$") -> ChartData:
    """Validate a chart spec and compute everything it will display."""
    if spec.type == "compound_growth":
        _need(spec, "annual_rate_pct", "years")
        if not (spec.monthly_contribution or spec.initial_amount):
            raise ValueError("compound_growth needs monthly_contribution or initial_amount")
        g = fm.compound_growth(
            initial=spec.initial_amount or 0.0, monthly=spec.monthly_contribution or 0.0,
            annual_rate_pct=spec.annual_rate_pct, years=int(spec.years),
        )
        parts = []
        if spec.initial_amount:
            parts.append(f"{money(spec.initial_amount, symbol)} to start")
        if spec.monthly_contribution:
            parts.append(f"{money(spec.monthly_contribution, symbol)}/month")
        scenario = " + ".join(parts) + f" at {spec.annual_rate_pct:g}% for {spec.years} years"
        facts = [
            f"compound_growth: {scenario} -> final balance {money(g.final_balance, symbol)}; "
            f"total contributed {money(g.total_contributed, symbol)}; "
            f"growth from returns {money(g.total_growth, symbol)} "
            "(monthly compounding, contributions at month end)",
        ]
        return ChartData(
            spec=spec, facts=facts,
            headline=money(g.final_balance, symbol),
            subline=f"You put in {compact_money(g.total_contributed, symbol)} · "
                    f"growth {compact_money(g.total_growth, symbol)}",
            footnote=f"Assumes {spec.annual_rate_pct:g}% average annual return, monthly "
                     "compounding. Illustrative only; returns are not guaranteed.",
            payload={"x": g.years, "total": g.balance, "contributed": g.contributed},
        )

    if spec.type == "debt_payoff":
        _need(spec, "balance", "apr_pct", "monthly_payment")
        p = fm.debt_payoff(balance=spec.balance, apr_pct=spec.apr_pct,
                           monthly_payment=spec.monthly_payment)
        scenario = (f"{money(spec.balance, symbol)} at {spec.apr_pct:g}% APR paying "
                    f"{money(spec.monthly_payment, symbol)}/month")
        if not p.paid_off:
            facts = [f"debt_payoff: {scenario} -> the payment does not cover the interest "
                     "(or takes over 50 years); the balance is never paid off"]
            headline, subline = "Never paid off", "The payment doesn't cover the interest"
        else:
            facts = [f"debt_payoff: {scenario} -> paid off in {p.months} months "
                     f"({fm.years_months(p.months)}); total interest {money(p.total_interest, symbol)}; "
                     f"total paid {money(p.total_paid, symbol)}"]
            headline = fm.years_months(p.months)
            subline = f"Interest paid: {money(p.total_interest, symbol)}"
        return ChartData(
            spec=spec, facts=facts, headline=headline, subline=subline,
            footnote=f"{spec.apr_pct:g}% APR, fixed {money(spec.monthly_payment, symbol)} "
                     "monthly payment, no new charges. Illustrative only.",
            payload={"months": list(range(len(p.balance_by_month))),
                     "balance": p.balance_by_month},
        )

    if spec.type == "inflation_erosion":
        _need(spec, "amount", "inflation_rate_pct", "years")
        r = fm.inflation_erosion(amount=spec.amount, inflation_rate_pct=spec.inflation_rate_pct,
                                 years=int(spec.years))
        facts = [f"inflation_erosion: {money(spec.amount, symbol)} in cash at "
                 f"{spec.inflation_rate_pct:g}% inflation for {spec.years} years -> "
                 f"buys what {money(r.final_value, symbol)} buys today "
                 f"({r.percent_lost:.0f}% of purchasing power lost)"]
        return ChartData(
            spec=spec, facts=facts,
            headline=money(r.final_value, symbol),
            subline=f"of buying power left · -{r.percent_lost:.0f}%",
            footnote=f"Assumes {spec.inflation_rate_pct:g}% inflation every year. Illustrative only.",
            payload={"x": r.years, "value": r.purchasing_power},
        )

    if spec.type == "bar_comparison":
        _need(spec, "labels", "values")
        if len(spec.labels) != len(spec.values):
            raise ValueError("bar_comparison needs one value per label")
        if not 2 <= len(spec.labels) <= 5:
            raise ValueError("bar_comparison needs 2-5 bars")
        pre, suf = spec.value_prefix or "", spec.value_suffix or ""
        pairs = [f"{lab}: {pre}{val:,.2f}".rstrip("0").rstrip(".") + suf
                 for lab, val in zip(spec.labels, spec.values)]
        top = int(np.argmax(spec.values))
        return ChartData(
            spec=spec, facts=[f"bar_comparison '{spec.title}': " + "; ".join(pairs)],
            headline="", subline="", footnote="",
            payload={"labels": spec.labels, "values": spec.values, "prefix": pre,
                     "suffix": suf, "top": top},
        )

    raise ValueError(f"Unknown chart type: {spec.type}")


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _theme(theme: dict | None) -> dict:
    return {**DEFAULT_THEME, **(theme or {})}


def _figure(w: int, h: int, t: dict):
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    fig.patch.set_facecolor(t["background"])
    return fig


def _scale(w: int, h: int) -> float:
    return min(w, h) / 1080


def _layout(w: int, h: int) -> dict:
    """Axes rect and text anchors, leaving the lower band free for captions."""
    if h > w:  # portrait
        return {"title": (0.5, 0.86, "center"), "axes": [0.16, 0.48, 0.76, 0.3],
                "headline": (0.5, 0.39, "center"), "subline": (0.5, 0.355, "center"),
                "footnote": (0.5, 0.955, "center"), "wrap": 30, "panel": 0.9}
    return {"title": (0.06, 0.9, "left"), "axes": [0.07, 0.34, 0.58, 0.48],
            "headline": (0.83, 0.62, "center"), "subline": (0.83, 0.53, "center"),
            "footnote": (0.06, 0.965, "left"), "wrap": 110, "panel": 0.3}


def _style_axes(ax, t: dict, s: float) -> None:
    ax.set_facecolor(t["background"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t["grid"])
    ax.tick_params(colors=t["text"], labelsize=18 * s, length=0, pad=8 * s)
    ax.grid(axis="y", color=t["grid"], linewidth=1.2 * s)
    ax.set_axisbelow(True)


def _ease(p: float) -> float:
    return 1 - (1 - p) ** 3


def _fit(text: str, max_pt: float, width_px: float) -> float:
    """Largest font size (pt, <= max_pt) at which bold text fits width_px at 100 dpi."""
    # Bold DejaVu averages ~0.62em per glyph; 1pt = 100/72 px at 100 dpi.
    per_char_px = 0.62 * 100 / 72
    return min(max_pt, width_px / (per_char_px * max(len(text), 1)))


def _texts(fig, data: ChartData, lay: dict, t: dict, s: float, alpha: float) -> None:
    x, y, ha = lay["title"]
    fig.text(x, y, data.spec.title, color=t["text"], fontsize=44 * s, fontweight="bold",
             ha=ha, va="center")
    if data.headline and alpha > 0:
        x, y, ha = lay["headline"]
        width_px = fig.get_figwidth() * 100 * lay["panel"]
        fig.text(x, y, data.headline, color=t["accent"],
                 fontsize=_fit(data.headline, 64 * s, width_px),
                 fontweight="bold", ha=ha, va="center", alpha=alpha)
        x, y, ha = lay["subline"]
        fig.text(x, y, "\n".join(textwrap.wrap(data.subline, 28)), color=t["text"],
                 fontsize=26 * s, ha=ha, va="top", alpha=alpha)
    if data.footnote:
        x, y, ha = lay["footnote"]
        fig.text(x, y, "\n".join(textwrap.wrap(data.footnote, lay["wrap"] + 20)),
                 color=t["text"], alpha=0.6, fontsize=15 * s, ha=ha, va="top")


def render_chart_frames(
    data: ChartData, out_dir: Path, *, width: int, height: int,
    theme: dict | None = None, symbol: str = "$", n_frames: int = 30,
) -> list[Path]:
    """Render the chart as an n_frames PNG sequence that animates in."""
    t = _theme(theme)
    s = _scale(width, height)
    lay = _layout(width, height)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    money_fmt = FuncFormatter(lambda v, _: compact_money(v, symbol))

    for i in range(n_frames):
        p = _ease(i / max(1, n_frames - 1))
        # Headline fades in over the last 30% of the animation.
        alpha = max(0.0, min(1.0, (p - 0.7) / 0.3)) if i < n_frames - 1 else 1.0
        fig = _figure(width, height, t)
        ax = fig.add_axes(lay["axes"])
        _style_axes(ax, t, s)
        pl = data.payload
        kind = data.spec.type

        if kind == "compound_growth":
            x = np.array(pl["x"], dtype=float)
            total = np.array(pl["total"])
            contrib = np.array(pl["contributed"])
            k = max(2, int(round(1 + p * (len(x) - 1))))
            ax.fill_between(x[:k], 0, contrib[:k], color=t["secondary"], alpha=0.85,
                            label="Money you put in", linewidth=0)
            ax.fill_between(x[:k], contrib[:k], total[:k], color=t["accent"], alpha=0.9,
                            label="Growth", linewidth=0)
            ax.set_xlim(0, x[-1])
            ax.set_ylim(0, total.max() * 1.08)
            ax.yaxis.set_major_formatter(money_fmt)
            ax.set_xlabel("Years", color=t["text"], fontsize=18 * s)
            leg = ax.legend(loc="upper left", frameon=False, fontsize=18 * s)
            for txt in leg.get_texts():
                txt.set_color(t["text"])

        elif kind == "debt_payoff":
            m = np.array(pl["months"], dtype=float) / 12
            bal = np.array(pl["balance"])
            k = max(2, int(round(1 + p * (len(m) - 1))))
            ax.plot(m[:k], bal[:k], color=t["accent"], linewidth=5 * s)
            ax.fill_between(m[:k], 0, bal[:k], color=t["accent"], alpha=0.18, linewidth=0)
            ax.set_xlim(0, max(m[-1], 0.5))
            ax.set_ylim(0, bal.max() * 1.1)
            ax.yaxis.set_major_formatter(money_fmt)
            ax.set_xlabel("Years", color=t["text"], fontsize=18 * s)

        elif kind == "inflation_erosion":
            x = np.array(pl["x"], dtype=float)
            v = np.array(pl["value"])
            k = max(2, int(round(1 + p * (len(x) - 1))))
            ax.axhline(v[0], color=t["secondary"], linewidth=2 * s, linestyle="--", alpha=0.7)
            ax.plot(x[:k], v[:k], color=t["accent"], linewidth=5 * s)
            ax.fill_between(x[:k], v[:k], v[0], color="#E57373", alpha=0.25, linewidth=0)
            ax.set_xlim(0, x[-1])
            ax.set_ylim(0, v[0] * 1.1)
            ax.yaxis.set_major_formatter(money_fmt)
            ax.set_xlabel("Years", color=t["text"], fontsize=18 * s)

        elif kind == "bar_comparison":
            labels, vals = pl["labels"], np.array(pl["values"], dtype=float)
            colors = [t["accent"] if j == pl["top"] else t["secondary"] for j in range(len(vals))]
            bars = ax.bar(labels, vals * p, color=colors, width=0.6)
            ax.set_ylim(0, max(vals.max(), 1e-9) * 1.2)
            ax.yaxis.set_visible(False)
            ax.spines["left"].set_visible(False)
            ax.tick_params(axis="x", labelsize=20 * s)
            for bar, val in zip(bars, vals):
                label = f"{pl['prefix']}{val * p:,.0f}{pl['suffix']}" if abs(val) >= 100 \
                    else f"{pl['prefix']}{val * p:,.1f}{pl['suffix']}"
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), label,
                        ha="center", va="bottom", color=t["text"], fontsize=24 * s,
                        fontweight="bold")

        _texts(fig, data, lay, t, s, alpha)
        path = out_dir / f"f_{i:03d}.png"
        fig.savefig(path, facecolor=t["background"])
        plt.close(fig)
        frames.append(path)
    return frames


def render_stat_card(stat: StatSpec, out_path: Path, *, width: int, height: int,
                     theme: dict | None = None) -> Path:
    t = _theme(theme)
    s = _scale(width, height)
    portrait = height > width
    fig = _figure(width, height, t)
    y = 0.6 if portrait else 0.58
    value = stat.value
    size = 150 * s if len(value) <= 8 else max(70 * s, 150 * s * 8 / len(value))
    fig.text(0.5, y, value, color=t["accent"], fontsize=size, fontweight="bold",
             ha="center", va="center")
    fig.add_artist(plt.Line2D([0.35, 0.65], [y - 0.075, y - 0.075], color=t["accent"],
                              linewidth=4 * s, alpha=0.7, transform=fig.transFigure))
    label = "\n".join(textwrap.wrap(stat.label, 26 if portrait else 44))
    fig.text(0.5, y - 0.11, label, color=t["text"], fontsize=40 * s, ha="center", va="top")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=t["background"])
    plt.close(fig)
    return out_path


def render_gradient(out_path: Path, *, width: int, height: int, theme: dict | None = None) -> Path:
    """Subtle vertical gradient used when no stock footage is available."""
    t = _theme(theme)
    fig = _figure(width, height, t)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    base = np.array(matplotlib.colors.to_rgb(t["background"]))
    top = np.clip(base + 0.08, 0, 1)
    grad = np.linspace(0, 1, 256)[:, None, None]
    img = top * (1 - grad) + base * grad
    ax.imshow(np.repeat(img, 2, axis=1), aspect="auto", extent=[0, 1, 0, 1])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=t["background"])
    plt.close(fig)
    return out_path


def render_thumbnail(text: str, out_path: Path, *, theme: dict | None = None,
                     width: int = 1280, height: int = 720) -> Path:
    """Bold 16:9 thumbnail: big words on the left, a rising line on the right."""
    t = _theme(theme)
    s = _scale(width, height)
    fig = _figure(width, height, t)
    bg = fig.add_axes([0, 0, 1, 1])
    bg.axis("off")
    base = np.array(matplotlib.colors.to_rgb(t["background"]))
    grad = np.linspace(0, 1, 256)[None, :, None]
    img = np.clip(base + 0.10, 0, 1) * (1 - grad) + base * grad
    bg.imshow(np.repeat(img, 2, axis=0), aspect="auto", extent=[0, 1, 0, 1])

    # Decorative rising line.
    ax = fig.add_axes([0.58, 0.15, 0.38, 0.6])
    ax.axis("off")
    xs = np.linspace(0, 1, 60)
    ys = xs ** 2.2 + 0.04 * np.sin(xs * 18)
    ax.plot(xs, ys, color=t["accent"], linewidth=10 * s, solid_capstyle="round")
    ax.fill_between(xs, 0, ys, color=t["accent"], alpha=0.15)

    words = text.upper().strip()
    lines = textwrap.wrap(words, 12) or [words]
    longest = max(len(l) for l in lines)
    size = min(150, 1150 / max(longest, 1)) * s * (0.9 if len(lines) > 2 else 1)
    fig.text(0.05, 0.5, "\n".join(lines[:3]), color=t["text"], fontsize=size,
             fontweight="bold", ha="left", va="center", linespacing=1.05)
    fig.add_artist(plt.Rectangle((0.05, 0.12), 0.18, 0.02, color=t["accent"],
                                 transform=fig.transFigure))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=t["background"])
    plt.close(fig)
    return out_path
