"""Read a .pptx into what the rules need: geometry, text, fonts, colours.

Everything is in EMU (914,400 per inch), the unit the file itself uses, so a
rule never mixes units. Rendered positions (render.py) are converted into EMU
before any rule compares them with these frames.

python-pptx resolves a placeholder's position through its layout, but not its
font size or colour through the theme. Font sizes are resolved here, along
PowerPoint's inheritance chain (see `Styles`). Fonts and colours that are
inherited rather than stated are None, and the rules that need them skip that
run rather than guess.

Groups are flattened: each child becomes a Shape of its own, placed on the
slide through the group's transform, so a rule sees text and pictures inside
a group exactly as it sees them outside one. `group` keeps the outermost
group's name for messages.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.enum.dml import MSO_COLOR_TYPE, MSO_FILL
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn

EMU_PER_PT = 12_700

# Placeholders that are routinely left empty on purpose.
_QUIET_PLACEHOLDERS = {PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.SLIDE_NUMBER}


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def contains(self, other: Box, tolerance: int = 0) -> bool:
        return (
            other.x >= self.x - tolerance
            and other.y >= self.y - tolerance
            and other.right <= self.right + tolerance
            and other.bottom <= self.bottom + tolerance
        )

    def intersection(self, other: Box) -> int:
        w = min(self.right, other.right) - max(self.x, other.x)
        h = min(self.bottom, other.bottom) - max(self.y, other.y)
        return w * h if w > 0 and h > 0 else 0

    @property
    def area(self) -> int:
        return max(self.w, 0) * max(self.h, 0)


@dataclass
class Paragraph:
    text: str
    level: int  # 0-based outline level
    bulleted: bool  # shows a bullet or a number, stated or inherited
    emphasis: tuple[str, ...] = ()  # "bold", "italic", "all caps": set on every run of the paragraph


@dataclass
class Run:
    text: str
    size_pt: float | None  # effective: stated or inherited size times any shrink-on-overflow scale
    font: str | None
    color: str | None  # "RRGGBB", only when stated as RGB
    bold: bool = False  # only when stated
    italic: bool = False  # only when stated
    underline: bool = False  # only when stated
    link: bool = False  # a hyperlink or click action
    face: str | None = None  # the font actually used: stated or inherited, theme fonts resolved


@dataclass
class Shape:
    name: str
    kind: str  # "text" | "picture" | "table" | "other"
    box: Box | None
    text: str = ""
    runs: list[Run] = field(default_factory=list)
    fill: str | None = None
    placeholder: str | None = None  # the placeholder type's name, if a placeholder
    quiet_placeholder: bool = False
    auto_grow: bool = False  # the frame resizes to its text, so text past it is not overflow
    image_aspect: float | None = None  # pictures: aspect of the visible (cropped) source
    from_layout: bool = False  # drawn by the layout or master, not the slide
    group: str | None = None  # the outermost group this shape sits in, if any
    graphic: str | None = None  # a visual that needs alt text: "picture", "chart", "SmartArt graphic", "object"
    alt_text: str = ""  # the shape's description (cNvPr/@descr)
    decorative: bool = False  # marked decorative in PowerPoint, so it needs no alt text
    header_row: bool | None = None  # tables: the first row is marked as a header row
    paragraphs: list[Paragraph] = field(default_factory=list)  # text frames, non-empty paragraphs only

    @property
    def label(self) -> str:
        """The name a message uses: a child is named with its group, since
        names inside groups ("TextBox 3") repeat from card to card."""
        return f"{self.group} > {self.name}" if self.group else self.name


TITLE_PLACEHOLDERS = ("TITLE", "CENTER_TITLE")


@dataclass
class Slide:
    number: int  # 1-based
    layout: str
    shapes: list[Shape]
    hidden: bool = False  # hidden in the slide show

    @property
    def title(self) -> Shape | None:
        """The slide's title placeholder, if it has one."""
        return next((s for s in self.shapes if s.placeholder in TITLE_PLACEHOLDERS and not s.from_layout), None)

    @property
    def text_shapes(self) -> list[Shape]:
        return [s for s in self.shapes if s.text.strip()]

    @property
    def words(self) -> int:
        return sum(len(s.text.split()) for s in self.shapes if not s.from_layout)


@dataclass
class Section:
    name: str
    slides: list[int]  # 1-based slide numbers, in order


@dataclass
class Deck:
    path: Path
    width: int
    height: int
    slides: list[Slide]
    sections: list[Section] = field(default_factory=list)

    @property
    def frame(self) -> Box:
        return Box(0, 0, self.width, self.height)


def _rgb(color_format) -> str | None:
    try:
        if color_format.type == MSO_COLOR_TYPE.RGB:
            return str(color_format.rgb)
    except (AttributeError, TypeError):
        pass
    return None


