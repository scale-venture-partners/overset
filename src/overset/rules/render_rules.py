"""Rules that measure the rendered deck.

A word is attributed to the slide's text frames that contain its text and
share its column; that is how "this word belongs to the title, and the title's
frame ends 40pt above it" becomes a finding instead of a guess. Words no frame
claims -- inside a chart or SmartArt -- are left alone rather than reported.
"""

from __future__ import annotations

from collections import defaultdict

from overset.deck import Box
from overset.rules.base import clip, finding, rule

EMU_PER_INCH = 914_400


def _norm(text: str) -> str:
    return " ".join(text.replace("\u00ad", "").split()).lower()


def _owners(word, shapes, tol):
    """Text frames whose text contains this word and whose columns overlap it."""
    token = _norm(word.text).strip(".,;:!?\"'()[]")
    if not token:
        return []
    owners = []
    for shape in shapes:
        if shape.box is None or shape.kind not in ("text", "table", "group"):
            continue
        if token in _norm(shape.text) and word.box.x < shape.box.right + tol and word.box.right > shape.box.x - tol:
            owners.append(shape)
    return owners


# pdftotext reports a word's font-metric box -- ascender to descender -- not
# its ink, and display type's ascender sits well above the cap height. Against
# real decks a correctly placed 80pt title "overflows" its frame's top by about
# a fifth of its own height. Overflow worth reporting is whole lines past an
# edge, so the vertical allowance scales with the word.
METRIC_SLACK = 0.3


def fits(frame: Box, word, tol: int) -> bool:
    v = max(tol, round(METRIC_SLACK * word.box.h))
    return (word.box.x >= frame.x - tol and word.box.right <= frame.right + tol
            and word.box.y >= frame.y - v and word.box.bottom <= frame.bottom + v)


def ink(word) -> Box:
    """A word's box trimmed to roughly its ink.

    pdftotext's box runs from the font's ascent to its descent, about 1.33x the
    point size. Glyphs start near the cap height, a fifth or more below the
    top, and descenders reach nearly to the bottom -- so most of the trim comes
    off the top. Two lines set tight are not a collision; a line drawn into
    another one is.
    """
    top, bottom = round(0.28 * word.box.h), round(0.05 * word.box.h)
    return Box(word.box.x, word.box.y + top, word.box.w, max(word.box.h - top - bottom, 1))


def _distance(frame: Box, word) -> int:
    dx = max(frame.x - word.box.x, 0, word.box.right - frame.right)
    dy = max(frame.y - word.box.y, 0, word.box.bottom - frame.bottom)
    return dx + dy


def _owner_name(word, shapes, tol) -> str:
    """The frame a rendered word belongs to, or its layout block if no frame claims it."""
    owners = _owners(word, shapes, tol)
    return min(owners, key=lambda o: _distance(o.box, word)).name if owners else f"block {word.block}"


def _by_block(words):
    blocks = defaultdict(list)
    for w in words:
        blocks[w.block].append(w)
    return blocks


def _text(words) -> str:
    return clip(" ".join(w.text for w in words))


@rule("OVS001", "text-off-slide", "Rendered text runs past the slide edge", "render", severity="error",
      explanation="Measured from the render: the words are drawn outside the slide, where no one will see "
                  "them. The usual cause is a bottom-anchored title that grew upward past the top.")
def text_off_slide(ctx):
    out, frame, tol = [], ctx.deck.frame, ctx.settings.tolerance_emu
    for page in ctx.render.pages:
        for words in _by_block([w for w in page.words if not fits(frame, w, tol)]).values():
            edges = []
            for w in words:
                if w.box.y < -tol:
                    edges.append("top")
                if w.box.bottom > frame.bottom + tol:
                    edges.append("bottom")
                if w.box.x < -tol:
                    edges.append("left")
                if w.box.right > frame.right + tol:
                    edges.append("right")
            edge = "/".join(sorted(set(edges)))
            out.append(finding(ctx, "OVS001", f"text runs off the {edge} of the slide", page.number, _text(words)))
    return out


@rule("OVS002", "text-overflows-frame", "Rendered text spills out of its own frame", "render", severity="error",
      explanation="The words belong to a frame whose box ends before they do, in the layout PowerPoint shows "
                  "(shrink-to-fit frozen at its stored scale). Frames set to grow with their text are exempt -- for those, the box is stale, not the layout wrong; OVS001 and OVS003 "
                  "still catch them when the growth runs off the slide or into something else.")
