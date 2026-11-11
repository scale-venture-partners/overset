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
    render = fake_render(
        [[word("Eight", 1, -0.6, 1, 0.5), word("of", 2.1, -0.6, 0.3, 0.5), word("companies", 1, 0.3, 2, 0.5, block=1)]]
    )
    (f,) = check("OVS001", deck, render)
    assert f.message == "text runs off the top of the slide" and f.snippet == "Eight of"


def test_each_edge_is_named(builder, make_deck, fake_render):
    builder.text("x")
    deck = make_deck(builder)
    render = fake_render(
        [
            [
                word("right", 13, 3, 1, 0.3, block=0),
                word("bottom", 3, 7.4, 1, 0.3, block=1),
                word("left", -0.5, 3, 1, 0.3, block=2),
            ]
        ]
    )
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


def test_dark_digits_on_a_dot_smaller_than_their_box_are_legible(builder, make_deck, fake_render):
    # The template's numbered markers: ink digits on a green dot, paper round the dot.
    def draw(n, image, dpi):
        d = ImageDraw.Draw(image)
        d.ellipse([1.05 * dpi, 1.0 * dpi, 1.45 * dpi, 1.4 * dpi], fill=(0, 199, 86))
        d.rectangle([1.17 * dpi, 1.1 * dpi, 1.33 * dpi, 1.3 * dpi], fill=(32, 33, 27))

    builder.text("01")
    render = fake_render([[word("01", 1.0, 1.0, 0.5, 0.4)]], color=(247, 245, 242), dpi=80, draw=draw)
    assert check("OVS104", make_deck(builder), render) == []


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


# -- collisions by ownership --------------------------------------------------


def test_frames_overflowing_into_each_other_collide_even_when_the_renderer_merges_them(builder, make_deck, fake_render):
    # Two questions stacked in fixed boxes, both overflowing: pdftotext puts
    # their interleaved lines in one block, so only the deck can tell them apart.
    builder.text("when they conflict which wins", x=8, y=3, w=4, h=0.4)
    builder.text("overset caught clipped titles", x=8, y=3.4, w=4, h=0.4)
    deck = make_deck(builder)
    a = word("conflict", 8.1, 3.55, 1, 0.26, block=6, line=0)
    b = word("overset", 8.1, 3.70, 1, 0.26, block=6, line=1)
    (f,) = check("OVS003", deck, fake_render([[a, b]]))
    assert "'TextBox 1' and 'TextBox 2' are drawn over each other" == f.message


def test_lines_of_one_frame_never_collide_with_each_other(builder, make_deck, fake_render):
    builder.text("one two", x=1, y=1, w=6, h=1)
    deck = make_deck(builder)
    render = fake_render([[word("one", 1.1, 1.1, 1, 0.3, block=0), word("two", 1.1, 1.2, 1, 0.3, block=1)]])
    assert check("OVS003", deck, render) == []


def test_a_word_that_overflowed_into_a_frame_sharing_it_is_still_its_own_frames(builder, make_deck, fake_render):
    # "rules" ends the title, wraps past its frame and lands inside the body's
    # box -- whose text also says "rules". Reading order, not geometry, says
    # whose word it is, and that it collides with the body's first line.
    builder.text("Case is invisible to phrase rules", x=1, y=1, w=5, h=0.4)
    builder.text("Two rules removed rather than shipped.", x=1, y=1.45, w=5, h=0.4)
    deck = make_deck(builder)
    words = [word(t, 1 + i * 0.7, 1.05, 0.6, 0.3, block=0) for i, t in enumerate("Case is invisible to phrase".split())]
    words += [
        word("rules", 1.0, 1.42, 0.6, 0.3, block=0, line=1),
        word("Two", 1.0, 1.47, 0.4, 0.3, block=1),
        word("rules", 1.5, 1.47, 0.6, 0.3, block=1),
        word("removed", 2.2, 1.47, 0.8, 0.3, block=1),
    ]
    render = fake_render([words])
    (spill,) = check("OVS002", deck, render)
    assert spill.message == "text spills out of 'TextBox 1'" and spill.snippet == "rules"
    (hit,) = check("OVS003", deck, render)
    assert hit.message == "'TextBox 1' and 'TextBox 2' are drawn over each other"


def test_a_row_of_cards_read_across_the_columns_keeps_each_word_in_its_card(builder, make_deck, fake_render):
    # pdftotext emits card 1's first line, then card 2's: "Instructions on how" then "A".
    # Card 1's text has an "a" a few words on, but card 2's "A" is not in card 1's column.
    builder.text("Instructions on how to build a chart.", x=1, y=4, w=1.6, h=1.5)
    builder.text("A typed Python API.", x=3, y=4, w=1.6, h=1.5)
    deck = make_deck(builder)
    words = [
        word("Instructions", 1.0, 4.1, 0.9, 0.25),
        word("on", 1.95, 4.1, 0.2, 0.25),
        word("how", 2.2, 4.1, 0.3, 0.25),
        word("A", 3.0, 4.1, 0.1, 0.25, block=1),
        word("typed", 3.15, 4.1, 0.4, 0.25, block=1),
        word("to", 1.0, 4.4, 0.2, 0.25),
        word("build", 1.25, 4.4, 0.4, 0.25),
        word("a", 1.7, 4.4, 0.1, 0.25),
    ]
    assert check("OVS002", deck, fake_render([words])) == []


