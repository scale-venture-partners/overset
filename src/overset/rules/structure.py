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
    explanation="Measured from the file, not the render, so it holds even where a renderer clips. "
    "Pictures are exempt: a full-bleed image is meant to reach the edge.",
)
def frame_off_slide(ctx):
    out, tol = [], ctx.settings.tolerance_emu
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.from_layout or shape.kind != "text" or not shape.text.strip() or shape.box is None:
                continue
            if not ctx.deck.frame.contains(shape.box, tol):
                out.append(
                    finding(
                        ctx, "OVS004", f"'{shape.label}' extends past the slide edge", slide.number, clip(shape.text)
                    )
                )
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
    explanation="Compares the frame's aspect with the visible (cropped) source image's.",
)
def image_distorted(ctx):
    out, limit = [], ctx.settings.max_aspect_distortion
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.kind != "picture" or not shape.image_aspect or not shape.box or shape.box.h <= 0:
                continue
            shown = shape.box.w / shape.box.h
            distortion = abs(shown / shape.image_aspect - 1)
            if distortion > limit:
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
