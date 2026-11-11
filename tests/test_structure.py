"""Rules that read only the .pptx."""

from pptx.util import Inches, Pt

from overset.deck import Box
from overset.engine import Context
from overset.rules import load_rules
from overset.rules.base import REGISTRY
from overset.settings import Settings

load_rules()


def check(code, deck, settings=None):
    return REGISTRY[code].check(Context(deck, settings or Settings()))


def test_a_text_frame_past_the_edge_is_reported_and_one_inside_is_not(builder, make_deck):
    builder.text("Inside", x=1, y=1)
    builder.text("Past the top", x=1, y=-0.5)
    (f,) = check("OVS004", make_deck(builder))
    assert f.slide == 1 and f.snippet == "Past the top" and "extends past" in f.message


def test_pictures_may_bleed_off_the_edge(builder, make_deck):
    builder.picture(x=-1, y=-1, w=15, h=9)
    assert check("OVS004", make_deck(builder)) == []


def test_small_text_is_reported_at_its_effective_size(builder, make_deck):
    builder.text("Fine print", size=8)
    builder.text("Body", y=3, size=18)
    (f,) = check("OVS101", make_deck(builder))
    assert f.message == "text at 8.0pt, under 10pt" and f.snippet == "Fine print"


def test_shrink_to_fit_counts_against_the_floor(builder, make_deck):
    from pptx.oxml.ns import qn

    box = builder.text("Shrunk", size=14)
    body = box.text_frame._txBody.bodyPr
    for child in list(body):
        body.remove(child)
    norm = body.makeelement(qn("a:normAutofit"), {"fontScale": "62500"})
    body.append(norm)
    (f,) = check("OVS101", make_deck(builder))
    assert "8.8pt" in f.message, "14pt shown at 62.5% is 8.75pt"


def test_fonts_are_only_checked_once_a_brand_set_is_configured(builder, make_deck):
    builder.text("Comic", font="Comic Sans MS")
    builder.text("Brand", y=3, font="Inter")
    deck = make_deck(builder)
    assert check("OVS102", deck) == []
    (f,) = check("OVS102", deck, Settings(fonts=["Inter", "Lora"]))
    assert "Comic Sans MS" in f.message


def test_a_weight_of_a_brand_font_is_the_brand_font(builder, make_deck):
    builder.text("Medium", font="Inter Medium")
    builder.text("Bold", y=2, font="Inter-Bold")
    builder.text("Sans", y=3, font="Interstate")
    (f,) = check("OVS102", make_deck(builder), Settings(fonts=["Inter"]))
    assert "Interstate" in f.message


def test_theme_fonts_pass_the_brand_check(builder, make_deck):
    builder.text("Theme", font="+mn-lt")
    assert check("OVS102", make_deck(builder), Settings(fonts=["Inter"])) == []


def test_colours_off_the_palette_are_reported_within_a_tolerance(builder, make_deck):
    builder.text("Brand green", color="00C853")
    builder.text("Nearly green", y=2, color="02C955")
    builder.text("Purple", y=3, color="8E24AA")
    deck = make_deck(builder)
    assert check("OVS103", deck) == []
    (f,) = check("OVS103", deck, Settings(palette=["00C853", "#1F1F1B"]))
    assert f.message == "#8E24AA is not in the brand palette"


def test_a_solid_fill_off_the_palette_is_reported(builder, make_deck):
    box = builder.text("x", color="1F1F1B")
    box.fill.solid()
    from pptx.dml.color import RGBColor

    box.fill.fore_color.rgb = RGBColor.from_string("FF00FF")
    (f,) = check("OVS103", make_deck(builder), Settings(palette=["1F1F1B"]))
    assert "FF00FF" in f.message and "fill of" in f.snippet


def test_an_empty_placeholder_is_reported_and_an_empty_title_only_once(builder, make_deck):
    builder.new_slide(layout=1)  # title and content, both left empty
    deck = make_deck(builder)
    (body,) = check("OVS201", deck, Settings(ignore=()))
    assert body.message.startswith("empty object placeholder")
    (title,) = check("OVS204", deck)
    assert title.message == "title placeholder 'Title 1' is empty"
    # With the title rule off, OVS201 reports the empty title itself.
    found = check("OVS201", deck, Settings(ignore=("OVS204",)))
    assert {f.message.split()[1] for f in found} == {"title", "object"}