def _fill(shape) -> str | None:
    try:
        if shape.fill.type == MSO_FILL.SOLID:
            return _rgb(shape.fill.fore_color)
    except (AttributeError, TypeError, NotImplementedError):
        pass
    return None


def _font_scale(text_frame) -> float:
    """PowerPoint's shrink-text-on-overflow stores its scale on the body; the
    sizes on the runs are the pre-shrink ones."""
    norm = text_frame._txBody.bodyPr.find(qn("a:normAutofit"))
    if norm is not None and norm.get("fontScale"):
        return int(norm.get("fontScale")) / 100_000
    return 1.0


# A transform from a shape's own coordinates to the slide's: x' = sx*x + tx.
Transform = tuple[float, float, float, float]  # sx, sy, tx, ty
IDENTITY: Transform = (1.0, 1.0, 0.0, 0.0)


def _box(shape, t: Transform = IDENTITY) -> Box | None:
    if shape.left is None or shape.top is None or shape.width is None or shape.height is None:
        return None
    sx, sy, tx, ty = t
    return Box(
        round(sx * shape.left + tx), round(sy * shape.top + ty), round(sx * shape.width), round(sy * shape.height)
    )


def _child_transform(group, outer: Transform) -> Transform:
    """Where a group's children land: the group maps its child extent
    (chOff, chExt) onto its own box (off, ext), and the result goes through
    the transform the group itself is under. Rotation and flips are ignored."""
    xfrm = group._element.grpSpPr.find(qn("a:xfrm"))
    ch_off = xfrm.find(qn("a:chOff")) if xfrm is not None else None
    ch_ext = xfrm.find(qn("a:chExt")) if xfrm is not None else None
    box = _box(group, outer)
    if ch_off is None or ch_ext is None or box is None:
        return outer
    cx, cy = int(ch_off.get("x")), int(ch_off.get("y"))
    cw, ch = int(ch_ext.get("cx")), int(ch_ext.get("cy"))
    sx = box.w / cw if cw else 1.0
    sy = box.h / ch if ch else 1.0
    return (sx, sy, box.x - sx * cx, box.y - sy * cy)


_TITLE_PLACEHOLDERS = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.VERTICAL_TITLE}


def _level_size(list_style, level: int) -> float | None:
    """The size a list style (a:lstStyle, p:titleStyle, ...) sets for a paragraph level, in points."""
    if list_style is None:
        return None
    lvl = list_style.find(qn(f"a:lvl{level + 1}pPr"))
    rpr = lvl.find(qn("a:defRPr")) if lvl is not None else None
    sz = rpr.get("sz") if rpr is not None else None
    return int(sz) / 100 if sz else None


class Styles:
    """The size a run inherits when it doesn't state one, by PowerPoint's chain:

    the shape's own list style -> the layout placeholder's -> the master
    placeholder's -> the master's title, body or other text style -> the
    presentation's default text style. A text box, not being a placeholder,
    goes straight from its own list style to the presentation default.
    A paragraph's own `a:pPr/a:defRPr` is not consulted. Table text has its
    own chain, through the table style, and is not resolved.
    """

    def __init__(self, prs):
        self.default = prs._element.find(qn("p:defaultTextStyle"))
        self._themes: dict[int, dict[str, str]] = {}

    def theme_fonts(self, master) -> dict[str, str]:
        """The master's theme fonts: '+mj-lt' (headings) and '+mn-lt' (body) to their typefaces."""
        if master is None:
            return {}
        if id(master) not in self._themes:
            fonts = {}
            try:
                theme = etree.fromstring(master.part.part_related_by(RT.THEME).blob)
                for key, tag in (("+mj-lt", "a:majorFont"), ("+mn-lt", "a:minorFont")):
                    latin = theme.find(f".//{qn('a:fontScheme')}/{qn(tag)}/{qn('a:latin')}")
                    if latin is not None and latin.get("typeface"):
                        fonts[key] = latin.get("typeface")
            except (KeyError, ValueError, etree.XMLSyntaxError):
                pass
            self._themes[id(master)] = fonts
        return self._themes[id(master)]

    @staticmethod
    def font(chain: list, level: int) -> str | None:
        """The Latin typeface a paragraph level inherits, as written (it may be a theme font)."""
        for list_style in chain:
            lvl = list_style.find(qn(f"a:lvl{level + 1}pPr")) if list_style is not None else None
            latin = lvl.find(f"{qn('a:defRPr')}/{qn('a:latin')}") if lvl is not None else None
            if latin is not None and latin.get("typeface"):
                return latin.get("typeface")
        return None

    def chain(self, shape, master) -> list:
        """The list styles to consult, nearest first."""
        styles = [shape.text_frame._txBody.find(qn("a:lstStyle"))]
        if not shape.is_placeholder:
            return [*styles, self.default]
        ph_type = shape.placeholder_format.type
        base = shape
        while True:
            try:
                base = base._base_placeholder
            except (AttributeError, NotImplementedError):
                break
            if base is None:
                break
            if getattr(base, "has_text_frame", False) and base.has_text_frame:
                styles.append(base.text_frame._txBody.find(qn("a:lstStyle")))
        tx_styles = master._element.find(qn("p:txStyles")) if master is not None else None
        if tx_styles is not None:
            if ph_type in _TITLE_PLACEHOLDERS:
                name = "p:titleStyle"
            elif ph_type in _QUIET_PLACEHOLDERS:  # date, footer, slide number
                name = "p:otherStyle"
            else:
                name = "p:bodyStyle"
            styles.append(tx_styles.find(qn(name)))
        return [*styles, self.default]

    @staticmethod
    def bulleted(chain: list, level: int) -> bool:
        """Whether a paragraph level shows a bullet or a number by inheritance: the
        nearest list style that says either way decides."""
        for list_style in chain:
            lvl = list_style.find(qn(f"a:lvl{level + 1}pPr")) if list_style is not None else None
            if lvl is None:
                continue
            for child in lvl:
                if child.tag == qn("a:buNone"):
                    return False
                if child.tag in _BULLET_TAGS:
                    return True
        return False

    @staticmethod
    def line_spacing(chain: list, level: int):
        """The `a:lnSpc` element a paragraph level inherits, or None (100%)."""
        for list_style in chain:
            lvl = list_style.find(qn(f"a:lvl{level + 1}pPr")) if list_style is not None else None
            spacing = lvl.find(qn("a:lnSpc")) if lvl is not None else None
            if spacing is not None:
                return spacing
        return None

    @staticmethod
    def size(chain: list, level: int) -> float | None:
        for list_style in chain:
            size = _level_size(list_style, level)
            if size is not None:
                return size
        return None


