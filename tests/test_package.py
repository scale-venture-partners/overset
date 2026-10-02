"""The package check: what PowerPoint would offer to repair, found before anything loads the deck."""

import zipfile

import pytest

from overset import package
from overset.engine import lint
from overset.settings import Settings


def rewrite(src, dst, *, drop=(), replace=None, add=None):
    """Copy a .pptx, dropping parts, editing some, adding others."""
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as b:
        for item in a.infolist():
            if item.filename in drop:
                continue
            data = a.read(item.filename)
            if replace and item.filename in replace:
                data = replace[item.filename](data.decode()).encode()
            b.writestr(item.filename, data)
        for name, data in (add or {}).items():
            b.writestr(name, data)
    return dst


@pytest.fixture
def sound(builder, tmp_path):
    builder.text("A slide title for one slide", size=32)
    return builder.save(tmp_path / "sound.pptx")


def test_a_deck_python_pptx_wrote_is_sound(sound):
    assert package.check(sound) == []


def test_a_part_with_no_content_type_is_the_repair_prompt(sound, tmp_path):
    broken = rewrite(sound, tmp_path / "jpg.pptx", add={"ppt/media/image9.jpg": b"\xff\xd8"})
    (problem,) = package.check(broken)
    assert problem.startswith('ppt/media/image9.jpg has no content type: no <Default Extension="jpg">')
    assert "save the picture as .png or .jpeg" in package.fix_hint(problem)
    assert package.fix_hint("something else") == ""


def test_a_relationship_to_a_missing_part_and_a_stale_override(sound, tmp_path):
    broken = rewrite(sound, tmp_path / "rel.pptx", drop=("ppt/slides/slide1.xml",))
    problems = package.check(broken)
    assert any("declares /ppt/slides/slide1.xml, which is not in the package" in p for p in problems)
    assert any("points rId" in p and "slides/slide1.xml, which is not in the package" in p for p in problems)


def test_xml_that_does_not_parse(sound, tmp_path):
    broken = rewrite(sound, tmp_path / "xml.pptx", replace={"ppt/slides/slide1.xml": lambda x: x[:-20]})
    assert any(p.startswith("ppt/slides/slide1.xml is not well-formed XML") for p in package.check(broken))


def test_not_a_zip_and_no_content_types(sound, tmp_path):
    (tmp_path / "lock.pptx").write_bytes(b"\x00owner-file")
    with pytest.raises(package.NotAPackage, match="not a .pptx"):
        package.check(tmp_path / "lock.pptx")
    bare = rewrite(sound, tmp_path / "bare.pptx", drop=("[Content_Types].xml",))
    assert package.check(bare) == ["[Content_Types].xml is missing, so no part has a content type"]


def test_an_unloadable_deck_is_a_finding_not_a_crash(sound, tmp_path):
    broken = rewrite(sound, tmp_path / "jpg.pptx", add={"ppt/media/image9.jpg": b"\xff\xd8"},
                     replace={"ppt/slides/_rels/slide1.xml.rels": lambda x: x.replace(
                         "</Relationships>", '<Relationship Id="rId99" Type="http://schemas.openxmlformats.org/'
                         'officeDocument/2006/relationships/image" Target="../media/image9.jpg"/></Relationships>')})
    result = lint(broken, Settings(render=False))
    assert [f.code for f in result.findings] == ["OVS000"] and result.findings[0].slide is None
    assert "could not be loaded" in result.notes[0] and "so no other rule ran" in result.notes[0]


def test_a_loadable_deck_with_a_package_problem_still_gets_every_rule(builder, tmp_path):
    builder.text("Fine print", size=6)
    src = builder.save(tmp_path / "d.pptx")
    stale = rewrite(src, tmp_path / "stale.pptx", replace={"[Content_Types].xml": lambda x: x.replace(
        "</Types>", '<Override PartName="/ppt/ghost.xml" ContentType="application/xml"/></Types>')})
    codes = sorted(f.code for f in lint(stale, Settings(render=False)).findings)
    assert codes == ["OVS000", "OVS101"]


def test_the_package_rule_can_be_ignored(sound, tmp_path):
    broken = rewrite(sound, tmp_path / "jpg.pptx", add={"ppt/media/image9.jpg": b"\xff\xd8"})
    assert lint(broken, Settings(render=False, ignore=("OVS000",))).findings == []
