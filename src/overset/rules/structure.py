"""Rules that need only the .pptx."""

from __future__ import annotations

import re

from overset import color as colour
from overset.deck import TITLE_PLACEHOLDERS
from overset.rules.base import clip, finding, rule


def _hex_distance(a: str, b: str) -> float:
    ra, ga, ba = (int(a[i : i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(b[i : i + 2], 16) for i in (0, 2, 4))
    return ((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5


def _in_palette(color: str, palette: list[str], tolerance: float, delta_e: float | None = None) -> bool:
    if delta_e is not None:
        return any(colour.distance(color, p.lstrip("#")) <= delta_e for p in palette)
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
    "and pass. A colour matches the palette within `palette-tolerance` (RGB distance, default 12), or within "
    "`palette-delta-e` (CIEDE2000, perceptual) when that is set: RGB distance is not perceptual, so one "
    "tolerance is too tight among some colours and too loose among others. Inactive until `palette` is "
    "configured.",
)
def off_palette_color(ctx):
    palette, tol, delta_e = ctx.settings.palette, ctx.settings.palette_tolerance, ctx.settings.palette_delta_e
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
                if color not in seen and not _in_palette(color, palette, tol, delta_e):
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
    "are exempt. Reported once per slide, naming each visual.",
)
def missing_alt_text(ctx):
    out = []
    for slide in ctx.deck.slides:
        missing, named = [], []
        for shape in slide.shapes:
            if not shape.graphic or shape.decorative or shape.from_layout:
                continue
            alt = " ".join(shape.alt_text.split())
            if not alt:
                missing.append(shape)
            elif _FILENAME_ALT.match(alt):
                named.append(shape)
        if len(missing) + len(named) == 1:
            shape = (missing or named)[0]
            what = "has no alt text" if missing else "has a file name for alt text"
            alt = clip(" ".join(shape.alt_text.split()))
            out.append(finding(ctx, "OVS206", f"{shape.graphic} '{shape.label}' {what}", slide.number, alt))
        elif missing or named:
            counts = [f"{len(missing)} with none"] * bool(missing) + [f"{len(named)} with a file name"] * bool(named)
            names = ", ".join(f"'{s.label}'" for s in missing + named)
            message = f"{len(missing) + len(named)} visuals need alt text ({', '.join(counts)}): {names}"
            out.append(finding(ctx, "OVS206", clip(message, 200), slide.number))
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


def kendall_tau(order: list[int]) -> float:
    """Kendall's tau between 0..n-1 and `order`: 1 for the same order, -1 for reversed."""
    n = len(order)
    if n < 2:
        return 1.0
    concordant = sum(1 for i in range(n) for j in range(i + 1, n) if order[i] < order[j])
    pairs = n * (n - 1) // 2
    return (2 * concordant - pairs) / pairs


def _row_order(boxes) -> list[int]:
    """Top to bottom, then left to right; shapes whose tops are within half the shorter one's
    height of each other share a row."""
    order = sorted(range(len(boxes)), key=lambda i: (boxes[i].y, boxes[i].x))
    rows: list[list[int]] = []
    for i in order:
        row = rows[-1] if rows else None
        if row and abs(boxes[i].y - boxes[row[0]].y) <= min(boxes[i].h, boxes[row[0]].h) / 2:
            row.append(i)
        else:
            rows.append([i])
    return [i for row in rows for i in sorted(row, key=lambda k: boxes[k].x)]


def _column_order(boxes) -> list[int]:
    """Left column to right column, top to bottom within each: shapes whose horizontal spans
    overlap share a column. A slide in two columns is read down the first, then the second."""
    columns: list[list[int]] = []
    for i in sorted(range(len(boxes)), key=lambda k: boxes[k].x):
        column = next(
            (c for c in columns if any(boxes[i].x < boxes[k].right and boxes[k].x < boxes[i].right for k in c)), None
        )
        if column is None:
            columns.append([i])
        else:
            column.append(i)
    return [i for c in columns for i in sorted(c, key=lambda k: boxes[k].y)]


def _readable(shape) -> bool:
    """A shape a screen reader announces: text, or a visual that needs alt text; not the template's,
    not decorative, not a footer, date or slide number."""
    if shape.from_layout or shape.quiet_placeholder or shape.box is None or shape.decorative:
        return False
    return bool(shape.text.strip()) or bool(shape.graphic)


@rule(
    "OVS212",
    "reading-order",
    "A screen reader reads the slide in an order that does not follow its layout",
    "structure",
    explanation="A screen reader reads shapes in the order they were added (PowerPoint's Reading Order "
    "pane), which can differ from what the eye sees. Microsoft's Accessibility Checker flags an illogical "
    "reading order. The order is compared with the layout's -- by rows, or down columns for a multi-column "
    "slide, whichever fits better -- using Kendall's tau, and reported under `min-reading-order` (default 0: "
    "more pairs out of order than in). "
    "A title that is not read first is reported too. Footers, dates, slide numbers, decorative visuals "
    "and the template's own shapes are left out.",
)
def reading_order(ctx):
    out, floor = [], ctx.settings.min_reading_order
    for slide in ctx.deck.slides:
        shapes = [s for s in slide.shapes if _readable(s)]
        title = slide.title
        if title in shapes and shapes[0] is not title:
            n = shapes.index(title) + 1
            out.append(finding(ctx, "OVS212", f"the title is read {_ordinal(n)}, not first", slide.number))
        if len(shapes) < 3:
            continue
        boxes = [s.box for s in shapes]
        tau = max(kendall_tau(_row_order(boxes)), kendall_tau(_column_order(boxes)))
        if tau < floor:
            first = ", ".join(f"'{s.label}'" for s in shapes[:3])
            message = f"reading order follows the layout poorly (tau {tau:.2f}, under {floor:g}); read first: {first}"
            out.append(finding(ctx, "OVS212", message, slide.number))
    return out


def _ordinal(n: int) -> str:
    return f"{n}{'tsnrhtdd'[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10 :: 4]}"


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
