"""Accessibility rules (OVS204-OVS208, OVS212): what Microsoft's Accessibility Checker reports --
slide titles, alt text, table headers, section names, reading order. Measured from the .pptx."""

from __future__ import annotations

import re

from overset.rules.base import clip, finding, rule


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
        shapes = [s for s in slide.shapes if s.readable]
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
