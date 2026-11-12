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
        if shape.box is None or shape.kind not in ("text", "table"):
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
    return (
        word.box.x >= frame.x - tol
        and word.box.right <= frame.right + tol
        and word.box.y >= frame.y - v
        and word.box.bottom <= frame.bottom + v
    )


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
    seqs = {
        id(s): [_token(t) for t in s.text.split()]
        for s in shapes
        if s.box is not None and s.kind in ("text", "table") and s.text.strip()
    }
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
            resuming = [o for o in candidates if pos[id(o)] and seqs[id(o)][pos[id(o)] : pos[id(o)] + 1] == [token]]
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
    return shape.label if shape is not None else f"block {word.block}"


def _by_block(words):
    blocks = defaultdict(list)
    for w in words:
        blocks[w.block].append(w)
    return blocks


def _text(words) -> str:
    return clip(" ".join(w.text for w in words))


@rule(
    "OVS001",
    "text-off-slide",
    "Rendered text runs past the slide edge",
    "render",
    severity="error",
    explanation="Measured from the render: the words are drawn outside the slide, where no one will see "
    "them. The usual cause is a bottom-anchored title that grew upward past the top.",
)
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


@rule(
    "OVS002",
    "text-overflows-frame",
    "Rendered text spills out of its own frame",
    "render",
    severity="error",
    explanation="The words belong to a frame whose box ends before they do, in the layout PowerPoint "
    "shows (shrink-to-fit frozen at its stored scale). Frames set to grow with their text are "
    "exempt -- for those, the box is stale, not the layout wrong; OVS001 and OVS003 "
    "still catch them when the growth runs off the slide or into something else.",
)
def text_overflows_frame(ctx):
    out, tol = [], ctx.settings.tolerance_emu
    for page in ctx.render.pages:
        shapes = ctx.deck.slides[page.number - 1].shapes if page.number <= len(ctx.deck.slides) else []
        spilled = defaultdict(list)
        for word, owner in zip(page.words, assign_owners(page.words, shapes, tol), strict=True):
            if owner is None or owner.auto_grow or fits(owner.box, word, tol):
                continue
            spilled[owner.label].append(word)
        for name, words in spilled.items():
            out.append(finding(ctx, "OVS002", f"text spills out of '{name}'", page.number, _text(words)))
    return out


def colliding_pairs(inks: list[Box], owners: list[str]) -> dict[tuple[str, str], tuple[int, int]]:
    """Pairs of words from different owners whose ink overlaps by more than 5% of
    the smaller word: for each pair of owners, the first such pair of word
    indices (i < j, in reading order).

    Words are swept top to bottom, and each is compared only with the words
    that start above its bottom edge, so a dense slide costs about n log n
    comparisons rather than n squared.
    """
    order = sorted(range(len(inks)), key=lambda k: inks[k].y)
    hits: dict[tuple[str, str], tuple[int, int]] = {}
    for pos, a in enumerate(order):
        for b in order[pos + 1 :]:
            if inks[b].y >= inks[a].bottom:
                break  # this word and every later one start below a's ink
            if owners[a] == owners[b]:
                continue
            overlap = inks[a].intersection(inks[b])
            if overlap and overlap > 0.05 * min(inks[a].area, inks[b].area):
                key = tuple(sorted((owners[a], owners[b])))
                pair = (min(a, b), max(a, b))
                if key not in hits or pair < hits[key]:
                    hits[key] = pair
    return hits


@rule(
    "OVS003",
    "text-collision",
    "Text from two frames is drawn on top of each other",
    "render",
    explanation="Words owned by different text frames whose ink overlaps. Ownership comes from the deck, "
    "not the renderer's grouping: when two frames overflow into each other, pdftotext merges "
    "their interleaved lines into one block, which is exactly the case to catch.",
)
def text_collision(ctx):
    out, tol = [], ctx.settings.tolerance_emu
    for page in ctx.render.pages:
        shapes = ctx.deck.slides[page.number - 1].shapes if page.number <= len(ctx.deck.slides) else []
        words = page.words
        owners = [_owner_name(o, w) for o, w in zip(assign_owners(words, shapes, tol), words, strict=True)]
        hits = colliding_pairs([ink(w) for w in words], owners)
        for (x, y), (i, j) in sorted(hits.items()):
            a, b = words[i], words[j]
            out.append(
                finding(
                    ctx,
                    "OVS003",
                    f"'{x}' and '{y}' are drawn over each other",
                    page.number,
                    clip(f"{a.text} / {b.text}", 120),
                )
            )
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


def _paragraph_of(words, shape) -> list[int | None]:
    """Which of the shape's paragraphs each of its rendered words belongs to, by
    following the paragraphs' text in reading order."""
    flat = [(i, _token(t)) for i, p in enumerate(shape.paragraphs) for t in p.text.split()]
    out, k = [], 0
    for w in words:
        token, found = _token(w.text), None
        for j in range(k, min(k + LOOKAHEAD + 1, len(flat))):
            if flat[j][1] == token:
                found, k = flat[j][0], j + 1
                break
        out.append(found)
    return out


