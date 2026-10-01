"""Rules a vision model judges: what a deck looks like, not what it measures.

Everything a renderer can measure is a render rule. These are the questions
with no measurement -- is this slide cluttered, does the eye land on the
point, do three slides in a row look the same -- asked of a model looking at
the rendered slides and a contact sheet of the whole deck.

A separate reviewer matters even though the author of the deck looked
at it too: the builder grades its own work, with sunk cost and a crowded
context. This one sees only the pictures and a rubric.

One model call answers every vision rule. Each finding carries the model's
confidence, and anything under `vision_threshold` is dropped. Opt-in
(`--vision`), since it is the one part of overset that is neither offline nor
deterministic. Needs `pip install overset[vision]` and a provider key.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

from overset.rules.base import finding, rule

CODES = {
    "OVS401": ("cluttered-slide", "Too many elements compete; no single focal point"),
    "OVS402": ("weak-hierarchy", "The eye does not land on the slide's main point first"),
    "OVS403": ("misaligned", "Elements sit visibly off a shared edge or grid"),
    "OVS404": ("illegible-over-image", "Text set over a busy part of an image"),
    "OVS405": ("monotonous-sequence", "Consecutive slides look interchangeable"),
    "OVS406": ("inconsistent-style", "A slide that does not look like it belongs to this deck"),
}

INSTRUCTIONS = """You review presentation decks for visual quality, as a strict senior designer.
You are shown each slide, then a contact sheet of the whole deck. Report only real, specific problems
from this list, each with the slide number (1-based) it is on and a confidence from 0 to 1:

{rubric}

For OVS405, report the second slide of the pair. Do not report text overflow, font sizes, colours or
contrast -- those are measured elsewhere. Do not comment on the writing. If the deck is fine, return no
issues. A false alarm costs the author a rewrite; only report what you would defend."""


class Issue(BaseModel):
    code: Literal["OVS401", "OVS402", "OVS403", "OVS404", "OVS405", "OVS406"]
    slide: int | None = Field(description="1-based slide number, or null for the whole deck")
    message: str = Field(description="What is wrong, specifically enough to fix")
    confidence: float = Field(ge=0, le=1)


class Review(BaseModel):
    issues: list[Issue]


def instructions(brief: str = "") -> str:
    rubric = "\n".join(f"- {code} {name}: {summary}" for code, (name, summary) in CODES.items())
    text = INSTRUCTIONS.format(rubric=rubric)
    return text + (f"\n\nHouse style for this deck:\n{brief}" if brief else "")


def review(ctx) -> Review:
    """Run the one vision call for this deck, once, whichever rules ask."""
    if ctx.cache.get("vision") is None:
        os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # a linter's output is its findings
        from pydantic_ai import Agent, BinaryContent

        settings = ctx.settings
        agent = Agent(ctx.vision_model or settings.vision_model, output_type=Review,
                      instructions=instructions(settings.vision_brief))
        parts: list = [f"A deck of {len(ctx.render.pages)} slides."]
        if settings.vision_input in ("slides", "both"):
            for page in ctx.render.pages:
                parts += [f"Slide {page.number}:", BinaryContent(page.image.read_bytes(), media_type="image/png")]
        if settings.vision_input in ("sheet", "both") and ctx.render.contact_sheet:
            parts += ["The whole deck:", BinaryContent(ctx.render.contact_sheet.read_bytes(), media_type="image/png")]
        ctx.cache["vision"] = agent.run_sync(parts).output
    return ctx.cache["vision"]


def _register(code, name, summary):
    @rule(code, name, summary, "vision", default=False)
    def check(ctx):
        threshold = ctx.settings.vision_threshold
        return [finding(ctx, code, i.message, i.slide, confidence=i.confidence)
                for i in review(ctx).issues if i.code == code and i.confidence >= threshold]
    return check


for _code, (_name, _summary) in CODES.items():
    _register(_code, _name, _summary)
