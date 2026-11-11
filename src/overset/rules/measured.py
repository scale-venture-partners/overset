"""Measured counterparts for the vision rules (#18): what a vision model is asked to judge,
approximated by a measurement that needs no model.

- OVS008 (for OVS401, clutter): edge density of the rendered slide. Edge density tracks visual
  clutter and predicts search performance (Rosenholtz, Li & Nakano 2007, with feature congestion;
  Inui et al. use edge density for slides). No absolute threshold is published, so a slide is
  compared with the rest of its own deck.
- OVS009 (for OVS404, text over a busy image): edge density of the background inside a text frame,
  with the words themselves masked out.
- OVS111 (for OVS402, weak hierarchy): body text set at least as large as the title. Kosslyn et al.
  (2012) found text more salient than the title in 29% of decks.
- OVS112 (for OVS406, inconsistent style): a slide whose fonts or title size the rest of its deck
  doesn't use (Kosslyn: changes that carry no information in 72% of decks).

All are off by default: the evidence supports the measures, not thresholds, and calibrating them
needs labelled slides (#20). The vision rules remain available.
"""

from __future__ import annotations

import statistics
from collections import Counter

from overset.rules.base import clip, finding, rule
from overset.rules.render_rules import assign_owners
from overset.rules.structure import TITLE_PLACEHOLDERS, font_family

EMU_PER_INCH = 914_400
EDGE_LEVEL = 32  # a pixel whose edge response (0-255) exceeds this is an edge
ANALYSIS_WIDTH = 480  # slides are measured at this width, so density doesn't depend on render resolution


def _edge_map(image):
    from PIL import ImageFilter

    gray = image.convert("L")
    if gray.width > ANALYSIS_WIDTH:
        gray = gray.resize((ANALYSIS_WIDTH, round(gray.height * ANALYSIS_WIDTH / gray.width)))
    return _inner(gray.filter(ImageFilter.FIND_EDGES))


def _inner(edges):
    """The edge filter answers at the image's own border, where there is no edge: drop that ring."""
    return edges.crop((1, 1, edges.width - 1, edges.height - 1))


def edge_density(image) -> float:
    """The share of a slide's pixels that sit on an edge."""
    edges = _edge_map(image)
    histogram = edges.histogram()
    return sum(histogram[EDGE_LEVEL + 1 :]) / (edges.width * edges.height)


def _robust_outliers(values: dict[int, float], spread: float) -> dict[int, float]:
    """Values more than `spread` median absolute deviations above the median."""
    if len(values) < 5:
        return {}
    median = statistics.median(values.values())
    mad = statistics.median(abs(v - median) for v in values.values()) or 1e-9
    return {k: (v - median) / mad for k, v in values.items() if (v - median) / mad > spread}


@rule(
    "OVS008",
    "cluttered-slide",
    "A slide far busier than the rest of its deck",
    "render",
    default=False,
    explanation="Edge density -- the share of the rendered slide's pixels on an edge -- tracks visual "
    "clutter (Rosenholtz, Li & Nakano 2007; Inui et al.). No absolute threshold is published, so a slide "
    "is reported when its density is more than `clutter-spread` (default 3) median absolute deviations "
    "above its deck's median. Decks of fewer than five slides are skipped. Off by default until calibrated.",
)
def cluttered_slide(ctx):
    from PIL import Image

    densities = {}
    for page in ctx.render.pages:
        with Image.open(page.image) as im:
            densities[page.number] = edge_density(im)
    median = statistics.median(densities.values()) if densities else 0
    out = []
    for number, score in sorted(_robust_outliers(densities, ctx.settings.clutter_spread).items()):
        message = f"edge density {densities[number]:.0%}, against the deck's median {median:.0%} ({score:.1f} MADs)"
        out.append(finding(ctx, "OVS008", message, number))
    return out


def background_busyness(image, frame, words, dpi) -> float | None:
    """Edge density of a text frame's background: the frame's pixels, less its words (each grown
    by a fifth of its height, so glyph edges stay out). None when too little background is left."""
    px = dpi / EMU_PER_INCH
    x0, y0 = max(0, int(frame.x * px)), max(0, int(frame.y * px))
    x1, y1 = min(image.width, int(frame.right * px)), min(image.height, int(frame.bottom * px))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    from PIL import ImageFilter

    region = _inner(image.crop((x0 - 1, y0 - 1, x1 + 1, y1 + 1)).convert("L").filter(ImageFilter.FIND_EDGES))
    mask = bytearray([1]) * (region.width * region.height)
    for w in words:
        pad = 0.2 * w.box.h
        wx0, wy0 = int((w.box.x - pad) * px) - x0, int((w.box.y - pad) * px) - y0
        wx1, wy1 = int((w.box.right + pad) * px) - x0, int((w.box.bottom + pad) * px) - y0
        for y in range(max(0, wy0), min(region.height, wy1)):
            row = y * region.width
            lo, hi = max(0, wx0), min(region.width, wx1)
            if hi > lo:
                mask[row + lo : row + hi] = bytes(hi - lo)
    pixels = region.tobytes()
    kept = [p for p, m in zip(pixels, mask, strict=True) if m]
    if len(kept) < 200:
        return None
    return sum(1 for p in kept if p > EDGE_LEVEL) / len(kept)