def test_a_filled_placeholder_is_not(builder, make_deck):
    slide = builder.new_slide(layout=5)  # title only
    slide.shapes.title.text = "A claim, not a label"
    assert check("OVS201", make_deck(builder)) == []


def test_a_stretched_picture_is_reported_and_a_proportional_one_is_not(builder, make_deck):
    builder.picture(size=(400, 200), w=4, h=2)
    builder.picture(size=(400, 200), y=4, w=4, h=4)
    (f,) = check("OVS202", make_deck(builder))
    assert "stretched 50%" in f.message, "a 2:1 image shown 1:1"


def test_word_count_has_a_ceiling(builder, make_deck):
    builder.text(" ".join(["word"] * 120), h=5)
    (f,) = check("OVS203", make_deck(builder))
    assert f.message == "120 words, over 90"
    assert check("OVS203", make_deck(builder), Settings(max_words=200)) == []


def test_repeated_layouts_are_reported_when_asked_for(builder, make_deck):
    builder.new_slide(layout=6)
    builder.new_slide(layout=6)
    builder.new_slide(layout=5)
    (f,) = check("OVS301", make_deck(builder))
    assert f.slide == 2 and "same layout as slide 1" in f.message


def _scale_group(group, factor_x, factor_y, x=None, y=None):
    """Show a group's children at a different size (and place), as PowerPoint
    does when a group is resized: off/ext change, chOff/chExt stay."""
    from pptx.oxml.ns import qn

    xfrm = group._element.grpSpPr.find(qn("a:xfrm"))
    off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
    if x is not None:
        off.set("x", str(int(Inches(x))))
    if y is not None:
        off.set("y", str(int(Inches(y))))
    ext.set("cx", str(round(int(ext.get("cx")) * factor_x)))
    ext.set("cy", str(round(int(ext.get("cy")) * factor_y)))


def test_text_inside_a_group_is_checked_like_any_other(builder, make_deck):
    card = builder.group()
    builder.text("Revenue up 40%", size=24, font="Inter", into=card)
    builder.text("Source: internal data", y=2, size=8, font="Comic Sans MS", color="FF00FF", into=card)
    card.name = "Card"
    deck = make_deck(builder)
    settings = Settings(fonts=["Inter"], palette=["000000"])
    (small,) = check("OVS101", deck)
    assert small.message == "text at 8.0pt, under 10pt" and small.snippet == "Source: internal data"
    (font,) = check("OVS102", deck, settings)
    assert "Comic Sans MS" in font.message
    (color,) = check("OVS103", deck, settings)
    assert "#FF00FF" in color.message


def test_a_group_is_flattened_into_its_children_and_its_text_counted_once(builder, make_deck):
    card = builder.group()
    builder.text("one two three", into=card)
    inner = builder.group(into=card)
    builder.text("four five", y=3, into=inner)
    card.name = "Card"
    (slide,) = make_deck(builder).slides
    assert [s.kind for s in slide.shapes] == ["text", "text"]
    assert {s.label for s in slide.shapes} == {"Card > TextBox 2", "Card > TextBox 4"}
    assert slide.words == 5


def test_a_picture_inside_a_group_is_checked_for_distortion(builder, make_deck):
    card = builder.group()
    builder.picture(size=(400, 200), w=4, h=4, into=card)
    card.name = "Card"
    (f,) = check("OVS202", make_deck(builder))
    assert f.message.startswith("'Card > Picture") and "stretched 50%" in f.message


def test_a_resized_group_places_and_scales_its_children(builder, make_deck):
    card = builder.group()
    builder.picture(size=(400, 200), x=1, y=1, w=4, h=2, into=card)
    _scale_group(card, 2, 1, x=0.5, y=0.5)  # stretched to twice the width
    (pic,) = make_deck(builder).slides[0].shapes
    assert pic.box == Box(int(Inches(0.5)), int(Inches(0.5)), int(Inches(8)), int(Inches(2)))
    (f,) = check("OVS202", make_deck(builder))
    assert "stretched 100%" in f.message, "a 2:1 image shown 4:1"


def test_a_group_moved_past_the_edge_takes_its_text_with_it(builder, make_deck):
    card = builder.group()
    builder.text("Inside the group", x=1, y=1, w=4, into=card)
    _scale_group(card, 1, 1, x=11)  # 11in + 4in wide, on a 13.33in slide
    card.name = "Card"
    (f,) = check("OVS004", make_deck(builder))
    assert f.message == "'Card > TextBox 2' extends past the slide edge"


