"""Measured counterparts for the vision rules (#18), on constructed decks and renders."""

import random

from PIL import Image, ImageDraw

from conftest import word
from overset.engine import Context
from overset.rules import load_rules
from overset.rules.base import REGISTRY
from overset.rules.measured import edge_density
from overset.settings import Settings

load_rules()


def check(code, deck, render=None, settings=None):
    return REGISTRY[code].check(Context(deck, settings or Settings(), render=render))


def _noise(box_inches=None, seed=0):
    """A draw callback that paints random black and white blocks, over the whole page or a box."""

    def draw(n, image, dpi):
        rng = random.Random(seed + n)
        d = ImageDraw.Draw(image)
        x0, y0, x1, y1 = (0, 0, image.width, image.height) if box_inches is None else (
            int(v * dpi) for v in box_inches
        )  # fmt: skip
        for x in range(x0, x1, 4):
            for y in range(y0, y1, 4):
                if rng.random() < 0.5:
                    d.rectangle([x, y, x + 3, y + 3], fill="black")

    return draw


def test_edge_density():
    blank = Image.new("RGB", (400, 225), "white")
    assert edge_density(blank) == 0
    busy = blank.copy()
    _noise()(1, busy, 30)
    assert edge_density(busy) > 0.15


def test_a_slide_far_busier_than_its_deck_is_cluttered(builder, make_deck, fake_render):
    for i in range(6):
        builder.new_slide()
        builder.text(f"Slide {i}")
    deck = make_deck(builder)

    def draw(n, image, dpi):
        ImageDraw.Draw(image).rectangle([40, 40, 200, 80], fill="black")  # a little content on every slide
        if n == 4:
            _noise()(n, image, dpi)

    render = fake_render([[] for _ in range(6)], dpi=30, draw=draw)
    assert not REGISTRY["OVS008"].default
    (f,) = check("OVS008", deck, render)
    assert f.slide == 4 and f.message.startswith("edge density")


def test_a_short_deck_is_not_judged_against_itself(builder, make_deck, fake_render):
    builder.text("One")
    builder.new_slide()
    builder.text("Two")
    render = fake_render([[], []], dpi=30, draw=lambda n, im, dpi: _noise()(n, im, dpi) if n == 2 else None)
    assert check("OVS008", make_deck(builder), render) == []


def test_text_over_a_busy_background(builder, make_deck, fake_render):
    builder.text("Over a photo", x=1, y=1, w=4, h=1.5)
    builder.text("Over plain paper", x=7, y=1, w=4, h=1.5)
    words = [[word("Over", 1.2, 1.2, 0.6, 0.3), word("Over", 7.2, 1.2, 0.6, 0.3, block=1)]]
    render = fake_render(words, dpi=40, draw=_noise(box_inches=(1, 1, 5, 2.5)))
    (f,) = check("OVS009", make_deck(builder), render)
    assert f.message.startswith("busy background behind 'TextBox 1'")


def _titled(builder, title, title_pt, body_pt=None, font=None):
    from pptx.util import Pt

    slide = builder.new_slide(layout=5)
    slide.shapes.title.text = title
    slide.shapes.title.text_frame.paragraphs[0].runs[0].font.size = Pt(title_pt)
    if body_pt:
        builder.text("Body", y=3, size=body_pt, font=font)
    return slide


def test_body_text_as_large_as_the_title(builder, make_deck):
    _titled(builder, "Revenue", 24, body_pt=40)
    _titled(builder, "Costs", 40, body_pt=24)
    _titled(builder, "Margin", 28, body_pt=28)  # equal: not larger, so weak
    found = check("OVS111", make_deck(builder))
    assert [(f.slide, f.message) for f in found] == [
        (1, "title at 24pt, other text at 40pt"),
        (3, "title at 28pt, other text at 28pt"),
    ]


def test_a_slide_in_another_style(builder, make_deck):
    for i in range(5):
        _titled(builder, f"Slide {i}", 40, body_pt=20)
    _titled(builder, "Pasted in from another deck", 54, body_pt=20, font="Comic Sans MS")
    messages = [(f.slide, f.message) for f in check("OVS112", make_deck(builder))]
    assert messages == [
        (6, "uses Comic Sans MS, which no other slide does"),
        (6, "title at 54pt, against the deck's usual 40pt"),
    ]
