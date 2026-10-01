"""Rules that measure a render. The render is constructed -- words at chosen
positions over a chosen image -- so each case pins one measurement without
LibreOffice; test_integration.py runs the real thing."""

from PIL import ImageDraw

from conftest import word
from overset.engine import Context
from overset.render import parse_words
from overset.rules import load_rules
from overset.rules.base import REGISTRY
from overset.rules.render_rules import contrast_ratio, fits, ink
from overset.settings import Settings

load_rules()


def check(code, deck, render, settings=None):
    return REGISTRY[code].check(Context(deck, settings or Settings(), render=render))


def test_words_past_the_top_are_off_the_slide(builder, make_deck, fake_render):
    builder.text("Eight of our 24 portfolio companies", y=0.2)
    deck = make_deck(builder)
    render = fake_render([[word("Eight", 1, -0.6, 1, 0.5), word("of", 2.1, -0.6, 0.3, 0.5),
                           word("companies", 1, 0.3, 2, 0.5, block=1)]])
    (f,) = check("OVS001", deck, render)
    assert f.message == "text runs off the top of the slide" and f.snippet == "Eight of"


def test_each_edge_is_named(builder, make_deck, fake_render):
    builder.text("x")
    deck = make_deck(builder)
    render = fake_render([[word("right", 13, 3, 1, 0.3, block=0), word("bottom", 3, 7.4, 1, 0.3, block=1),
                           word("left", -0.5, 3, 1, 0.3, block=2)]])
    assert sorted(f.message.split()[4] for f in check("OVS001", deck, render)) == ["bottom", "left", "right"]


def test_a_display_type_ascender_is_not_an_overflow(builder, make_deck, fake_render):
    # pdftotext boxes run from ascender to descender; a big title's box pokes
    # above its frame by about a fifth of its height on correct slides.
    builder.text("Portfolio", x=1, y=1, w=6, h=1.5, size=80)
    deck = make_deck(builder)
    render = fake_render([[word("Portfolio", 1.1, 0.75, 4, 1.3)]])
    assert check("OVS002", deck, render) == []


def test_a_line_below_its_frame_is_an_overflow(builder, make_deck, fake_render):
    builder.text("Up 42% year over year", x=1, y=4, w=3, h=0.4, size=14)
    deck = make_deck(builder)
    render = fake_render([[word("Up", 1.05, 4.05, 0.3, 0.25), word("year", 1.05, 4.6, 0.5, 0.25, line=1)]])
    (f,) = check("OVS002", deck, render)
    assert f.message == "text spills out of 'TextBox 1'" and f.snippet == "year"


def test_a_frame_that_grows_with_its_text_is_not_overflowing(builder, make_deck, fake_render):
    builder.text("A long paragraph", x=1, y=4, w=3, h=0.4, grow=True)
    deck = make_deck(builder)
    render = fake_render([[word("paragraph", 1.05, 5.5, 1, 0.3)]])
    assert check("OVS002", deck, render) == []


def test_words_no_frame_claims_are_left_alone(builder, make_deck, fake_render):
    builder.text("Title", x=1, y=1)
    deck = make_deck(builder)
    render = fake_render([[word("Q3", 9, 6, 0.4, 0.3)]])  # text drawn by a chart, say
    assert check("OVS002", deck, render) == []


def test_overlapping_ink_from_two_blocks_collides(builder, make_deck, fake_render):
    builder.text("Revenue", x=1, y=1)
    builder.text("Retention", x=1, y=1.1)
    deck = make_deck(builder)
    render = fake_render([[word("Revenue", 1, 1, 1.5, 0.5, block=0), word("Retention", 1.1, 1.1, 1.5, 0.5, block=1)]])
    (f,) = check("OVS003", deck, render)
    assert f.snippet == "Revenue / Retention"


def test_tightly_set_lines_do_not_collide(builder, make_deck, fake_render):
    # Metric boxes of an eyebrow and a title below it overlap; their ink doesn't.
    builder.text("Q3 REVIEW", x=1, y=1)
    deck = make_deck(builder)
    eyebrow = word("Q3", 1, 1.0, 1, 0.3, block=0)
    title = word("Portfolio", 1, 1.22, 4, 1.2, block=1)
    assert eyebrow.box.intersection(title.box) > 0
    assert check("OVS003", deck, fake_render([[eyebrow, title]])) == []


def test_words_in_one_block_never_collide(builder, make_deck, fake_render):
    builder.text("x")
    render = fake_render([[word("a", 1, 1, 1, 0.5), word("b", 1, 1, 1, 0.5)]])
    assert check("OVS003", make_deck(builder), render) == []


def _paint(fg, rect):
    def draw(n, image, dpi):
        x, y, w, h = rect
        ImageDraw.Draw(image).rectangle([x * dpi, y * dpi, (x + w) * dpi, (y + h) * dpi], fill=fg)
    return draw


def test_faint_text_is_low_contrast_and_dark_text_is_not(builder, make_deck, fake_render):
    builder.text("Source line")
    deck = make_deck(builder)
    words = [[word("Source", 1, 1, 2, 0.5)]]
    # Ink covering a third of the box, the rest background -- as glyphs do.
    faint = fake_render(words, color=(245, 244, 240), dpi=60, draw=_paint((205, 200, 190), (1.2, 1.1, 0.6, 0.3)))
    (f,) = check("OVS104", deck, faint)
    assert f.message.startswith("contrast 1.") and f.snippet == "Source"
    dark = fake_render(words, color=(245, 244, 240), dpi=60, draw=_paint((30, 30, 27), (1.2, 1.1, 0.6, 0.3)))
    assert check("OVS104", deck, dark) == []


def test_contrast_ratio_matches_wcag():
    assert round(contrast_ratio((0, 0, 0), (255, 255, 255)), 1) == 21.0
    assert contrast_ratio((119, 119, 119), (255, 255, 255)) > 4.4


def test_fits_and_ink_scale_with_the_word(builder):
    from overset.deck import Box

    frame = Box(0, 1000, 10_000, 1000)
    tall = word("T", 0, 0, 0.001, 0.001)
    tall.box = Box(0, 800, 100, 1000)  # 200 above the frame, 30% slack of 1000 is 300
    assert fits(frame, tall, 0)
    assert ink(tall).y > tall.box.y and ink(tall).h < tall.box.h


XHTML = """<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><body><doc>
<page width="960" height="540"><flow><block><line>
<word xMin="72" yMin="-36" xMax="144" yMax="12">Eight</word></line></block>
<block><line><word xMin="0" yMin="0" xMax="960" yMax="540">whole</word></line></block></flow></page>
</doc></body></html>"""


def test_pdftotext_boxes_are_converted_to_slide_emu(builder, make_deck):
    builder.text("x")
    deck = make_deck(builder)
    (width, height, words) = parse_words(XHTML, deck)[1]
    assert (width, height) == (960, 540)
    eight, whole = words
    assert eight.text == "Eight" and (eight.block, whole.block) == (0, 1)
    assert eight.box.y < 0, "off-page words keep their negative coordinates"
    assert whole.box.w == deck.width and whole.box.h == deck.height
