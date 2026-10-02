"""Load, render if any active rule needs it, run the rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from overset import deck as deck_mod
from overset import render as render_mod
from overset.rules.base import REGISTRY, Finding
from overset.settings import Settings


@dataclass
class Context:
    deck: deck_mod.Deck
    settings: Settings
    render: render_mod.Render | None = None
    vision_model: object = None  # a pydantic-ai model to use instead of settings.vision_model
    cache: dict = field(default_factory=dict)


@dataclass
class Result:
    path: Path
    findings: list[Finding]
    slides: int
    rendered: bool
    skipped: list[str] = field(default_factory=list)  # codes that could not run, and why
    notes: list[str] = field(default_factory=list)

    def sorted(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: (f.slide or 0, f.code))


def lint(path: str | Path, settings: Settings, workdir: Path | None = None, vision_model=None) -> Result:
    deck = deck_mod.load(path)
    codes = settings.active_codes()
    ctx = Context(deck, settings, vision_model=vision_model)
    result = Result(Path(path), [], len(deck.slides), rendered=False)

    needs_render = [c for c in codes if REGISTRY[c].kind in ("render", "vision")]
    if needs_render:
        try:
            wants_sheet = any(REGISTRY[c].kind == "vision" for c in codes)
            ctx.render = render_mod.render(deck, workdir, settings.font_dirs, contact_sheet=wants_sheet,
                                           as_powerpoint=settings.render_as == "powerpoint")
            result.rendered = True
            result.notes += ctx.render.notes
        except render_mod.RenderError as e:
            # Structure rules still run; the render rules are reported as skipped, not passed.
            result.skipped = needs_render
            result.notes.append(f"render failed, so {', '.join(needs_render)} did not run: {e}")
            codes = [c for c in codes if c not in needs_render]

    for code in codes:
        result.findings += REGISTRY[code].check(ctx)
    return result
