"""Rules that need only the .pptx."""

from __future__ import annotations

from overset.rules.base import clip, finding, rule


def _hex_distance(a: str, b: str) -> float:
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (0, 2, 4))
    return ((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5


def _in_palette(color: str, palette: list[str], tolerance: float) -> bool:
    return any(_hex_distance(color.upper(), p.upper().lstrip("#")) <= tolerance for p in palette)


def _family_allowed(font: str, allowed: set[str]) -> bool:
    """'Inter Medium' and 'Inter-Bold' are Inter: a weight is not another font."""
    name = font.lower()
    return any(name == a or name.startswith((a + " ", a + "-")) for a in allowed)


@rule("OVS004", "frame-off-slide", "A text frame extends past the slide edge", "structure",
      explanation="Measured from the file, not the render, so it holds even where a renderer clips. "
                  "Pictures are exempt: a full-bleed image is meant to reach the edge.")
def frame_off_slide(ctx):
    out, tol = [], ctx.settings.tolerance_emu
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.from_layout or shape.kind != "text" or not shape.text.strip() or shape.box is None:
                continue
            if not ctx.deck.frame.contains(shape.box, tol):
                out.append(finding(ctx, "OVS004", f"'{shape.name}' extends past the slide edge", slide.number,
                                   clip(shape.text)))
    return out


@rule("OVS101", "text-too-small", "Text set below the minimum size", "structure",
      explanation="Uses the stated size times any shrink-on-overflow scale, so text PowerPoint shrank to fit "
                  "is caught at the size it is actually shown. Inherited sizes are not resolved and are skipped.")
def text_too_small(ctx):
    out, floor = [], ctx.settings.min_font_pt
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.from_layout:
                continue
            small = [r for r in shape.runs if r.size_pt is not None and r.size_pt < floor - 0.05]
            if small:
                size = min(r.size_pt for r in small)
                out.append(finding(ctx, "OVS101", f"text at {size:.1f}pt, under {floor:g}pt", slide.number,
                                   clip(small[0].text)))
    return out


@rule("OVS102", "off-brand-font", "A font outside the configured set", "structure",
      explanation="Only stated font names are checked, by family: 'Inter Medium' is Inter. Theme fonts "
                  "(+mj-lt, +mn-lt) are the template's own and pass. Inactive until `fonts` is configured.")
def off_brand_font(ctx):
    allowed = {f.lower() for f in ctx.settings.fonts}
    if not allowed:
        return []
    out = []
    for slide in ctx.deck.slides:
        seen = set()
        for shape in slide.shapes:
            for r in shape.runs:
                if r.font and not r.font.startswith("+") and not _family_allowed(r.font, allowed) \
                        and r.font not in seen:
                    seen.add(r.font)
                    out.append(finding(ctx, "OVS102", f"font '{r.font}' is not in the brand set", slide.number,
                                       clip(r.text)))
    return out


@rule("OVS103", "off-palette-color", "A colour outside the configured palette", "structure",
      explanation="Checks colours stated as RGB on text and solid fills; theme colours are the template's own "
                  "and pass. Inactive until `palette` is configured.")
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
                colors.append((shape.fill, f"fill of '{shape.name}'"))
            for color, where in colors:
                if color not in seen and not _in_palette(color, palette, tol):
                    seen.add(color)
                    out.append(finding(ctx, "OVS103", f"#{color} is not in the brand palette", slide.number,
                                       clip(where)))
    return out


@rule("OVS201", "empty-placeholder", "A placeholder left empty", "structure",
      explanation="An empty placeholder shows 'Click to add text' to anyone who opens the deck to edit it. "
                  "Footer, date and slide-number placeholders are exempt.")
def empty_placeholder(ctx):
    out = []
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.placeholder and not shape.quiet_placeholder and shape.kind == "text" and not shape.text.strip():
                out.append(finding(ctx, "OVS201", f"empty {shape.placeholder.lower()} placeholder '{shape.name}'",
                                   slide.number))
    return out


@rule("OVS202", "image-distorted", "A picture stretched out of its aspect ratio", "structure",
      explanation="Compares the frame's aspect with the visible (cropped) source image's.")
def image_distorted(ctx):
    out, limit = [], ctx.settings.max_aspect_distortion
    for slide in ctx.deck.slides:
        for shape in slide.shapes:
            if shape.kind != "picture" or not shape.image_aspect or not shape.box or shape.box.h <= 0:
                continue
            shown = shape.box.w / shape.box.h
            distortion = abs(shown / shape.image_aspect - 1)
            if distortion > limit:
                out.append(finding(ctx, "OVS202", f"'{shape.name}' is stretched {distortion:.0%} out of shape",
                                   slide.number))
    return out


@rule("OVS203", "too-many-words", "More words on a slide than an audience will read", "structure")
def too_many_words(ctx):
    out, limit = [], ctx.settings.max_words
    for slide in ctx.deck.slides:
        if slide.words > limit:
            out.append(finding(ctx, "OVS203", f"{slide.words} words, over {limit}", slide.number))
    return out


@rule("OVS301", "repeated-layout", "Two consecutive slides use the same layout", "structure", default=False,
      explanation="Off by default: many templates build every slide on one layout. Turn it on for templates "
                  "where each slide type has its own.")
def repeated_layout(ctx):
    out = []
    slides = ctx.deck.slides
    for prev, cur in zip(slides, slides[1:], strict=False):
        if prev.layout == cur.layout:
            out.append(finding(ctx, "OVS301", f"same layout as slide {prev.number} ('{cur.layout}')", cur.number))
    return out

