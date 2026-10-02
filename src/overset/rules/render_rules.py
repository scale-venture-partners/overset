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


def _token(text: str) -> str:
    return _norm(text).strip(".,;:!?\"'()[]\u201c\u201d\u2018\u2019")


LOOKAHEAD = 3  # tokens a frame's sequence may skip: hyphenation, ligatures, a dropped glyph


def assign_owners(words, shapes, tol) -> list:
    """The frame each rendered word belongs to, by reading sequence first.

    Geometry alone cannot attribute a word that overflowed into another frame
    and also appears in that frame's text -- "rules" ending a title that ran
    into a body reading "Two rules removed..." sits inside the body's box. The
    renderer writes each frame's text in one run, so a word belongs to the
    frame whose text it continues: the frame the previous word came from, if
    its next token matches, else a frame whose sequence it starts or resumes.
    Geometry is the fallback. Returns a Shape, or None, per word.
    """
    seqs = {id(s): [_token(t) for t in s.text.split()] for s in shapes
            if s.box is not None and s.kind in ("text", "table", "group") and s.text.strip()}
    by_id = {id(s): s for s in shapes}
    pos = dict.fromkeys(seqs, 0)
    current, out = None, []

    def advance(sid, token):
        seq, start = seqs[sid], pos[sid]
        for i in range(start, min(start + LOOKAHEAD + 1, len(seq))):
            if seq[i] == token:
                pos[sid] = i + 1
                return True
        return False

    for w in words:
        token = _token(w.text)
        owner = None
        # Only frames whose column the word sits in can own it. Continuing the previous
        # word's frame must pass that test too: pdftotext reads a row of cards line by
        # line across the columns, so the word after card 1's first line is card 2's,
        # and card 1's text may well hold the same short word a few tokens on.
        candidates = [o for o in _owners(w, shapes, tol) if id(o) in seqs] if token else []
        column = {id(o) for o in candidates}
        if token and current is not None and current in column and advance(current, token):
            owner = current
        elif token:
            resuming = [o for o in candidates if pos[id(o)] and seqs[id(o)][pos[id(o)]:pos[id(o)] + 1] == [token]]
            starting = [o for o in candidates if not pos[id(o)] and seqs[id(o)][:1] == [token]]
            pick = resuming or starting or candidates
            if pick:
                o = min(pick, key=lambda o: _distance(o.box, w))
                advance(id(o), token)
                owner = id(o)
        current = owner
        out.append(by_id[owner] if owner is not None else None)
    return out


def _owner_name(shape, word) -> str:
    return shape.name if shape is not None else f"block {word.block}"


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
      explanation="The words belong to a frame whose box ends before they do, in the layout PowerPoint "
                  "shows (shrink-to-fit frozen at its stored scale). Frames set to grow with their text are "
                  "exempt -- for those, the box is stale, not the layout wrong; OVS001 and OVS003 "
                  "still catch them when the growth runs off the slide or into something else.")
def text_overflows_frame(ctx):
    out, tol = [], ctx.settings.tolerance_emu
    for page in ctx.render.pages:
        shapes = ctx.deck.slides[page.number - 1].shapes if page.number <= len(ctx.deck.slides) else []
        spilled = defaultdict(list)
        for word, owner in zip(page.words, assign_owners(page.words, shapes, tol), strict=True):
            if owner is None or owner.auto_grow or fits(owner.box, word, tol):
                continue
            spilled[owner.name].append(word)
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
        owners = [_owner_name(o, w) for o, w in zip(assign_owners(words, shapes, tol), words, strict=True)]
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


# Colours covering this share of the sampled pixels are ink candidates.
INK_SHARE = 0.02
# Below this, a colour is a stray speck -- a corner of a rule, a dust pixel --
# not text. Small, thin type spreads its ink over many antialiased shades that
# each cover less than INK_SHARE, so the farthest colour above the speck floor
# is a candidate too.
SPECK_SHARE = 0.003


def sample_contrast(image, boxes, dpi) -> float | None:
    """Contrast between a block's background and its ink, from the pixels.

    The background is the commonest colour under the words. The ink is the
    candidate that contrasts with it most, where the candidates are every
    colour covering at least INK_SHARE of the pixels plus the colour farthest
    from the background in luminance (above the speck floor). Farthest alone
    went wrong for text on a shape smaller than the word's box -- dark digits
    on a green dot, with paper round the dot, measured green against paper
    (2.1:1). Large shares alone went wrong for small thin type, whose ink is
    spread over many faint shades. Antialiasing only pulls ink toward the
    background, so this reads low, never high.
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
    total = sum(counts.values())
    background = max(counts, key=counts.get)
    bl = _luminance(background)
    candidates = [c for c, n in counts.items() if c != background and n >= INK_SHARE * total]
    visible = [c for c, n in counts.items() if n >= SPECK_SHARE * total] or list(counts)
    candidates.append(max(visible, key=lambda c: abs(_luminance(c) - bl)))
    return max(contrast_ratio(background, c) for c in candidates)


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
