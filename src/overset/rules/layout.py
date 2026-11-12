"""Layout measures computed from shape boxes: alignment, balance and whitespace.

These follow Ngo, Teo & Byrne's (2003) interface aesthetics measures (moderate evidence) and the
verifiable layout rewards of AeSlides (2026, preprint). No study gives slide-specific thresholds,
so each rule is off by default and its threshold is a setting, chosen from the starter corpus's
distribution (docs/corpus.md) rather than from evidence; calibrating them is #20's job.

A shape counts when a screen reader would announce it -- text, or a visual that needs alt
text -- and it is the slide's own: footers, slide numbers and the template's shapes are left out.
"""

from __future__ import annotations

from overset.rules.base import finding, rule

EMU_PER_PT = 12_700
NEAR_MISS_PT = 12  # an edge this close to another, but not on it, looks like a slip


def _edges(box, axis: str) -> tuple[float, float, float]:
    if axis == "x":
        return box.x, box.x + box.w / 2, box.right
    return box.y, box.y + box.h / 2, box.bottom


BACKGROUND_SHARE = 0.8  # a picture covering this much of the slide is a background, not content


def _content(slide, deck=None) -> list:
    shapes = [s for s in slide.shapes if s.readable]
    if deck is not None:
        area = deck.width * deck.height
        shapes = [s for s in shapes if not (s.graphic and s.box.area >= BACKGROUND_SHARE * area)]
    return shapes


def _alignment_miss(s, others, tol):
    """None if one of the shape's edges lines up with another's within `tol`; else the nearest miss
    as (distance, other shape, edge name)."""
    best = None
    for axis, names in (("x", ("left edge", "centre", "right edge")), ("y", ("top", "middle", "bottom"))):
        mine = _edges(s.box, axis)
        for o in others:
            for name, a, b in zip(names, mine, _edges(o.box, axis), strict=True):
                d = abs(a - b)
                if d <= tol:
                    return None
                if best is None or d < best[0]:
                    best = (d, o, name)
    return best


@rule(
    "OVS005",
    "misaligned",
    "Shapes that line up with nothing else on the slide",
    "structure",
    default=False,
    explanation="A shape whose left, centre and right edges, and top, middle and bottom edges, all miss "
    "every other shape's by more than `align-tolerance-pt` (default 4pt) sits off any grid the slide has. "
    "Ngo, Teo & Byrne (2003) count distinct alignment lines; this names the shapes that add one, once per "
    "slide. When an edge misses another by under 12pt the message says so: that is usually a slip. Slides "
    "with fewer than three shapes are skipped. Off by default until calibrated.",
)
def misaligned(ctx):
    out, tol = [], ctx.settings.align_tolerance_pt * EMU_PER_PT
    for slide in ctx.deck.slides:
        shapes = _content(slide, ctx.deck)
        if len(shapes) < 3:
            continue
        misses = []
        for s in shapes:
            miss = _alignment_miss(s, [o for o in shapes if o is not s], tol)
            if miss is not None:
                misses.append((s, miss))
        if not misses:
            continue
        s, (d, other, edge) = misses[0]
        if d <= NEAR_MISS_PT * EMU_PER_PT:
            detail = f"'{s.label}' is {d / EMU_PER_PT:.0f}pt off the {edge} of '{other.label}'"
        else:
            detail = f"'{s.label}' lines up with no other shape"
        if len(misses) > 1:
            more = ", ".join(f"'{m.label}'" for m, _ in misses[1:4]) + (", ..." if len(misses) > 4 else "")
            detail = f"{len(misses)} shapes off the slide's alignment: {detail}; also {more}"
        out.append(finding(ctx, "OVS005", detail, slide.number))
    return out


def balance(boxes, width: int, height: int) -> float:
    """Ngo, Teo & Byrne's balance measure: 1 when the area-weighted moments either side of each
    centre line match, 0 when everything sits on one side."""
    cx, cy = width / 2, height / 2
    moments = {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0}
    for b in boxes:
        mx, my = b.x + b.w / 2, b.y + b.h / 2
        moments["left" if mx < cx else "right"] += b.area * abs(mx - cx)
        moments["top" if my < cy else "bottom"] += b.area * abs(my - cy)

    def skew(a: float, b: float) -> float:
        return abs(a - b) / max(a, b) if max(a, b) else 0.0

    return 1 - (skew(moments["left"], moments["right"]) + skew(moments["top"], moments["bottom"])) / 2


@rule(
    "OVS006",
    "unbalanced-layout",
    "Content weighted heavily to one side of the slide",
    "structure",
    default=False,
    explanation="Ngo, Teo & Byrne's (2003) balance measure over the slide's content -- the title left out, "
    "as it sits at the top by design, and background pictures: each shape's area times its distance from "
    "the centre line, "
    "compared left against right and top against bottom. 1 is balanced, 0 is everything on one side. "
    "Reported under `min-balance`. Off by default until calibrated.",
)
def unbalanced_layout(ctx):
    out, floor = [], ctx.settings.min_balance
    for slide in ctx.deck.slides:
        boxes = [s.box for s in _content(slide, ctx.deck) if s is not slide.title]
        if len(boxes) < 2:
            continue
        score = balance(boxes, ctx.deck.width, ctx.deck.height)
        if score < floor:
            out.append(finding(ctx, "OVS006", f"layout balance {score:.2f}, under {floor:g}", slide.number))
    return out


GRID = 200  # cells across the slide when measuring covered area


def whitespace(boxes, width: int, height: int) -> float:
    """The share of the slide no box covers, on a grid of GRID cells across."""
    rows = max(1, round(GRID * height / width))
    covered = [[False] * GRID for _ in range(rows)]
    for b in boxes:
        x0, x1 = max(0, int(b.x / width * GRID)), min(GRID, int(-(-b.right * GRID // width)))
        y0, y1 = max(0, int(b.y / height * rows)), min(rows, int(-(-b.bottom * rows // height)))
        for r in range(y0, y1):
            covered[r][x0:x1] = [True] * max(0, x1 - x0)
    return 1 - sum(map(sum, covered)) / (GRID * rows)


@rule(
    "OVS007",
    "crowded-slide",
    "Too little empty space on the slide",
    "structure",
    default=False,
    explanation="The share of the slide no text or visual covers. AeSlides (2026, preprint) scores "
    "whitespace as a verifiable layout quality; no study gives a slide threshold. Reported under "
    "`min-whitespace`. A picture covering 80% of the slide or more is a background and does not count. Off by "
    "default until calibrated.",
)
def crowded_slide(ctx):
    out, floor = [], ctx.settings.min_whitespace
    for slide in ctx.deck.slides:
        boxes = [s.box for s in _content(slide, ctx.deck)]
        if not boxes:
            continue
        share = whitespace(boxes, ctx.deck.width, ctx.deck.height)
        if share < floor:
            out.append(finding(ctx, "OVS007", f"{share:.0%} of the slide is empty, under {floor:.0%}", slide.number))
    return out