def _set_level_size(list_style_parent, level, pt, tag="a:lstStyle"):
    """State a size for a paragraph level in a list style, creating what's missing."""
    from pptx.oxml.ns import qn
    from pptx.oxml.xmlchemy import OxmlElement

    style = list_style_parent if tag is None else list_style_parent.find(qn(tag))
    if style is None:
        style = OxmlElement(tag)
        # a:lstStyle sits after a:bodyPr in a text body
        list_style_parent.insert(1, style)
    lvl = style.find(qn(f"a:lvl{level + 1}pPr"))
    if lvl is None:
        lvl = OxmlElement(f"a:lvl{level + 1}pPr")
        style.append(lvl)
    rpr = lvl.find(qn("a:defRPr"))
    if rpr is None:
        rpr = OxmlElement("a:defRPr")
        lvl.append(rpr)
    rpr.set("sz", str(int(pt * 100)))


def _body_placeholder_text(builder, text, level=0):
    slide = builder.new_slide(layout=1)  # Title and Content
    slide.shapes.title.text = "A title"
    body = slide.placeholders[1]
    body.text_frame.text = text
    body.text_frame.paragraphs[0].level = level
    return slide, body


def test_a_size_inherited_from_the_master_body_style_is_checked(builder, make_deck):
    # The issue's case: a placeholder inheriting 9pt from the master's bodyStyle, level 2.
    from pptx.oxml.ns import qn

    _body_placeholder_text(builder, "Second-level point", level=1)
    master = builder.prs.slide_masters[0]
    body_style = master._element.find(qn("p:txStyles")).find(qn("p:bodyStyle"))
    _set_level_size(body_style, 1, 9, tag=None)
    (f,) = check("OVS101", make_deck(builder))
    assert f.message == "text at 9.0pt, under 10pt" and f.snippet == "Second-level point"


def test_inherited_sizes_resolve_nearest_first(builder, make_deck):
    slide, body = _body_placeholder_text(builder, "Body text")
    layout_body = slide.slide_layout.placeholders[1]

    def size():
        (slide_,) = make_deck(builder).slides
        (run,) = [r for s in slide_.shapes if s.placeholder == "OBJECT" for r in s.runs]
        return run.size_pt

    assert size() == 32, "the default master's bodyStyle, level 1"
    _set_level_size(layout_body.text_frame._txBody, 0, 20)
    assert size() == 20, "the layout placeholder overrides the master"
    _set_level_size(body.text_frame._txBody, 0, 8)
    assert size() == 8, "the shape's own list style overrides the layout"
    body.text_frame.paragraphs[0].runs[0].font.size = Pt(28)
    assert size() == 28, "a stated size overrides everything"


def test_a_title_inherits_the_title_style_and_a_text_box_the_presentation_default(builder, make_deck):
    from pptx.oxml.ns import qn

    slide = builder.new_slide(layout=1)
    slide.shapes.title.text = "A title"
    box = slide.shapes.add_textbox(Inches(1), Inches(5), Inches(4), Inches(1))
    box.text_frame.text = "A note"
    sizes = {s.text: s.runs[0].size_pt for s in make_deck(builder).slides[0].shapes if s.runs}
    assert sizes == {"A title": 44, "A note": 18}
    _set_level_size(builder.prs._element.find(qn("p:defaultTextStyle")), 0, 7, tag=None)
    (f,) = check("OVS101", make_deck(builder))
    assert f.message == "text at 7.0pt, under 10pt" and f.snippet == "A note"


def test_shrink_to_fit_scales_an_inherited_size(builder, make_deck):
    from pptx.oxml.ns import qn
    from pptx.oxml.xmlchemy import OxmlElement

    _, body = _body_placeholder_text(builder, "Shrunk body text")  # inherits 32pt
    body_pr = body.text_frame._txBody.find(qn("a:bodyPr"))
    norm = OxmlElement("a:normAutofit")
    norm.set("fontScale", "25000")
    body_pr.append(norm)
    (f,) = check("OVS101", make_deck(builder))
    assert f.message == "text at 8.0pt, under 10pt"


def _titled(builder, title):
    slide = builder.new_slide(layout=5)  # Title Only
    slide.shapes.title.text = title
    return slide


