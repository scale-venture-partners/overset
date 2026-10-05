"""Render a deck and measure where its text actually landed.

LibreOffice turns the .pptx into a PDF; poppler's `pdftotext -bbox-layout`
reports every word with its box, and `pdftoppm` rasterises each page. Words a
slide pushes past its edges are still reported -- with negative or oversized
coordinates -- which is what makes overflow measurable rather than guessed.

overset renders the deck itself instead of trusting a preview someone else
made: a preview can be stale, and it ties the linter to whichever tool made
the deck.

Needs LibreOffice (`soffice`) and poppler (`pdftotext`, `pdftoppm`) on PATH.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from overset.deck import Box, Deck

SOFFICE_CANDIDATES = ("soffice", "libreoffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice")
DEFAULT_DPI = 110


class RenderError(RuntimeError):
    """The deck could not be rendered; the render rules cannot run."""


@dataclass
class Word:
    text: str
    box: Box  # EMU, slide coordinates
    block: int  # pdftotext's layout block, roughly one text frame
    line: int  # a line within the block


@dataclass
class Page:
    number: int  # 1-based, one per slide
    words: list[Word]
    image: Path  # the rasterised slide
    dpi: int


@dataclass
class Render:
    pages: list[Page]
    workdir: Path
    contact_sheet: Path | None = None
    notes: list[str] = field(default_factory=list)


def find_soffice() -> str | None:
    for candidate in SOFFICE_CANDIDATES:
        found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if found:
            return found
    return None


def _font_env(font_dirs: list[Path], workdir: Path) -> dict:
    """Register extra font folders with fontconfig, so a deck renders in the
    face it was designed in. Without the brand fonts LibreOffice substitutes
    one with different metrics, and every measurement shifts."""
    env = {**os.environ, "SAL_USE_VCLPLUGIN": "svp"}
    dirs = [d for d in font_dirs if d.is_dir()]
    if dirs:
        conf = workdir / "fonts.conf"
        entries = "".join(f"  <dir>{escape(str(d.resolve()))}</dir>\n" for d in dirs)
        conf.write_text(
            '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
            f'{entries}  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
            f"  <cachedir>{escape(str(workdir / 'fontcache'))}</cachedir>\n</fontconfig>\n"
        )
        env["FONTCONFIG_FILE"] = str(conf)
    return env


def _run(cmd, env=None, timeout=180):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    except FileNotFoundError as e:
        raise RenderError(f"{cmd[0]} is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"{Path(cmd[0]).name} timed out after {timeout}s") from e
    if proc.returncode != 0:
        raise RenderError(f"{Path(cmd[0]).name} failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc


def to_pdf(pptx: Path, workdir: Path, font_dirs=()) -> Path:
    soffice = find_soffice()
    if soffice is None:
        raise RenderError("LibreOffice (soffice) is not installed")
    profile = workdir / "lo-profile"  # isolated, so a running LibreOffice doesn't block this one
    _run(
        [
            soffice,
            f"-env:UserInstallation=file://{profile}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(workdir),
            str(pptx),
        ],
        env=_font_env(list(font_dirs), workdir),
    )
    pdf = workdir / (pptx.stem + ".pdf")
    if not pdf.exists():
        raise RenderError("LibreOffice produced no PDF")
    return pdf


def parse_words(xhtml: str, deck: Deck) -> dict[int, tuple[float, float, list[Word]]]:
    """pdftotext's -bbox-layout output, per page: (width_pt, height_pt, words in EMU)."""
    root = ET.fromstring(xhtml)
    pages = {}
    for number, page in enumerate(root.iter("{http://www.w3.org/1999/xhtml}page"), start=1):
        width_pt, height_pt = float(page.get("width")), float(page.get("height"))
        sx, sy = deck.width / width_pt, deck.height / height_pt
        words = []
        for b, block in enumerate(page.iter("{http://www.w3.org/1999/xhtml}block")):
            for li, line in enumerate(block.iter("{http://www.w3.org/1999/xhtml}line")):
                for word in line.iter("{http://www.w3.org/1999/xhtml}word"):
                    x0, y0 = float(word.get("xMin")), float(word.get("yMin"))
                    x1, y1 = float(word.get("xMax")), float(word.get("yMax"))
                    box = Box(round(x0 * sx), round(y0 * sy), round((x1 - x0) * sx), round((y1 - y0) * sy))
                    words.append(Word(word.text or "", box, b, li))
        pages[number] = (width_pt, height_pt, words)
    return pages


_NORM_AUTOFIT = re.compile(r"<a:normAutofit\b([^>]*?)/>|<a:normAutofit\b([^>]*)>.*?</a:normAutofit>", re.S)
_TX_BODY = re.compile(r"<p:txBody>.*?</p:txBody>", re.S)


