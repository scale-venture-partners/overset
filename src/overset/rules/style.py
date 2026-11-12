"""Typography and colour rules beyond the brand checks (OVS105-OVS110): how many families and
colours a deck uses, emphasis, underlines, and colours that read badly. Measured from the .pptx."""

from __future__ import annotations

import re

from overset import color as colour
from overset.deck import TITLE_PLACEHOLDERS
from overset.rules.base import clip, finding, rule

_STYLE_WORDS = {
    "thin", "hairline", "extralight", "ultralight", "light", "regular", "book", "normal", "roman", "medium",
    "semibold", "demibold", "bold", "extrabold", "ultrabold", "black", "heavy", "italic", "oblique",
    "condensed", "narrow", "semi", "demi", "extra", "ultra",
}  # fmt: skip
# Symbol and icon fonts set single glyphs, not text: they are not a typeface choice.
_SYMBOL_FONTS = {"symbol", "wingdings", "wingdings 2", "wingdings 3", "webdings", "marlett",
                 "segoe ui symbol", "segoe ui emoji", "apple color emoji", "noto color emoji"}  # fmt: skip


def font_family(face: str) -> str:
    """'Inter SemiBold', 'Inter-Bold' and 'Inter' are one family: weights and styles are not."""
    base, _, style = face.partition("-")
    if style and all(w.lower() in _STYLE_WORDS for w in re.findall(r"[A-Z]?[a-z]+", style) or [style]):
        face = base
    words = face.split()
    while len(words) > 1 and words[-1].lower() in _STYLE_WORDS:
        words.pop()
    return " ".join(words)


@rule(
    "OVS105",
    "too-many-font-families",
    "More typeface families in the deck than a consistent design uses",
    "structure",
    explanation="Counts the families text is actually set in -- stated, inherited from the layout, and the "
    "theme's heading and body fonts -- with weights and styles of one family counted once. Kosslyn et al. "
    "(2012) found fonts mixed arbitrarily in 37% of sampled decks. Symbol fonts are not counted. Unlike "
    "OVS102 it needs no brand font set. Limit: `max-font-families` (default 2).",
)
def too_many_font_families(ctx):
    first: dict[str, int] = {}
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.from_layout:
                continue
            for r in shape.runs:
                if r.face and r.face.lower() not in _SYMBOL_FONTS:
                    first.setdefault(font_family(r.face), slide.number)
    limit = ctx.settings.max_font_families
    if len(first) <= limit:
        return []
    names = ", ".join(f"{f} (slide {n})" for f, n in sorted(first.items(), key=lambda kv: kv[1]))
    return [finding(ctx, "OVS105", f"{len(first)} font families in the deck, over {limit}: {names}", None)]


# A paragraph this short is a heading, label or callout, where bold or capitals mark it out on purpose.
HEADING_WORDS = 10
# Attribution and caption lines are conventionally set in italic (or small bold); they are not body text.
_CITATION = re.compile(
    r"^\s*(?:sources?|notes?|credits?|photo(?:graph)?|image|picture|figure|fig\.?|table|data|adapted from|"
    r"courtesy of|via|references?|\u00a9|\*)\b",
    re.IGNORECASE,
)


_QUOTE_MARKS = "\"'\u201c\u201d\u2018\u2019\u00ab\u00bb\u201e"


def _overused(paragraph) -> tuple[str, ...]:
    """The emphasis a paragraph overuses: none for headings, labels, source and caption lines, and
    italic quotations."""
    if len(paragraph.text.split()) <= HEADING_WORDS or _CITATION.match(paragraph.text):
        return ()
    quoted = paragraph.text.lstrip()[:1] in _QUOTE_MARKS  # a quotation in italic is the convention
    return tuple(e for e in paragraph.emphasis if not (quoted and e == "italic"))


@rule(
    "OVS106",
    "emphasis-overuse",
    "A whole paragraph of body text set in bold, italic or capitals",
    "structure",
    explanation="Emphasis works by contrast; body text that is all bold, all italic or all capitals has "
    "nothing to stand out from, and capitals read slower. Kosslyn et al. (2012) found it in 81% of sampled "
    "decks. Only paragraphs of more than ten words count -- shorter ones are headings, labels and callouts -- "
    "and source, note and caption lines ('Source: ...', 'Figure 2: ...'), quotations in italic and slide "
    "titles are exempt. "
    "Only stated bold and italic count; capitals are the All Caps option or text typed in capitals. "
    "Reported once per text frame.",
)
def emphasis_overuse(ctx):
    out = []
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.from_layout or shape.placeholder in TITLE_PLACEHOLDERS:
                continue
            hit = next((p for p in shape.paragraphs if _overused(p)), None)
            if hit:
                kinds = " and ".join(_overused(hit))
                message = f"a whole paragraph in {kinds} in '{shape.label}'"
                out.append(finding(ctx, "OVS106", message, slide.number, clip(hit.text)))
    return out


