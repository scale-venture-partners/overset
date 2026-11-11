"""Rules that need only the .pptx."""

from __future__ import annotations

import re

from overset.deck import TITLE_PLACEHOLDERS
from overset.rules.base import clip, finding, rule


def _hex_distance(a: str, b: str) -> float:
    ra, ga, ba = (int(a[i : i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(b[i : i + 2], 16) for i in (0, 2, 4))
    return ((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5


def _in_palette(color: str, palette: list[str], tolerance: float) -> bool:
    return any(_hex_distance(color.upper(), p.upper().lstrip("#")) <= tolerance for p in palette)


def _family_allowed(font: str, allowed: set[str]) -> bool:
    """'Inter Medium' and 'Inter-Bold' are Inter: a weight is not another font."""
    name = font.lower()
    return any(name == a or name.startswith((a + " ", a + "-")) for a in allowed)


@rule(
    "OVS000",
    "invalid-package",
    "The file is not a well-formed PowerPoint package",
    "structure",
    severity="error",
    explanation="A part with no content type, a relationship to a part that isn't there, or XML that doesn't "
    "parse. PowerPoint offers to repair such a deck when it opens; python-pptx refuses to load it. "
    "Checked before anything else (overset.package), so the deck's other rules don't run when it "
    "can't be loaded.",
)
def invalid_package(ctx):
    return []  # computed by the engine before the deck loads; see engine._package_findings


@rule(
    "OVS004",
    "frame-off-slide",
    "A text frame extends past the slide edge",
    "structure",
    explanation="Measured from the file, not the render, so it holds even where a renderer clips. Only "
    "the part of the frame text can occupy counts -- the box less its inner margins -- so a frame "
    "whose padding hangs over the edge is fine. A frame entirely off the slide is said so: it is "
    "invisible in the slide show. Pictures are exempt: a full-bleed image is meant to reach the edge.",
)
def frame_off_slide(ctx):
    out, tol, slide_box = [], ctx.settings.tolerance_emu, ctx.deck.frame
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            area = shape.text_area or shape.box
            if shape.from_layout or shape.kind != "text" or not shape.text.strip() or area is None:
                continue
            if slide_box.contains(area, tol):
                continue
            where = "is entirely off the slide" if not slide_box.intersection(area) else "extends past the slide edge"
            out.append(finding(ctx, "OVS004", f"'{shape.label}' {where}", slide.number, clip(shape.text)))
    return out


@rule(
    "OVS101",
    "text-too-small",
    "Text set below the minimum size",
    "structure",
    explanation="Uses the run's size -- stated, or inherited from the layout, master or presentation "
    "defaults -- times any shrink-on-overflow scale, so text PowerPoint shrank to fit is caught at the "
    "size it is actually shown. Table text that doesn't state a size is skipped.",
)
def text_too_small(ctx):
    out, floor = [], ctx.settings.min_font_pt
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.from_layout:
                continue
            small = [r for r in shape.runs if r.size_pt is not None and r.size_pt < floor - 0.05]
            if small:
                size = min(r.size_pt for r in small)
                out.append(
                    finding(
                        ctx, "OVS101", f"text at {size:.1f}pt, under {floor:g}pt", slide.number, clip(small[0].text)
                    )
                )
    return out


@rule(
    "OVS102",
    "off-brand-font",
    "A font outside the configured set",
    "structure",
    explanation="Only stated font names are checked, by family: 'Inter Medium' is Inter. Theme fonts "
    "(+mj-lt, +mn-lt) are the template's own and pass. Inactive until `fonts` is configured.",
)
def off_brand_font(ctx):
    allowed = {f.lower() for f in ctx.settings.fonts}
    if not allowed:
        return []
    out = []
    for slide in ctx.deck.slides:
        seen = set()
        for shape in slide.shapes:
            for r in shape.runs:
                if (
                    r.font
                    and not r.font.startswith("+")
                    and not _family_allowed(r.font, allowed)
                    and r.font not in seen
                ):
                    seen.add(r.font)
                    out.append(
                        finding(ctx, "OVS102", f"font '{r.font}' is not in the brand set", slide.number, clip(r.text))
                    )
    return out


@rule(
    "OVS103",
    "off-palette-color",
    "A colour outside the configured palette",
    "structure",
    explanation="Checks colours stated as RGB on text and solid fills; theme colours are the template's own "
    "and pass. Inactive until `palette` is configured.",
)
def off_palette_color(ctx):
    palette, tol = ctx.settings.palette, ctx.settings.palette_tolerance
    if not palette:
        return []
    out = []
    for slide in ctx.deck.slides:
        seen = set()
        for shape in slide.shapes:
            if shape.from_layout:
                continue
            colors = [(r.color, r.text) for r in shape.runs if r.color]
            if shape.fill:
                colors.append((shape.fill, f"fill of '{shape.label}'"))
            for color, where in colors:
                if color not in seen and not _in_palette(color, palette, tol):
                    seen.add(color)
                    out.append(
                        finding(ctx, "OVS103", f"#{color} is not in the brand palette", slide.number, clip(where))
                    )
    return out


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


LABEL_WORDS = 4  # a paragraph shorter than this is a label, where caps or bold are a style choice


@rule(
    "OVS106",
    "emphasis-overuse",
    "A whole paragraph set in bold, italic or capitals",
    "structure",
    explanation="Emphasis works by contrast; a paragraph that is all bold, all italic or all capitals has "
    "nothing to stand out from, and capitals read slower. Kosslyn et al. (2012) found it in 81% of sampled "
    "decks. Paragraphs under four words (labels) and slide titles are exempt. Only stated bold and italic "
    "count; capitals are the All Caps option or text typed in capitals. Reported once per text frame.",
)
def emphasis_overuse(ctx):
    out = []
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.from_layout or shape.placeholder in TITLE_PLACEHOLDERS:
                continue
            hit = next((p for p in shape.paragraphs if p.emphasis and len(p.text.split()) >= LABEL_WORDS), None)
            if hit:
                kinds = " and ".join(hit.emphasis)
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


@rule(
    "OVS201",
    "empty-placeholder",
    "A placeholder left empty",
    "structure",
    explanation="An empty placeholder shows 'Click to add text' to anyone who opens the deck to edit it. "
    "Footer, date and slide-number placeholders are exempt.",
)
def empty_placeholder(ctx):
    out = []
    # An empty title is reported once, as a missing title, when that rule is on.
    titles_elsewhere = "OVS204" in ctx.settings.active_codes()
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if titles_elsewhere and shape.placeholder in TITLE_PLACEHOLDERS:
                continue
            if shape.placeholder and not shape.quiet_placeholder and shape.kind == "text" and not shape.text.strip():
                out.append(
                    finding(
                        ctx, "OVS201", f"empty {shape.placeholder.lower()} placeholder '{shape.label}'", slide.number
                    )
                )
    return out


@rule(
    "OVS202",
    "image-distorted",
    "A picture stretched out of its aspect ratio",
    "structure",
    explanation="Compares the frame's aspect with the visible (cropped) source image's. A small image's "
    "own aspect is only known to the nearest pixel -- a 20-pixel icon's to about 5% -- so distortion "
    "within that rounding is not counted.",
)
def image_distorted(ctx):
    out, limit = [], ctx.settings.max_aspect_distortion
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.kind != "picture" or not shape.image_size or not shape.box or shape.box.h <= 0:
                continue
            w, h = shape.image_size
            shown = shape.box.w / shape.box.h
            distortion = abs(shown * h / w - 1)
            # The source's true aspect lies anywhere within half a pixel each way; only distortion
            # beyond that range is the frame's.
            low, high = max(w - 0.5, 1e-9) / (h + 0.5), (w + 0.5) / max(h - 0.5, 1e-9)
            beyond = abs(shown / min(max(shown, low), high) - 1)
            if beyond > limit:
                out.append(
                    finding(ctx, "OVS202", f"'{shape.label}' is stretched {distortion:.0%} out of shape", slide.number)
                )
    return out


@rule("OVS203", "too-many-words", "More words on a slide than an audience will read", "structure")
def too_many_words(ctx):
    out, limit = [], ctx.settings.max_words
    for slide in ctx.deck.slides:
        if slide.words > limit:
            out.append(finding(ctx, "OVS203", f"{slide.words} words, over {limit}", slide.number))
    return out


@rule(
    "OVS204",
    "missing-slide-title",
    "A slide with no title",
    "structure",
    explanation="A slide's title is what a screen reader announces and what the outline, the slide "
    "sorter and navigation show; Microsoft's Accessibility Checker reports a missing one as an error. "
    "Only a title placeholder counts, not a text box styled like one. An empty title placeholder is "
    "reported here rather than as OVS201. Hidden slides are skipped.",
)
def missing_slide_title(ctx):
    out = []
    for slide in ctx.deck.slides:
        if slide.hidden:
            continue
        title = slide.title
        if title is None:
            out.append(finding(ctx, "OVS204", "no title placeholder", slide.number))
        elif not title.text.strip():
            out.append(finding(ctx, "OVS204", f"title placeholder '{title.label}' is empty", slide.number))
    return out


@rule(
    "OVS205",
    "duplicate-slide-title",
    "Two slides share a title",
    "structure",
    explanation="Slides with the same title can't be told apart by a screen-reader user or in the "
    "outline; Microsoft's Accessibility Checker suggests making each one unique. Compared ignoring case "
    "and spacing. Each repeat is reported once, against the first slide with that title. Hidden slides "
    "are skipped.",
)
def duplicate_slide_title(ctx):
    out, first = [], {}
    for slide in ctx.deck.slides:
        if slide.hidden or slide.title is None:
            continue
        text = " ".join(slide.title.text.split())
        key = text.casefold()
        if not key:
            continue
        if key in first:
            out.append(finding(ctx, "OVS205", f"same title as slide {first[key]}", slide.number, clip(text)))
        else:
            first[key] = slide.number
    return out


# Alt text that only names the file or the shape, as PowerPoint and cameras fill it in.
_FILENAME_ALT = re.compile(
    r"""^(?:
        .*\.(?:png|jpe?g|gif|bmp|tiff?|svg|emf|wmf|webp|heic)       # a file name
      | (?:img|dsc|dscn|pxl|photo)[\s_-]*[\d\s_:.-]*                  # a camera's name
      | (?:screenshot|screen\ shot)[\d\s_:.,-]*(?:at[\d\s_:.,-]*)?(?:[ap]m)?  # macOS / Windows screenshots
      | (?:picture|image|graphic|chart|diagram|object)\s*\d+          # a default shape name
    )$""",
    re.IGNORECASE | re.VERBOSE,
)


@rule(
    "OVS206",
    "missing-alt-text",
    "A picture, chart or graphic with no alt text",
    "structure",
    explanation="A screen reader has nothing to say for a visual without a description; Microsoft's "
    "Accessibility Checker reports one as an error, including alt text that is only a file name. "
    "Checks pictures (including video), charts, SmartArt and embedded objects on the slide, inside "
    "groups too. Visuals marked decorative in PowerPoint, and the template's own (layout and master), "
    "are exempt.",
)
def missing_alt_text(ctx):
    out = []
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if not shape.graphic or shape.decorative or shape.from_layout:
                continue
            alt = " ".join(shape.alt_text.split())
            if not alt:
                message = f"{shape.graphic} '{shape.label}' has no alt text"
            elif _FILENAME_ALT.match(alt):
                message = f"{shape.graphic} '{shape.label}' has a file name for alt text"
            else:
                continue
            out.append(finding(ctx, "OVS206", message, slide.number, clip(alt)))
    return out


@rule(
    "OVS207",
    "table-without-header",
    "A table with no header row",
    "structure",
    explanation="A screen reader announces a table's header cells as the reader moves through it; without "
    "a header row the cells are numbers with no labels. Microsoft's Accessibility Checker reports it as an "
    "error. Checks the table's 'Header Row' option (tblPr firstRow).",
)
def table_without_header(ctx):
    out = []
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.kind == "table" and not shape.from_layout and shape.header_row is False:
                out.append(finding(ctx, "OVS207", f"table '{shape.label}' has no header row", slide.number))
    return out


DEFAULT_SECTION_NAMES = {"default section", "untitled section"}


@rule(
    "OVS208",
    "default-section-name",
    "A section left with PowerPoint's default name",
    "structure",
    explanation="Section names are how a screen-reader user, and anyone in the slide sorter, finds their "
    "way around a long deck. Microsoft's Accessibility Checker reports 'Default Section' and 'Untitled "
    "Section' as errors. Reported at the section's first slide.",
)
def default_section_name(ctx):
    out = []
    for section in ctx.deck.sections:
        name = " ".join(section.name.split())
        if name.casefold() in DEFAULT_SECTION_NAMES:
            first = section.slides[0] if section.slides else None
            out.append(finding(ctx, "OVS208", f"section '{name}' has a default name", first))
    return out


def _lists(paragraphs):
    """Each run of sibling bullets -- items at one level under one parent -- as
    (level, items). A paragraph without a bullet ends every open list; a return to
    a shallower level ends the deeper ones."""
    open_lists: dict[int, list] = {}
    for p in paragraphs:
        if not p.bulleted:
            yield from ((lvl, items) for lvl, items in sorted(open_lists.items()))
            open_lists = {}
            continue
        for deeper in sorted(lvl for lvl in open_lists if lvl > p.level):
            yield deeper, open_lists.pop(deeper)
        open_lists.setdefault(p.level, []).append(p)
    yield from ((lvl, items) for lvl, items in sorted(open_lists.items()))


@rule(
    "OVS209",
    "too-many-bullets",
    "A list with more items than an audience will hold",
    "structure",
    explanation="Counts sibling bullets: items at one level under one parent. Kosslyn et al. (2012) found "
    "lists of more than four items in 91% of 140 sampled decks. Paragraphs count as bullets when they show "
    "a bullet or a number, stated or inherited from the layout. Limit: `max-bullets` (default 4).",
)
def too_many_bullets(ctx):
    out, limit = [], ctx.settings.max_bullets
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.from_layout:
                continue
            for _, items in _lists(shape.paragraphs):
                if len(items) > limit:
                    message = f"{len(items)} bullets in one list in '{shape.label}', over {limit}"
                    out.append(finding(ctx, "OVS209", message, slide.number, clip(items[0].text)))
    return out


@rule(
    "OVS211",
    "bullet-depth",
    "Bullets nested deeper than an audience can follow",
    "structure",
    explanation="Kosslyn et al. (2012) found lists nested past a shallow hierarchy in 86% of sampled decks. "
    "Reported once per text frame, at its deepest bullet. Limit: `max-bullet-depth` levels (default 2).",
)
def bullet_depth(ctx):
    out, limit = [], ctx.settings.max_bullet_depth
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.from_layout:
                continue
            deep = [p for p in shape.paragraphs if p.bulleted and p.level + 1 > limit]
            if deep:
                deepest = max(deep, key=lambda p: p.level)
                message = f"bullets nested {deepest.level + 1} levels deep in '{shape.label}', over {limit}"
                out.append(finding(ctx, "OVS211", message, slide.number, clip(deepest.text)))
    return out


@rule(
    "OVS301",
    "repeated-layout",
    "Two consecutive slides use the same layout",
    "structure",
    default=False,
    explanation="Off by default: many templates build every slide on one layout. Turn it on for templates "
    "where each slide type has its own.",
)
def repeated_layout(ctx):
    out = []
    slides = ctx.deck.slides
    for prev, cur in zip(slides, slides[1:], strict=False):
        if prev.layout == cur.layout:
            out.append(finding(ctx, "OVS301", f"same layout as slide {prev.number} ('{cur.layout}')", cur.number))
    return out
