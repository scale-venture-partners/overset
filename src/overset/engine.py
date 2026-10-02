"""Load, render if any active rule needs it, run the rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from overset import deck as deck_mod
from overset import package as package_mod
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


def _package_findings(path) -> list[Finding]:
    out = []
    for problem in package_mod.check(path):
        hint = package_mod.fix_hint(problem)
        out.append(Finding("OVS000", problem + (f" -- {hint}" if hint else ""), None, REGISTRY["OVS000"].severity))
    return out


def lint(path: str | Path, settings: Settings, workdir: Path | None = None, vision_model=None) -> Result:
    codes = settings.active_codes()
    # The package first: a deck PowerPoint would have to repair is a finding, and one
    # python-pptx can't load is reported as that rather than as overset failing.
    package = _package_findings(path) if "OVS000" in codes else []
    try:
        deck = deck_mod.load(path)
    except Exception as e:
        if not package:
            raise
        result = Result(Path(path), package, 0, rendered=False)
        result.notes.append(f"the deck could not be loaded ({type(e).__name__}: {e}), so no other rule ran")
        return result
    ctx = Context(deck, settings, vision_model=vision_model)
    result = Result(Path(path), list(package), len(deck.slides), rendered=False)
    codes = [c for c in codes if c != "OVS000"]

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