_BULLET_TAGS = {qn("a:buChar"), qn("a:buAutoNum"), qn("a:buBlip")}


def _caps(run) -> bool:
    rpr = run._r.rPr
    return rpr is not None and rpr.get("cap") == "all"


def _emphasis(paragraph, text: str) -> tuple[str, ...]:
    """The emphasis every run of a paragraph shares. All caps is the `cap="all"`
    option, or text typed in capitals."""
    runs = [r for r in paragraph.runs if r.text.strip()]
    out = []
    if runs and all(r.font.bold for r in runs):
        out.append("bold")
    if runs and all(r.font.italic for r in runs):
        out.append("italic")
    letters = [c for c in text if c.isalpha()]
    if runs and (all(_caps(r) for r in runs) or (len(letters) > 1 and all(c.isupper() for c in letters))):
        out.append("all caps")
    return tuple(out)


def _paragraphs(text_frame, chain: list | None) -> list[Paragraph]:
    out = []
    for paragraph in text_frame.paragraphs:
        text = "".join(r.text for r in paragraph.runs)
        if not text.strip():
            continue
        level = paragraph.level
        stated = paragraph._p.pPr
        bullet = None
        if stated is not None:
            for child in stated:
                if child.tag == qn("a:buNone"):
                    bullet = False
                elif child.tag in _BULLET_TAGS:
                    bullet = True
        if bullet is None:
            bullet = Styles.bulleted(chain, level) if chain else False
        out.append(Paragraph(text, level, bullet, _emphasis(paragraph, text)))
    return out


def _runs(text_frame, chain: list | None = None, theme: dict | None = None) -> list[Run]:
    scale = _font_scale(text_frame)
    theme = theme or {}
    runs = []
    for paragraph in text_frame.paragraphs:
        inherited = Styles.size(chain, paragraph.level) if chain else None
        inherited_font = (Styles.font(chain, paragraph.level) if chain else None) or "+mn-lt"
        for run in paragraph.runs:
            if not run.text.strip():
                continue
            stated = run.font.size.pt if run.font.size is not None else inherited
            size = stated * scale if stated is not None else None
            written = run.font.name or inherited_font
            rpr = run._r.rPr
            runs.append(
                Run(
                    run.text,
                    size,
                    run.font.name,
                    _rgb(run.font.color),
                    bool(run.font.bold),
                    italic=bool(run.font.italic),
                    underline=bool(run.font.underline),
                    link=rpr is not None and rpr.find(qn("a:hlinkClick")) is not None,
                    face=theme.get(written[:6], None) if written.startswith("+") else written,
                )
            )
    return runs


def _picture_aspect(picture) -> float | None:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(picture.image.blob)) as image:
            iw, ih = image.size
    except Exception:  # an unreadable or vector image: no aspect to compare
        return None
    visible_w = iw * (1 - picture.crop_left - picture.crop_right)
    visible_h = ih * (1 - picture.crop_top - picture.crop_bottom)
    if visible_w <= 0 or visible_h <= 0:
        return None
    return visible_w / visible_h