@rule(
    "OVS009",
    "busy-behind-text",
    "Text set over a busy background",
    "render",
    default=False,
    explanation="Edge density of the background inside a text frame, with the words masked out: a "
    "photograph or pattern behind text makes it harder to read even when the contrast measured at the "
    "letters (OVS104) passes. Reported above `max-background-busyness` (default 0.08, about the starter "
    "corpus's 99th percentile). Off by default until calibrated.",
)
def busy_behind_text(ctx):
    from PIL import Image

    out, tol, limit = [], ctx.settings.tolerance_emu, ctx.settings.max_background_busyness
    for page in ctx.render.pages:
        shapes = ctx.deck.slides[page.number - 1].shapes if page.number <= len(ctx.deck.slides) else []
        owned: dict[int, tuple] = {}
        for word, owner in zip(page.words, assign_owners(page.words, shapes, tol), strict=True):
            if owner is not None and not owner.from_layout and owner.box is not None:
                owned.setdefault(id(owner), (owner, []))[1].append(word)
        with Image.open(page.image) as im:
            image = im.convert("RGB")
            for shape, words in owned.values():
                score = background_busyness(image, shape.box, words, page.dpi)
                if score is not None and score > limit:
                    message = f"busy background behind '{shape.label}' (edge density {score:.0%})"
                    out.append(finding(ctx, "OVS009", message, page.number, clip(shape.text)))
    return out


@rule(
    "OVS111",
    "weak-title-hierarchy",
    "Body text set as large as the title",
    "structure",
    default=False,
    explanation="The title should be the first thing the eye lands on; Kosslyn et al. (2012) found text "
    "more salient than the title in 29% of decks. Reports a slide whose title is not larger than its "
    "largest other text by `min-title-ratio` (default 1.0: not larger at all). Sizes are effective ones, "
    "inherited sizes resolved. Off by default: a large number or quote can be a slide's point by design.",
)
def weak_title_hierarchy(ctx):
    out, ratio = [], ctx.settings.min_title_ratio
    for slide in ctx.deck.slides:
        title = slide.title
        title_sizes = [r.size_pt for r in title.runs if r.size_pt] if title else []
        if not title_sizes:
            continue
        body = [
            (r.size_pt, r.text)
            for s in slide.shapes
            if s is not title and not s.from_layout and s.placeholder not in TITLE_PLACEHOLDERS
            for r in s.runs
            if r.size_pt and r.text.strip()
        ]
        if not body:
            continue
        top, text = max(body)
        if max(title_sizes) < top * ratio or (ratio == 1.0 and max(title_sizes) <= top):
            message = f"title at {max(title_sizes):g}pt, other text at {top:g}pt"
            out.append(finding(ctx, "OVS111", message, slide.number, clip(text)))
    return out


@rule(
    "OVS112",
    "off-style-slide",
    "A slide whose fonts or title size the rest of the deck doesn't use",
    "structure",
    default=False,
    explanation="Consistency lets the audience read changes as meaning; Kosslyn et al. (2012) found "
    "changes that carry none in 72% of decks. Reports a slide that uses a font family no other slide "
    "uses, or whose title size is more than 15% off the deck's most common title size. Decks of fewer "
    "than five slides are skipped. Off by default until calibrated.",
)
def off_style_slide(ctx):
    slides = ctx.deck.slides
    if len(slides) < 5:
        return []
    families = {
        s.number: {font_family(r.face) for sh in s.shapes if not sh.from_layout for r in sh.runs if r.face}
        for s in slides
    }
    uses = Counter(f for fs in families.values() for f in fs)
    title_size = {
        s.number: max(r.size_pt for r in s.title.runs if r.size_pt)
        for s in slides
        if s.title and any(r.size_pt for r in s.title.runs)
    }
    common = Counter(round(v) for v in title_size.values()).most_common(1)
    out = []
    for s in slides:
        own = sorted(f for f in families[s.number] if uses[f] == 1)
        if own:
            out.append(finding(ctx, "OVS112", f"uses {', '.join(own)}, which no other slide does", s.number))
        if common and s.number in title_size and abs(title_size[s.number] / common[0][0] - 1) > 0.15:
            message = f"title at {title_size[s.number]:g}pt, against the deck's usual {common[0][0]}pt"
            out.append(finding(ctx, "OVS112", message, s.number))
    return out