def _attr(attrs: str, name: str) -> int | None:
    m = re.search(rf'\b{name}="(\d+)"', attrs or "")
    return int(m.group(1)) if m else None


def _freeze_body(body: str) -> str:
    """One text body, with shrink-on-overflow replaced by what PowerPoint shows.

    PowerPoint stores the result of shrinking -- `fontScale`, `lnSpcReduction`
    -- and applies those stored values when it opens a file; it recomputes them
    only when someone edits the text. A bare `<a:normAutofit/>` therefore means
    100% in PowerPoint. LibreOffice instead recomputes the shrink every time it
    renders, so text that overflows in PowerPoint fits in LibreOffice. Freezing
    the stored values gives LibreOffice PowerPoint's layout to draw.
    """
    m = _NORM_AUTOFIT.search(body)
    if m is None:
        return body
    attrs = m.group(1) if m.group(1) is not None else m.group(2)
    scale = (_attr(attrs, "fontScale") or 100_000) / 100_000
    reduction = (_attr(attrs, "lnSpcReduction") or 0) / 100_000
    body = body[: m.start()] + "<a:noAutofit/>" + body[m.end() :]
    if scale != 1:
        body = re.sub(
            r'(<a:(?:rPr|endParaRPr|defRPr)\b[^>]*?\bsz=")(\d+)(")',
            lambda r: f"{r.group(1)}{max(100, round(int(r.group(2)) * scale))}{r.group(3)}",
            body,
        )
    if reduction:
        body = re.sub(
            r'(<a:lnSpc><a:spcPct val=")(\d+)(")',
            lambda r: f"{r.group(1)}{round(int(r.group(2)) * (1 - reduction))}{r.group(3)}",
            body,
        )
    return body


def as_powerpoint_shows_it(pptx: Path, out: Path) -> Path:
    """A copy of the deck whose text sits where PowerPoint would put it."""
    with zipfile.ZipFile(pptx) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if re.match(r"ppt/(slides|slideLayouts|slideMasters)/[^/]+\.xml$", item.filename):
                text = data.decode("utf-8")
                data = _TX_BODY.sub(lambda b: _freeze_body(b.group(0)), text).encode("utf-8")
            dst.writestr(item, data)
    return out


def render(
    deck: Deck,
    workdir: Path | None = None,
    font_dirs=(),
    dpi: int = DEFAULT_DPI,
    contact_sheet: bool = False,
    as_powerpoint: bool = True,
) -> Render:
    workdir = Path(workdir or tempfile.mkdtemp(prefix="overset-"))
    workdir.mkdir(parents=True, exist_ok=True)
    source = deck.path.resolve()
    if as_powerpoint:
        source = as_powerpoint_shows_it(source, workdir / source.name)
    pdf = to_pdf(source, workdir, font_dirs)

    xhtml = _run(["pdftotext", "-bbox-layout", str(pdf), "-"]).stdout
    words = parse_words(xhtml, deck)
    _run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(workdir / "slide")])
    images = sorted(workdir.glob("slide-*.png"))

    pages = []
    for number, image in enumerate(images, start=1):
        pages.append(Page(number, words.get(number, (0, 0, []))[2], image, dpi))
    result = Render(pages, workdir)
    if len(pages) != len(deck.slides):
        result.notes.append(f"rendered {len(pages)} pages for {len(deck.slides)} slides")
    if contact_sheet and pages:
        result.contact_sheet = make_contact_sheet([p.image for p in pages], workdir / "contact_sheet.png")
    return result


def make_contact_sheet(images: list[Path], out: Path, columns: int = 3, width: int = 640) -> Path:
    """Every slide in one image, labelled, for a whole-deck look."""
    from PIL import Image, ImageDraw

    thumbs = []
    for path in images:
        with Image.open(path) as im:
            ratio = width / im.width
            thumbs.append(im.convert("RGB").resize((width, round(im.height * ratio))))
    pad, label = 16, 22
    rows = (len(thumbs) + columns - 1) // columns
    cell_h = max(t.height for t in thumbs) + label
    sheet = Image.new("RGB", (columns * (width + pad) + pad, rows * (cell_h + pad) + pad), "white")
    draw = ImageDraw.Draw(sheet)
    for i, thumb in enumerate(thumbs):
        x = pad + (i % columns) * (width + pad)
        y = pad + (i // columns) * (cell_h + pad)
        draw.text((x, y), f"Slide {i + 1}", fill="black")
        sheet.paste(thumb, (x, y + label))
    sheet.save(out)
    return out