_GRAPHIC_DATA = {
    "http://schemas.openxmlformats.org/drawingml/2006/chart": "chart",
    "http://schemas.openxmlformats.org/drawingml/2006/diagram": "SmartArt graphic",
    "http://schemas.openxmlformats.org/presentationml/2006/ole": "object",
}
_DECORATIVE = "http://schemas.microsoft.com/office/drawing/2017/decorative"


def _graphic(element) -> str | None:
    """What kind of visual a shape element is, if it is one a reader needs described.
    Pictures include picture placeholders and video; a table is text, so it is not one."""
    if element.tag == qn("p:pic"):
        return "picture"
    if element.tag == qn("p:graphicFrame"):
        data = element.find(f"{qn('a:graphic')}/{qn('a:graphicData')}")
        return _GRAPHIC_DATA.get(data.get("uri")) if data is not None else None
    return None


def _description(element) -> tuple[str, bool]:
    """The shape's alt text, and whether PowerPoint marks it decorative."""
    cnvpr = element.find(f"./*/{qn('p:cNvPr')}")
    if cnvpr is None:
        return "", False
    decorative = any(el.get("val") in ("1", "true") for el in cnvpr.iter(f"{{{_DECORATIVE}}}decorative"))
    return cnvpr.get("descr") or "", decorative


def _shape(shape, from_layout=False, t: Transform = IDENTITY, group: str | None = None, ctx=None) -> Shape:
    kind = "other"
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        kind = "picture"
    elif getattr(shape, "has_table", False) and shape.has_table:
        kind = "table"
    elif shape.has_text_frame:
        kind = "text"

    out = Shape(name=shape.name, kind=kind, box=_box(shape, t), fill=_fill(shape), from_layout=from_layout, group=group)
    if shape.is_placeholder:
        ph_type = shape.placeholder_format.type
        out.placeholder = getattr(ph_type, "name", str(ph_type))
        out.quiet_placeholder = ph_type in _QUIET_PLACEHOLDERS
    if shape.has_text_frame:
        out.text = shape.text_frame.text
        styles, master = ctx or (None, None)
        chain = styles.chain(shape, master) if styles else None
        out.runs = _runs(shape.text_frame, chain, styles.theme_fonts(master) if styles else None)
        out.paragraphs = _paragraphs(shape.text_frame, chain)
        out.auto_grow = shape.text_frame.auto_size == MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
    elif kind == "table":
        out.header_row = bool(shape.table.first_row)
        cells = [c.text_frame for row in shape.table.rows for c in row.cells]
        out.text = "\n".join(c.text for c in cells)
        out.runs = [r for c in cells for r in _runs(c)]
    if kind == "picture":
        out.image_aspect = _picture_aspect(shape)
    out.graphic = _graphic(shape._element)
    if out.graphic:
        out.alt_text, out.decorative = _description(shape._element)
    return out


def _shapes(shapes, from_layout=False, t: Transform = IDENTITY, group: str | None = None, ctx=None) -> list[Shape]:
    """Shapes as the rules see them, with every group replaced by its children.
    `ctx` is (Styles, slide master), for resolving inherited sizes."""
    out = []
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            out += _shapes(shape.shapes, from_layout, _child_transform(shape, t), group or shape.name, ctx)
        else:
            out.append(_shape(shape, from_layout, t, group, ctx))
    return out


_P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"


def _sections(prs) -> list[Section]:
    """The deck's sections (PowerPoint 2010's p14:sectionLst), with the slides each holds."""
    number = {sld.get("id"): n for n, sld in enumerate(prs._element.sldIdLst, start=1)}
    out = []
    for section in prs._element.iter(f"{{{_P14}}}section"):
        ids = [s.get("id") for s in section.iter(f"{{{_P14}}}sldId")]
        out.append(Section(section.get("name") or "", [number[i] for i in ids if i in number]))
    return out


def load(path: str | Path) -> Deck:
    path = Path(path)
    prs = Presentation(str(path))
    slides, styles = [], Styles(prs)
    for number, slide in enumerate(prs.slides, start=1):
        ctx = (styles, slide.slide_layout.slide_master)
        shapes = _shapes(slide.shapes, ctx=ctx)
        # The layout and master draw text too -- a footer, a logo lockup -- and
        # a renderer's words have to be attributable to some frame.
        for inherited in (slide.slide_layout.shapes, slide.slide_layout.slide_master.shapes):
            shapes += _shapes([s for s in inherited if not s.is_placeholder], from_layout=True, ctx=ctx)
        hidden = slide._element.get("show") in ("0", "false")
        slides.append(Slide(number, slide.slide_layout.name, shapes, hidden))
    return Deck(path, int(prs.slide_width), int(prs.slide_height), slides, _sections(prs))
