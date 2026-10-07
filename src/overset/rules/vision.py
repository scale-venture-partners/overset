"""Rules a decision model judges: what a deck looks like, not what it measures.

Everything a renderer can measure is a render rule. These are the questions
with no measurement -- is this slide cluttered, does the eye land on the
point, do two slides in a row look the same -- put as yes/no questions to a
multimodal decision model looking at the rendered slides.

A separate reviewer matters even though the author of the deck looked
at it too: the builder grades its own work, with sunk cost and a crowded
context. This one sees only the pictures and a question.

Each slide is one request (OVS401-404 together, OVS406 with the contact sheet
as a reference for the deck), and each consecutive pair of slides another
(OVS405). The model returns a probability per question, reported as the
finding's confidence; anything under `vision_threshold` is dropped. Opt-in
(`--vision`), since it is the one part of overset that is neither offline nor
deterministic. Needs `pip install overset[vision]` and a provider key.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from overset import decisions
from overset.rules.base import finding, rule

CODES = {
    "OVS401": ("cluttered-slide", "Too many elements compete; no single focal point"),
    "OVS402": ("weak-hierarchy", "The eye does not land on the slide's main point first"),
    "OVS403": ("misaligned", "Elements sit visibly off a shared edge or grid"),
    "OVS404": ("illegible-over-image", "Text set over a busy part of an image"),
    "OVS405": ("monotonous-sequence", "Consecutive slides look interchangeable"),
    "OVS406": ("inconsistent-style", "A slide that does not look like it belongs to this deck"),
}

# Phrased so a high probability means the problem is present.
QUESTIONS = {
    "OVS401": "Is this slide cluttered: do so many elements compete that it has no single focal point?",
    "OVS402": "Does this slide have a weak hierarchy: does the eye fail to land on its main point first?",
    "OVS403": "Are elements on this slide visibly misaligned, sitting off a shared edge or grid?",
    "OVS404": "Is any text on this slide set over a busy part of an image, so that it is hard to read?",
    "OVS405": "Are these two slides interchangeable: the same layout and visual structure, differing only in content?",
    "OVS406": "Does the first image, a single slide, look like it does not belong to the deck shown in the second?",
}
SLIDE_CODES = ("OVS401", "OVS402", "OVS403", "OVS404")

SCOPE = (
    "Judge only how the slides look. Do not judge text overflow, font sizes, colours or contrast, which are "
    "measured elsewhere, and do not judge the writing."
)
MAX_WORKERS = 8


def preamble(brief: str = "") -> str:
    return SCOPE + (f"\nHouse style for this deck:\n{brief}" if brief else "")


def _requests(ctx):
    """Every request the active rules need: (slide the findings land on, prompt, questions)."""
    wanted = set(ctx.settings.active_codes())
    pages, sheet = ctx.render.pages, ctx.render.contact_sheet
    intro = preamble(ctx.settings.vision_brief)

    def ask(codes):
        return {c: QUESTIONS[c] for c in codes if c in wanted}

    for page in pages:
        if questions := ask(SLIDE_CODES):
            text = f"{intro}\nSlide {page.number} of {len(pages)}:"
            yield page.number, decisions.Prompt(text, [page.image]), questions
        if sheet and (questions := ask(["OVS406"])):
            text = f"{intro}\nThe first image is slide {page.number}; the second is the whole deck:"
            yield page.number, decisions.Prompt(text, [page.image, sheet]), questions
    for before, after in zip(pages, pages[1:], strict=False):
        if questions := ask(["OVS405"]):
            text = f"{intro}\nSlide {before.number}, then slide {after.number}:"
            yield after.number, decisions.Prompt(text, [before.image, after.image]), questions


def review(ctx) -> dict[str, list[tuple[int, float]]]:
    """Ask every question of every slide once, whichever rules are active: {code: [(slide, probability)]}."""
    if ctx.cache.get("vision") is None:
        backend = ctx.vision_backend
        requests = list(_requests(ctx))
        with ThreadPoolExecutor(MAX_WORKERS) as pool:
            outcomes = list(pool.map(lambda r: backend.predicates(r[1], r[2]), requests))
        found: dict[str, list[tuple[int, float]]] = {code: [] for code in CODES}
        refused = 0
        for (slide, _, _), answers in zip(requests, outcomes, strict=True):
            refused += len(answers.refused)
            for code, p in answers.probabilities.items():
                found[code].append((slide, p))
        if refused:
            ctx.notes.append(f"the decision model refused {refused} vision question(s); those were not judged")
        ctx.cache["vision"] = found
    return ctx.cache["vision"]


def _register(code, name, summary):
    @rule(code, name, summary, "vision", default=False)
    def check(ctx):
        threshold = ctx.settings.vision_threshold
        return [finding(ctx, code, summary, slide, confidence=p) for slide, p in review(ctx)[code] if p >= threshold]

    return check


for _code, (_name, _summary) in CODES.items():
    _register(_code, _name, _summary)