@rule(
    "OVS107",
    "underline-not-link",
    "Underlined text that is not a link",
    "structure",
    explanation="On a slide, underlining reads as a link; Kosslyn et al. (2012) found underlined non-links in "
    "46% of sampled decks. A run with a hyperlink or a click action is a link. Reported once per text frame.",
)
def underline_not_link(ctx):
    out = []
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.from_layout:
                continue
            hit = next((r for r in shape.runs if r.underline and not r.link and r.text.strip()), None)
            if hit:
                message = f"underlined text in '{shape.label}' that is not a link"
                out.append(finding(ctx, "OVS107", message, slide.number, clip(hit.text)))
    return out


SAME_COLOUR = 5.0  # CIEDE2000 under which two stated colours count as one


def _slide_colours(slide) -> list[str]:
    """Distinct text and fill colours stated on a slide, near-identical shades merged."""
    out: list[str] = []
    for shape in slide.shapes:
        if shape.from_layout:
            continue
        for c in [r.color for r in shape.runs if r.color and r.text.strip()] + [shape.fill] * bool(shape.fill):
            if not any(colour.distance(c, seen) < SAME_COLOUR for seen in out):
                out.append(c)
    return out


@rule(
    "OVS108",
    "too-many-colors",
    "More text and fill colours on a slide than a consistent design uses",
    "structure",
    explanation="Colour variety adds visual clutter (Rosenholtz et al. 2007) and lowers first-impression "
    "ratings (Reinecke et al. 2013). Counts the distinct colours stated on text and solid fills, with shades "
    "within a CIEDE2000 of 5 counted once; theme colours the file does not state as RGB are not counted. "
    "Limit: `max-colors` (default 6).",
)
def too_many_colors(ctx):
    out, limit = [], ctx.settings.max_colors
    for slide in ctx.deck.slides:
        colours = _slide_colours(slide)
        if len(colours) > limit:
            listed = ", ".join(f"#{c}" for c in colours)
            out.append(finding(ctx, "OVS108", f"{len(colours)} colours, over {limit}: {listed}", slide.number))
    return out


@rule(
    "OVS109",
    "saturated-blue-text",
    "Text in a vivid saturated blue",
    "structure",
    explanation="The eye focuses saturated blue less sharply than other hues, so thin strokes in it look "
    "blurred; Kosslyn et al. (2012) found saturated blue text in 55% of sampled decks. Checks colours stated "
    "as RGB. Reported once per text frame.",
)
def saturated_blue_text(ctx):
    out = []
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            hit = next((r for r in shape.runs if r.color and r.text.strip() and colour.saturated_blue(r.color)), None)
            if hit and not shape.from_layout:
                message = f"text in saturated blue #{hit.color} in '{shape.label}'"
                out.append(finding(ctx, "OVS109", message, slide.number, clip(hit.text)))
    return out


def _red_blue(a: str, b: str) -> bool:
    return (colour.saturated_red(a) and colour.saturated_blue(b)) or (
        colour.saturated_blue(a) and colour.saturated_red(b)
    )


@rule(
    "OVS110",
    "red-blue-adjacent",
    "Saturated red and blue side by side",
    "structure",
    explanation="Saturated red and blue focus at different depths in the eye, so where they meet they seem "
    "to sit at different distances and the edge shimmers (chromostereopsis); Kosslyn et al. (2012) found it "
    "in 36% of sampled decks. Reports red text on a blue fill (or the reverse) and red and blue filled shapes "
    "that touch or overlap. Checks colours stated as RGB.",
)
def red_blue_adjacent(ctx):
    out, tol = [], ctx.settings.tolerance_emu
    for slide in ctx.deck.slides:
        shapes = [s for s in slide.shapes if not s.from_layout]
        for shape in shapes:
            hit = next((r for r in shape.runs if shape.fill and r.color and _red_blue(r.color, shape.fill)), None)
            if hit:
                message = f"#{hit.color} text on a #{shape.fill} fill in '{shape.label}'"
                out.append(finding(ctx, "OVS110", message, slide.number, clip(hit.text)))
        filled = [s for s in shapes if s.fill and s.box]
        for i, a in enumerate(filled):
            for b in filled[i + 1 :]:
                touching = (
                    a.box.x <= b.box.right + tol
                    and b.box.x <= a.box.right + tol
                    and a.box.y <= b.box.bottom + tol
                    and b.box.y <= a.box.bottom + tol
                )
                if touching and _red_blue(a.fill, b.fill):
                    message = f"'{a.label}' (#{a.fill}) and '{b.label}' (#{b.fill}) meet"
                    out.append(finding(ctx, "OVS110", message, slide.number))
    return out