def text_overflows_frame(ctx):
    out, tol = [], ctx.settings.tolerance_emu
    for page in ctx.render.pages:
        shapes = ctx.deck.slides[page.number - 1].shapes if page.number <= len(ctx.deck.slides) else []
        spilled = defaultdict(list)
        for word in page.words:
            owners = _owners(word, shapes, tol)
            if not owners or any(fits(o.box, word, tol) or o.auto_grow for o in owners):
                continue
            nearest = min(owners, key=lambda o: _distance(o.box, word))
            spilled[nearest.name].append(word)
        for name, words in spilled.items():
            out.append(finding(ctx, "OVS002", f"text spills out of '{name}'", page.number, _text(words)))
    return out


@rule("OVS003", "text-collision", "Text from two frames is drawn on top of each other", "render",
      explanation="Words owned by different text frames whose ink overlaps. Ownership comes from the deck, "
                  "not the renderer's grouping: when two frames overflow into each other, pdftotext merges "
                  "their interleaved lines into one block, which is exactly the case to catch.")
def text_collision(ctx):
    out, tol = [], ctx.settings.tolerance_emu
    for page in ctx.render.pages:
        shapes = ctx.deck.slides[page.number - 1].shapes if page.number <= len(ctx.deck.slides) else []
        words = page.words
        owners = [_owner_name(w, shapes, tol) for w in words]
        inks = [ink(w) for w in words]
        hits: dict[tuple[str, str], list] = {}
        for i, a in enumerate(words):
            for j in range(i + 1, len(words)):
                if owners[i] == owners[j]:
                    continue
                overlap = inks[i].intersection(inks[j])
                if overlap and overlap > 0.05 * min(inks[i].area, inks[j].area):
                    key = tuple(sorted((owners[i], owners[j])))
                    hits.setdefault(key, [a, words[j]])
        for (x, y), (a, b) in sorted(hits.items()):
            out.append(finding(ctx, "OVS003", f"'{x}' and '{y}' are drawn over each other", page.number,
                               clip(f"{a.text} / {b.text}", 120)))
    return out


def _luminance(rgb) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _pixel_box(box: Box, dpi: int, image_size) -> tuple[int, int, int, int] | None:
    scale = dpi / EMU_PER_INCH
    x0, y0 = max(0, int(box.x * scale)), max(0, int(box.y * scale))
    x1, y1 = min(image_size[0], int(box.right * scale) + 1), min(image_size[1], int(box.bottom * scale) + 1)
    return (x0, y0, x1, y1) if x1 - x0 >= 2 and y1 - y0 >= 2 else None


def sample_contrast(image, boxes, dpi) -> float | None:
    """Contrast between a block's background and its ink, from the pixels.

    The background is the commonest colour under the words; the ink is the
    pixel farthest from it in luminance. Antialiasing only ever pulls the ink
    toward the background, so this reads low, never high -- the safe side.
    """
    counts = defaultdict(int)
    for box in boxes:
        region = _pixel_box(box, dpi, image.size)
        if region is None:
            continue
        raw = image.crop(region).tobytes()  # RGB triples; works across Pillow versions
        for i in range(0, len(raw), 3):
            counts[(raw[i] // 8 * 8, raw[i + 1] // 8 * 8, raw[i + 2] // 8 * 8)] += 1
    if not counts:
        return None
    background = max(counts, key=counts.get)
    bl = _luminance(background)
    ink = max(counts, key=lambda c: abs(_luminance(c) - bl))
    return contrast_ratio(background, ink)


@rule("OVS104", "low-contrast", "Text too close in tone to what is behind it", "render",
      explanation="Sampled from the rendered pixels, so it holds over images, gradients and theme colours "
                  "the file never states as RGB. The threshold is WCAG's 3:1 for large text by default.")
def low_contrast(ctx):
    from PIL import Image

    out, floor = [], ctx.settings.min_contrast
    for page in ctx.render.pages:
        with Image.open(page.image) as im:
            image = im.convert("RGB")
            for words in _by_block(page.words).values():
                ratio = sample_contrast(image, [w.box for w in words], page.dpi)
                if ratio is not None and ratio < floor:
                    out.append(finding(ctx, "OVS104", f"contrast {ratio:.1f}:1, under {floor:g}:1", page.number,
                                       _text(words)))
    return out
