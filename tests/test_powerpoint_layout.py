"""Rendering as PowerPoint shows a deck, not as LibreOffice would.

PowerPoint applies a shrink-on-overflow box's *stored* scale when it opens a
file; a bare <a:normAutofit/> is 100%. LibreOffice recomputes the shrink on
every render. Text that fits in LibreOffice can overflow in PowerPoint -- the
deck an audience sees -- so overset freezes the stored values before it
renders."""

import zipfile

from conftest import needs_libreoffice
from overset.engine import lint
from overset.render import _freeze_body, as_powerpoint_shows_it
from overset.settings import Settings

BODY = (
    '<p:txBody><a:bodyPr wrap="square">{fit}</a:bodyPr><a:p><a:pPr><a:lnSpc><a:spcPct val="135000"/>'
    '</a:lnSpc></a:pPr><a:r><a:rPr lang="en-US" sz="1400"/><a:t>x</a:t></a:r>'
    '<a:endParaRPr sz="1400"/></a:p></p:txBody>'
)


def test_a_bare_shrink_is_frozen_at_full_size():
    out = _freeze_body(BODY.format(fit="<a:normAutofit/>"))
    assert "<a:noAutofit/>" in out and "normAutofit" not in out
    assert 'sz="1400"' in out and 'val="135000"' in out


def test_a_stored_scale_is_applied_to_sizes_and_spacing():
    out = _freeze_body(BODY.format(fit='<a:normAutofit fontScale="75000" lnSpcReduction="20000"/>'))
    assert out.count('sz="1050"') == 2, "runs and the end-of-paragraph size both shrink"
    assert 'val="108000"' in out


def test_bodies_without_shrink_are_left_alone():
    for fit in ("", "<a:noAutofit/>", "<a:spAutoFit/>"):
        body = BODY.format(fit=fit)
        assert _freeze_body(body) == body


def test_the_copy_freezes_slides_and_leaves_everything_else(builder, tmp_path):
    builder.text("x")
    src = builder.save(tmp_path / "deck.pptx")
    out = as_powerpoint_shows_it(src, tmp_path / "frozen.pptx")
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
        assert a.namelist() == b.namelist()
        assert a.read("ppt/presentation.xml") == b.read("ppt/presentation.xml")


@needs_libreoffice
def test_text_that_only_fits_because_libreoffice_shrinks_it_is_caught(builder, tmp_path):
    from pptx.oxml.ns import qn

    box = builder.text(
        "Who outranks whom? A banned phrase, a compliance rule, a user's verbatim request: "
        "when they conflict, which wins?",
        x=8,
        y=3,
        w=3.6,
        h=0.6,
        size=14,
    )
    body = box.text_frame._txBody.bodyPr
    for child in list(body):
        body.remove(child)
    body.append(body.makeelement(qn("a:normAutofit"), {}))
    deck = builder.save(tmp_path / "deck.pptx")

    as_libreoffice = lint(deck, Settings(render_as="libreoffice", select=("OVS002",)))
    as_powerpoint = lint(deck, Settings(select=("OVS002",)))
    assert as_libreoffice.findings == [], "LibreOffice shrinks it to fit"
    assert [f.code for f in as_powerpoint.findings] == ["OVS002"], "PowerPoint shows it at full size"


def _shrunk_body(builder, paragraphs, font_scale):
    """A content placeholder whose text inherits its size (32pt, from the master's
    bodyStyle), stored as shrunk to `font_scale` percent, the way PowerPoint saves it."""
    from pptx.oxml.ns import qn

    slide = builder.new_slide(layout=1)
    slide.shapes.title.text = "A title"
    body = slide.placeholders[1]
    tf = body.text_frame
    tf.text = paragraphs[0]
    for text in paragraphs[1:]:
        tf.add_paragraph().text = text
    body_pr = tf._txBody.bodyPr
    for child in list(body_pr):
        body_pr.remove(child)
    body_pr.append(body_pr.makeelement(qn("a:normAutofit"), {"fontScale": str(round(font_scale * 1000))}))
    return body


def test_an_inherited_size_is_stated_and_then_scaled(builder, tmp_path):
    _shrunk_body(builder, ["First point", "Second point"], font_scale=62.5)
    src = builder.save(tmp_path / "deck.pptx")
    out = as_powerpoint_shows_it(src, tmp_path / "frozen.pptx")
    with zipfile.ZipFile(out) as z:
        slide = z.read("ppt/slides/slide1.xml").decode()
    body = slide[slide.index("First point") - 400 :]
    assert "normAutofit" not in slide
    # 32pt inherited x 62.5% = 20pt, on both runs and both end-of-paragraph marks
    assert body.count('sz="2000"') == 4, body
    assert 'sz="3200"' not in slide


@needs_libreoffice
def test_inherited_text_that_powerpoint_shrank_is_not_a_false_overflow(builder, tmp_path):
    # Ten 32pt lines don't fit the content placeholder; at the stored 50% they do.
    _shrunk_body(builder, [f"Point number {i}" for i in range(1, 11)], font_scale=50)
    deck = builder.save(tmp_path / "deck.pptx")
    assert lint(deck, Settings(select=("OVS002",))).findings == []
