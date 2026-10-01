"""The real pipeline: LibreOffice, pdftotext, pdftoppm. Skipped where they
aren't installed; CI installs them."""

from conftest import needs_libreoffice
from overset import cli
from overset.engine import lint
from overset.settings import Settings


@needs_libreoffice
def test_a_title_pushed_off_the_top_is_caught_end_to_end(builder, tmp_path):
    builder.text("A title running off the top", x=1, y=-0.6, w=8, h=1.2, size=40)
    builder.text("Clean body copy that fits its frame.", x=1, y=3, w=8, h=1, size=20)
    result = lint(builder.save(tmp_path / "deck.pptx"), Settings(), workdir=tmp_path / "render")
    codes = sorted({f.code for f in result.findings})
    assert codes == ["OVS001", "OVS004"]
    off = next(f for f in result.findings if f.code == "OVS001")
    assert "top" in off.message and "running off the top" in off.snippet
    assert result.rendered and (tmp_path / "render" / "slide-1.png").exists()


@needs_libreoffice
def test_a_fixed_frame_too_small_for_its_text_overflows(builder, tmp_path):
    builder.text("This body text is far too long for its small fixed box and spills well past the bottom",
                 x=1, y=3, w=2, h=0.5, size=20)
    result = lint(builder.save(tmp_path / "deck.pptx"), Settings())
    assert [f.code for f in result.findings] == ["OVS002"]


@needs_libreoffice
def test_a_clean_deck_is_clean_and_the_contact_sheet_is_made(builder, tmp_path, capsys):
    builder.text("Efficiency is the scarce input", x=1, y=1, w=10, h=1.2, size=36)
    builder.text("Median burn multiple fell from 2.1x to 1.4x.", x=1, y=3, w=10, h=1, size=20)
    builder.new_slide()
    builder.text("Second slide", x=1, y=1, w=6, h=1, size=36)
    deck = builder.save(tmp_path / "deck.pptx")
    assert cli.main([str(deck), "--keep-render", str(tmp_path / "r")]) == 0
    assert "All clear" in capsys.readouterr().out

    from overset import deck as deck_mod
    from overset import render as render_mod

    r = render_mod.render(deck_mod.load(deck), tmp_path / "r2", contact_sheet=True)
    assert len(r.pages) == 2 and r.contact_sheet.exists()