def test_soffice_profile_is_an_absolute_file_uri_for_a_relative_workdir(tmp_path, monkeypatch):
    # A relative --keep-render once produced "file://out/lo-profile", which
    # LibreOffice reads as host "out"; it hung until the 180s timeout.
    from overset import render as render_mod

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(render_mod, "find_soffice", lambda: "soffice")
    calls = []

    def fake_run(cmd, env=None, timeout=180):
        calls.append(cmd)
        (tmp_path / "out" / "deck.pdf").write_bytes(b"%PDF")

    monkeypatch.setattr(render_mod, "_run", fake_run)
    (tmp_path / "out").mkdir()
    render_mod.to_pdf(tmp_path / "deck.pptx", render_mod.Path("out"))

    (flag,) = [a for a in calls[0] if a.startswith("-env:UserInstallation=")]
    uri = flag.split("=", 1)[1]
    assert uri == (tmp_path / "out" / "lo-profile").resolve().as_uri()
    assert uri.startswith("file:///")


def test_text_spilling_out_of_a_frame_inside_a_group_is_an_overflow(builder, make_deck, fake_render):
    # Before groups were flattened, the group's whole box was the frame, so a
    # card's text running into the card below it went unreported.
    card = builder.group()
    builder.text("Quarterly revenue grew", x=1, y=1, w=4, h=0.5, into=card)
    builder.text("Churn", x=1, y=3, w=4, h=0.5, into=card)
    card.name = "Card"
    deck = make_deck(builder)
    render = fake_render(
        [
            [
                word("Quarterly", 1, 1, 1.5, 0.4),
                word("revenue", 1, 1.6, 1.3, 0.4),
                word("grew", 1, 2.2, 0.8, 0.4),
                word("Churn", 1, 3, 1, 0.4, block=1),
            ]
        ]
    )
    (f,) = check("OVS002", deck, render)
    assert f.message == "text spills out of 'Card > TextBox 2'" and f.snippet == "revenue grew"


GREY = (138, 138, 138)  # about 3.4:1 on white: enough for large text, not for body text


def _grey_text(builder, make_deck, fake_render, size, bold=False):
    box = builder.text("Caption", size=size)
    box.text_frame.paragraphs[0].runs[0].font.bold = bold
    words = [[word("Caption", 1, 1, 2, 0.5)]]
    render = fake_render(words, color="white", dpi=60, draw=_paint(GREY, (1.2, 1.1, 0.6, 0.3)))
    return check("OVS104", make_deck(builder), render)


def test_the_grey_sits_between_the_two_wcag_thresholds():
    ratio = contrast_ratio(GREY, (255, 255, 255))
    assert 3.0 < ratio < 4.5


def test_body_text_needs_4_5_to_1(builder, make_deck, fake_render):
    (f,) = _grey_text(builder, make_deck, fake_render, size=16)
    assert f.message.endswith("under 4.5:1") and f.snippet == "Caption"


def test_large_text_needs_only_3_to_1(builder, make_deck, fake_render):
    assert _grey_text(builder, make_deck, fake_render, size=20) == []


def test_14pt_bold_is_large_text(builder, make_deck, fake_render):
    assert _grey_text(builder, make_deck, fake_render, size=14, bold=True) == []


def test_14pt_regular_is_body_text(builder, make_deck, fake_render):
    (f,) = _grey_text(builder, make_deck, fake_render, size=14)
    assert f.message.endswith("under 4.5:1")


def test_text_of_unknown_size_is_held_to_the_body_threshold(builder, make_deck, fake_render):
    builder.text("Something else")  # no frame owns the rendered word, so its size is unknown
    words = [[word("Caption", 1, 1, 2, 0.5)]]
    render = fake_render(words, color="white", dpi=60, draw=_paint(GREY, (1.2, 1.1, 0.6, 0.3)))
    (f,) = check("OVS104", make_deck(builder), render)
    assert f.message.endswith("under 4.5:1")


def test_the_large_text_threshold_is_configurable(builder, make_deck, fake_render):
    builder.text("Caption", size=20)
    words = [[word("Caption", 1, 1, 2, 0.5)]]
    render = fake_render(words, color="white", dpi=60, draw=_paint(GREY, (1.2, 1.1, 0.6, 0.3)))
    (f,) = check("OVS104", make_deck(builder), render, Settings(min_contrast_large=4.0))
    assert f.message.endswith("under 4:1")


def _all_pairs(inks, owners):
    """The original O(n^2) scan, as the reference colliding_pairs must match."""
    hits = {}
    for i in range(len(inks)):
        for j in range(i + 1, len(inks)):
            if owners[i] == owners[j]:
                continue
            overlap = inks[i].intersection(inks[j])
            if overlap and overlap > 0.05 * min(inks[i].area, inks[j].area):
                hits.setdefault(tuple(sorted((owners[i], owners[j]))), (i, j))
    return hits


def test_the_collision_sweep_finds_exactly_what_comparing_every_pair_finds():
    import random

    from overset.deck import Box
    from overset.rules.render_rules import colliding_pairs

    rng = random.Random(7)
    for _ in range(200):
        n = rng.randint(0, 60)
        # Small slide, big words: plenty of overlaps, ties in y, and touching edges.
        inks = [Box(rng.randint(0, 40), rng.randint(0, 40), rng.randint(1, 15), rng.randint(1, 8)) for _ in range(n)]
        owners = [rng.choice("ABCD") for _ in range(n)]
        assert colliding_pairs(inks, owners) == _all_pairs(inks, owners)