def test_a_slide_without_a_title_placeholder_has_no_title(builder, make_deck):
    builder.text("Big words in a text box, styled like a title", size=44)  # a text box is not a title
    _titled(builder, "Revenue by segment")
    (f,) = check("OVS204", make_deck(builder))
    assert (f.slide, f.message) == (1, "no title placeholder")


def test_slides_sharing_a_title_are_reported_against_the_first(builder, make_deck):
    _titled(builder, "Agenda")
    _titled(builder, "Revenue by segment")
    _titled(builder, "  agenda ")  # the same, ignoring case and spacing
    _titled(builder, "AGENDA")
    found = check("OVS205", make_deck(builder))
    assert [(f.slide, f.message, f.snippet) for f in found] == [
        (3, "same title as slide 1", "agenda"),
        (4, "same title as slide 1", "AGENDA"),
    ]


def test_an_empty_title_is_not_a_duplicate(builder, make_deck):
    builder.new_slide(layout=5)
    builder.new_slide(layout=5)
    assert check("OVS205", make_deck(builder)) == []


def test_hidden_slides_are_not_checked_for_titles(builder, make_deck):
    _titled(builder, "Agenda")
    builder.new_slide()._element.set("show", "0")  # hidden, untitled
    hidden_copy = _titled(builder, "Agenda")
    hidden_copy._element.set("show", "0")
    deck = make_deck(builder)
    assert deck.slides[1].hidden and not deck.slides[0].hidden
    assert check("OVS204", deck) == [] and check("OVS205", deck) == []


def _alt(shape, text):
    shape._element.find("./*/{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr").set("descr", text)


def _chart(builder):
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE

    data = CategoryChartData()
    data.categories = ["2024", "2025"]
    data.add_series("Revenue", (1.0, 2.0))
    if builder.slide is None:
        builder.new_slide()
    return builder.slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(6), Inches(1), Inches(4), Inches(3), data
    )


def test_a_picture_with_no_alt_text_is_reported(builder, make_deck):
    _alt(builder.picture(), "")
    (f,) = check("OVS206", make_deck(builder))
    assert f.message == "picture 'Picture 1' has no alt text"


def test_alt_text_that_is_only_a_file_name_is_reported(builder, make_deck):
    for name in ("IMG_1234.jpg", "IMG_1234", "Picture 3", "Screenshot 2026-11-11 at 09.14.22", "chart.PNG"):
        b = type(builder)()
        _alt(b.picture(), name)
        (f,) = check("OVS206", make_deck(b, name="d.pptx"))
        assert f.message == "picture 'Picture 1' has a file name for alt text" and f.snippet == name, name


def test_real_alt_text_passes(builder, make_deck):
    _alt(builder.picture(), "Revenue grew 40% year on year, led by enterprise")
    _alt(builder.picture(y=4), "Screenshot of the billing dashboard at month end")
    _alt(_chart(builder), "Column chart: revenue doubled from 2024 to 2025")
    assert check("OVS206", make_deck(builder)) == []


def test_a_chart_with_no_alt_text_is_reported(builder, make_deck):
    _chart(builder)
    (f,) = check("OVS206", make_deck(builder))
    assert f.message.startswith("chart '") and f.message.endswith("has no alt text")


def test_a_decorative_picture_needs_no_alt_text(builder, make_deck):
    from lxml import etree

    pic = builder.picture()
    _alt(pic, "")
    cnvpr = pic._element.find("./*/{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr")
    cnvpr.append(
        etree.fromstring(
            '<a:extLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:ext uri="{C183D7F6-B498-43B3-948B-1728B52AA6E4}">'
            '<adec:decorative xmlns:adec="http://schemas.microsoft.com/office/drawing/2017/decorative" val="1"/>'
            "</a:ext></a:extLst>"
        )
    )
    assert check("OVS206", make_deck(builder)) == []


def test_a_picture_inside_a_group_needs_alt_text_and_a_table_does_not(builder, make_deck):
    card = builder.group()
    _alt(builder.picture(into=card), "")
    card.name = "Card"
    builder.slide.shapes.add_table(2, 2, Inches(1), Inches(4), Inches(4), Inches(1))
    (f,) = check("OVS206", make_deck(builder))
    assert f.message == "picture 'Card > Picture 2' has no alt text"