def _line_count(words) -> int:
    """Rendered lines among a paragraph's words: centres more than half a word's
    height apart start a new line."""
    centres = sorted(w.box.y + w.box.h / 2 for w in words)
    if not centres:
        return 0
    height = sorted(w.box.h for w in words)[len(words) // 2]
    return 1 + sum(1 for a, b in zip(centres, centres[1:], strict=False) if b - a > height / 2)


@rule(
    "OVS210",
    "long-bullet",
    "A bullet that runs to more lines than an audience will read",
    "render",
    explanation="Counts the lines a bullet paragraph renders on. Kosslyn et al. (2012) found bullets of "
    "more than two lines in 91% of 140 sampled decks. Limit: `max-bullet-lines` (default 2).",
)
def long_bullet(ctx):
    out, tol, limit = [], ctx.settings.tolerance_emu, ctx.settings.max_bullet_lines
    for page in ctx.render.pages:
        shapes = ctx.deck.slides[page.number - 1].shapes if page.number <= len(ctx.deck.slides) else []
        owned = defaultdict(list)
        for word, owner in zip(page.words, assign_owners(page.words, shapes, tol), strict=True):
            if owner is not None and not owner.from_layout and any(p.bulleted for p in owner.paragraphs):
                owned[id(owner)].append((owner, word))
        for pairs in owned.values():
            shape, words = pairs[0][0], [w for _, w in pairs]
            by_paragraph = defaultdict(list)
            for word, index in zip(words, _paragraph_of(words, shape), strict=True):
                if index is not None:
                    by_paragraph[index].append(word)
            for index, ws in sorted(by_paragraph.items()):
                paragraph = shape.paragraphs[index]
                lines = _line_count(ws)
                if paragraph.bulleted and lines > limit:
                    message = f"a bullet in '{shape.label}' runs to {lines} lines, over {limit}"
                    out.append(finding(ctx, "OVS210", message, page.number, clip(paragraph.text)))
    return out


@rule(
    "OVS104",
    "low-contrast",
    "Text too close in tone to what is behind it",
    "render",
    explanation="Sampled from the rendered pixels, so it holds over images, gradients and theme colours "
    "the file never states as RGB. Thresholds follow WCAG 2.2 SC 1.4.3: 4.5:1 for body text, 3:1 for "
    "large text (at least 18pt, or 14pt bold). A word's size comes from the run it was set in; where the "
    "file doesn't say (table text, which inherits through the table style), it is measured from the "
    "render, erring small. Reported once per slide and threshold, listing the blocks. On a projector "
    "contrast is lower still.",
)
def low_contrast(ctx):
    from PIL import Image

    out, tol = [], ctx.settings.tolerance_emu
    for page in ctx.render.pages:
        shapes = ctx.deck.slides[page.number - 1].shapes if page.number <= len(ctx.deck.slides) else []
        large = dict(zip(map(id, page.words), _large_text(page.words, shapes, tol), strict=True))
        with Image.open(page.image) as im:
            image = im.convert("RGB")
            hits: dict[float, list[tuple[float, list]]] = defaultdict(list)
            for block in _by_block(page.words).values():
                # Large and body text in one block are held to different floors, so sample each on its own.
                for is_large in (False, True):
                    words = [w for w in block if large[id(w)] == is_large]
                    if not words:
                        continue
                    floor = ctx.settings.min_contrast_large if is_large else ctx.settings.min_contrast
                    ratio = sample_contrast(image, [w.box for w in words], page.dpi)
                    if ratio is not None and ratio < floor:
                        hits[floor].append((ratio, words))
        # A table or diagram can have dozens of low-contrast blocks: one finding per slide and floor.
        for floor, blocks in sorted(hits.items()):
            lowest = min(r for r, _ in blocks)
            if len(blocks) == 1:
                message = f"contrast {lowest:.1f}:1, under {floor:g}:1"
                snippet = _text(blocks[0][1])
            else:
                message = f"{len(blocks)} text blocks under {floor:g}:1, the lowest {lowest:.1f}:1"
                snippet = clip(" / ".join(" ".join(w.text for w in ws) for _, ws in blocks), 120)
            out.append(finding(ctx, "OVS104", message, page.number, snippet))
    return out


LARGE_PT, LARGE_BOLD_PT = 18.0, 14.0  # WCAG's "large scale" text
# A rendered word's box runs ascender to descender, about 1.2x its point size (measured on LibreOffice
# renders); dividing by a little more errs small, so a word of unknown size is never judged larger than it is.
BOX_PER_PT = 1.3
EMU_PER_PT = 12_700


def _large_text(words, shapes, tol) -> list[bool]:
    """Whether each rendered word is WCAG large text, from the run it belongs to:
    the word's frame, then the first run in that frame whose text holds it."""
    out = []
    for word, owner in zip(words, assign_owners(words, shapes, tol), strict=True):
        token = _token(word.text)
        run = next((r for r in owner.runs if token and token in _norm(r.text)), None) if owner else None
        size = run.size_pt if run is not None else None
        if size is None:
            size = word.box.h / EMU_PER_PT / BOX_PER_PT
        bold = bool(run and run.bold)
        out.append(size >= LARGE_PT - 0.05 or (bold and size >= LARGE_BOLD_PT - 0.05))
    return out
