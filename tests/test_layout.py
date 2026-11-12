"""Layout measures from shape boxes: alignment, balance, whitespace (#17)."""

from pptx.util import Inches

from overset.engine import Context
from overset.rules import load_rules
from overset.rules.base import REGISTRY
from overset.rules.layout import balance, whitespace
from overset.settings import Settings

load_rules()


def check(code, deck, settings=None):
    return REGISTRY[code].check(Context(deck, settings or Settings()))


def _grid(builder, jitter=0.0, stray=None):
    for row in range(2):
        for col in range(3):
            builder.text(f"Card {row}{col}", x=1 + 4 * col + (jitter if (row, col) == (1, 1) else 0), y=1 + 3 * row,
                         w=3, h=2)  # fmt: skip
    if stray:
        builder.text("Stray note", x=stray[0], y=stray[1], w=2, h=0.6)


def test_a_clean_grid_is_aligned(builder, make_deck):
    _grid(builder)
    assert check("OVS005", make_deck(builder)) == []


def test_a_one_pixel_jitter_within_tolerance_is_aligned(builder, make_deck):
    _grid(builder, jitter=3 / 72)  # 3pt: inside the 4pt alignment tolerance
    assert check("OVS005", make_deck(builder)) == []


def test_a_shape_off_the_grid_is_reported(builder, make_deck):
    _grid(builder, stray=(7.3, 6.5))  # lines up with no card
    (f,) = check("OVS005", make_deck(builder))
    assert f.message == "'TextBox 7' lines up with no other shape"


def test_a_near_miss_names_the_edge_it_missed(builder, make_deck):
    _grid(builder, jitter=8 / 72)  # 8pt off its column
    found = check("OVS005", make_deck(builder))
    # The jittered card still shares its top with its row, so it is aligned; nudge it off the row too.
    assert found == []
    builder.new_slide()
    for x, y in [(1, 1), (5, 1), (1, 4)]:
        builder.text(f"Box {x},{y}", x=x, y=y, w=3, h=2)
    builder.text("Slipped", x=5 + 6 / 72, y=4 + 0.5, w=3, h=1.4)  # 6pt off the right column's left edge
    (f,) = check("OVS005", make_deck(builder))
    assert f.slide == 2 and f.message == "'TextBox 4' is 6pt off the left edge of 'TextBox 2'"


def test_several_misaligned_shapes_are_one_finding_per_slide(builder, make_deck):
    _grid(builder, stray=(7.3, 6.5))
    builder.text("Another stray", x=0.2, y=0.2, w=0.5, h=0.3)
    (f,) = check("OVS005", make_deck(builder))
    assert f.message.startswith("2 shapes off the slide's alignment: 'TextBox 7' lines up with no other shape")


def test_balance_measure():
    from overset.deck import Box

    w, h = int(Inches(10)), int(Inches(5))
    square = int(Inches(1))
    left = Box(int(Inches(1)), int(Inches(2)), square, square)
    right = Box(int(Inches(8)), int(Inches(2)), square, square)
    assert balance([left, right], w, h) == 1.0
    assert balance([left], w, h) == 0.5  # all weight to the left; balanced top to bottom
    assert balance([left, Box(int(Inches(1)), int(Inches(0.5)), square, square)], w, h) < 0.5


def test_an_unbalanced_slide_is_reported_when_asked_for(builder, make_deck):
    builder.text("Everything", x=0.3, y=0.3, w=2, h=1)
    builder.text("crammed top left", x=0.3, y=1.5, w=2, h=1)
    deck = make_deck(builder)
    assert not REGISTRY["OVS006"].default
    (f,) = check("OVS006", deck)
    assert f.message.startswith("layout balance 0.0") and f.message.endswith("under 0.05")


def test_whitespace_and_a_crowded_slide(builder, make_deck):
    from overset.deck import Box

    w, h = int(Inches(10)), int(Inches(5))
    assert whitespace([Box(0, 0, w // 2, h)], w, h) == 0.5
    assert whitespace([Box(0, 0, w // 2, h), Box(0, 0, w // 2, h)], w, h) == 0.5, "overlaps count once"
    builder.text("Wall to wall", x=0.1, y=0.1, w=13.1, h=7.3)
    (f,) = check("OVS007", make_deck(builder))
    assert f.message.endswith("of the slide is empty, under 25%")


def test_a_background_picture_is_not_content(builder, make_deck):
    builder.picture(size=(1600, 900), x=0, y=0, w=13.333, h=7.5)
    builder.text("A short caption", x=1, y=1, w=4, h=1)
    assert check("OVS007", make_deck(builder)) == []
