"""Check that a .pptx is a well-formed Open Packaging file before reading it.

A deck whose package is broken -- a part with no content type, a relationship
to a part that isn't there, XML that doesn't parse -- is one PowerPoint offers
to "repair" when it opens, and one python-pptx refuses to load at all. That is
a defect in the deck, so it is reported as findings, not as overset failing.

Seen in practice: a deck generator copied a `.jpg` picture into ppt/media/
without registering the `jpg` extension (the template only listed `jpeg`).
PowerPoint asked to repair the deck; every linter that opened it crashed.

stdlib only, so it runs on a file nothing else can open.
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _rels_base(rels_name: str) -> str:
    """'ppt/slides/_rels/slide1.xml.rels' -> 'ppt/slides' (the folder its targets resolve from)."""
    return posixpath.dirname(posixpath.dirname(rels_name))


class NotAPackage(ValueError):
    """The file isn't a zip at all -- a file error, not a defect in a deck."""


def check(path: str | Path) -> list[str]:
    """Every problem found in the package, as one sentence each. Empty means sound.

    Raises NotAPackage when the file isn't a zip: a PowerPoint lock file
    (`~$deck.pptx`), or something that was never a deck, is a usage error.
    """
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise NotAPackage(f"not a .pptx (zip) file: {e}") from e
    with z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        parts = set(names)
        problems = []
        if "[Content_Types].xml" not in parts:
            return ["[Content_Types].xml is missing, so no part has a content type"]

        parsed = {}
        for name in names:
            if name.endswith((".xml", ".rels")):
                try:
                    parsed[name] = ET.fromstring(z.read(name))
                except ET.ParseError as e:
                    problems.append(f"{name} is not well-formed XML ({e})")

        types = parsed.get("[Content_Types].xml")
        if types is None:
            return problems
        defaults = {d.get("Extension", "").lower() for d in types.iter(f"{CT_NS}Default")}
        overrides = {o.get("PartName", "") for o in types.iter(f"{CT_NS}Override")}
        for name in names:
            if name == "[Content_Types].xml" or f"/{name}" in overrides:
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in defaults:
                problems.append(f"{name} has no content type: no <Default Extension=\"{ext}\"> or <Override> "
                                f"in [Content_Types].xml")
        for part in sorted(overrides):
            if part.lstrip("/") not in parts:
                problems.append(f"[Content_Types].xml declares {part}, which is not in the package")

        for name, root in parsed.items():
            if not name.endswith(".rels"):
                continue
            base = _rels_base(name)
            for rel in root.iter(f"{REL_NS}Relationship"):
                if rel.get("TargetMode") == "External":
                    continue
                target = rel.get("Target", "")
                resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                    posixpath.join(base, target))
                if resolved not in parts:
                    problems.append(f"{name} points {rel.get('Id')} at {target}, which is not in the package")
        return problems


def fix_hint(problem: str) -> str:
    """What to do about one problem, when there is a usual cause."""
    m = re.search(r"has no content type: no <Default Extension=\"(\w+)\">", problem)
    if m and m.group(1) in ("jpg", "jpe", "tif", "gif", "bmp"):
        return (f"a .{m.group(1)} picture was added without registering its type; save the picture as .png or "
                ".jpeg before adding it, or register the extension")
    return ""
