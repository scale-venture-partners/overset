"""Rules that read only the .pptx."""

import pytest
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


def test_a_table_without_a_header_row_is_reported(builder, make_deck):
    builder.new_slide()
    labelled = builder.slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(1))
    bare = builder.slide.shapes.add_table(2, 2, Inches(1), Inches(3), Inches(4), Inches(1))
    bare.table.first_row = False
    assert labelled.table.first_row, "python-pptx's tables have a header row by default"
    (f,) = check("OVS207", make_deck(builder))
    assert f.message == f"table '{bare.name}' has no header row"


def _sections(builder, sections):
    """Give the deck PowerPoint's sections: [(name, [0-based slide indexes])]."""
    from lxml import etree

    p, p14 = (
        "http://schemas.openxmlformats.org/presentationml/2006/main",
        "http://schemas.microsoft.com/office/powerpoint/2010/main",
    )
    ids = [s.get("id") for s in builder.prs._element.sldIdLst]
    body = "".join(
        f'<p14:section name="{name}" id="{{00000000-0000-0000-0000-00000000000{n}}}"><p14:sldIdLst>'
        + "".join(f'<p14:sldId id="{ids[i]}"/>' for i in slides)
        + "</p14:sldIdLst></p14:section>"
        for n, (name, slides) in enumerate(sections)
    )
    builder.prs._element.append(
        etree.fromstring(
            f'<p:extLst xmlns:p="{p}"><p:ext uri="{{521415D9-36F7-43E2-AB2F-B90AF26B5E84}}">'
            f'<p14:sectionLst xmlns:p14="{p14}">{body}</p14:sectionLst></p:ext></p:extLst>'
        )
    )


def test_sections_left_with_default_names_are_reported_at_their_first_slide(builder, make_deck):
    for _ in range(4):
        builder.new_slide()
    _sections(
        builder, [("Default Section", [0, 1]), ("Results", [2]), ("Untitled  section", [3]), ("Untitled Section", [])]
    )
    deck = make_deck(builder)
    assert [(s.name, s.slides) for s in deck.sections][:3] == [
        ("Default Section", [1, 2]),
        ("Results", [3]),
        ("Untitled  section", [4]),
    ]
    found = check("OVS208", deck)
    assert [(f.slide, f.message) for f in found] == [
        (1, "section 'Default Section' has a default name"),
        (4, "section 'Untitled section' has a default name"),
        (None, "section 'Untitled Section' has a default name"),
    ]


def test_a_deck_without_sections_has_nothing_to_name(builder, make_deck):
    builder.new_slide()
    assert make_deck(builder).sections == [] and check("OVS208", make_deck(builder)) == []


def _bullets(builder, items, layout=1):
    """A content placeholder (bulleted by the master) holding (text, level) paragraphs."""
    slide = builder.new_slide(layout=layout)
    slide.shapes.title.text = f"Slide {len(builder.prs.slides)}"
    tf = slide.placeholders[1].text_frame
    for n, (text, level) in enumerate(items):
        p = tf.paragraphs[0] if n == 0 else tf.add_paragraph()
        p.text, p.level = text, level
    return slide.placeholders[1]


def test_a_list_of_six_bullets_is_too_many(builder, make_deck):
    _bullets(builder, [(f"Point {i}", 0) for i in range(1, 7)])
    (f,) = check("OVS209", make_deck(builder))
    assert f.message == "6 bullets in one list in 'Content Placeholder 2', over 4" and f.snippet == "Point 1"
    assert check("OVS211", make_deck(builder)) == []


def test_siblings_are_counted_under_their_parent(builder, make_deck):
    # Four top-level points, each with three sub-points: no list is over four.
    items = [(t, lvl) for n in range(4) for t, lvl in [(f"Point {n}", 0)] + [(f"Sub {n}.{k}", 1) for k in range(3)]]
    _bullets(builder, items)
    assert check("OVS209", make_deck(builder)) == []
    # A fifth top-level point after the sub-points still joins the first list.
    _bullets(builder, items + [("Point 5", 0)])
    (f,) = check("OVS209", make_deck(builder))
    assert f.slide == 2 and f.message.startswith("5 bullets")


def test_paragraphs_without_bullets_are_not_a_list(builder, make_deck):
    from pptx.oxml.ns import qn

    builder.text("\n".join(f"Line {i}" for i in range(8)), h=4)  # a text box: no bullets
    body = _bullets(builder, [(f"Point {i}", 0) for i in range(6)])
    for p in body.text_frame.paragraphs:  # bullets switched off in a placeholder
        p._p.get_or_add_pPr().append(p._p.makeelement(qn("a:buNone"), {}))
    assert check("OVS209", make_deck(builder)) == []


def test_bullets_stated_in_a_text_box_count(builder, make_deck):
    from pptx.oxml.ns import qn

    box = builder.text("\n".join(f"Item {i}" for i in range(5)), h=4)
    for p in box.text_frame.paragraphs:
        p._p.get_or_add_pPr().append(p._p.makeelement(qn("a:buChar"), {"char": "•"}))
    (f,) = check("OVS209", make_deck(builder))
    assert f.message.startswith("5 bullets in one list in 'TextBox 1'")


def test_a_three_level_nest_is_too_deep(builder, make_deck):
    _bullets(builder, [("Point", 0), ("Sub-point", 1), ("Sub-sub-point", 2)])
    (f,) = check("OVS211", make_deck(builder))
    assert f.message == "bullets nested 3 levels deep in 'Content Placeholder 2', over 2"
    assert f.snippet == "Sub-sub-point"
    assert check("OVS209", make_deck(builder)) == []
    assert check("OVS211", make_deck(builder), Settings(max_bullet_depth=3)) == []


def test_weights_and_styles_belong_to_one_family():
    from overset.rules.structure import font_family

    assert {font_family(f) for f in ("Inter", "Inter SemiBold", "Inter-Bold", "Inter Light Italic")} == {"Inter"}
    assert font_family("Segoe UI Light") == "Segoe UI"
    assert font_family("Source Sans Pro") == "Source Sans Pro"
    assert font_family("Fira-Code") == "Fira-Code", "a hyphen before a non-style word is part of the name"


def test_too_many_font_families_in_a_deck(builder, make_deck):
    builder.text("Inherits the theme's body font")  # Calibri, from the theme
    builder.text("A display face", y=2, font="Georgia")
    builder.text("Bold weight of the same display face", y=3, font="Georgia Bold")
    builder.text("✓", y=4, font="Wingdings")  # a symbol font is not a typeface choice
    assert check("OVS105", make_deck(builder)) == []
    builder.new_slide()
    builder.text("A third family", font="Inter")
    (f,) = check("OVS105", make_deck(builder))
    assert f.slide is None
    assert f.message == "3 font families in the deck, over 2: Calibri (slide 1), Georgia (slide 1), Inter (slide 2)"
    assert check("OVS105", make_deck(builder), Settings(max_font_families=3)) == []


def test_a_whole_paragraph_in_bold_italic_or_capitals_is_overused_emphasis(builder, make_deck):
    bold = builder.text("Every single word of this rather long sentence of body text is set in bold")
    bold.text_frame.paragraphs[0].runs[0].font.bold = True
    builder.text("THIS WHOLE SENTENCE OF BODY TEXT HAS BEEN TYPED IN CAPITALS FROM START TO END", y=2)
    caps = builder.text("This sentence of body text uses the all caps option for all of its words", y=3)
    caps.text_frame.paragraphs[0].runs[0]._r.get_or_add_rPr().set("cap", "all")
    found = check("OVS106", make_deck(builder))
    assert [f.message for f in found] == [
        "a whole paragraph in bold in 'TextBox 1'",
        "a whole paragraph in all caps in 'TextBox 2'",
        "a whole paragraph in all caps in 'TextBox 3'",
    ]


def test_labels_titles_and_partial_emphasis_are_fine(builder, make_deck):
    slide = builder.new_slide(layout=1)
    slide.shapes.title.text = "QUARTERLY RESULTS FOR THE BOARD"  # a title may be set in capitals
    builder.text("NEW PRODUCT", y=5)  # a short label
    mixed = builder.text("Only one word here is bold", y=6)
    p = mixed.text_frame.paragraphs[0]
    p.runs[0].text = "Only one "
    extra = p.add_run()
    extra.text, extra.font.bold = "word", True
    p.add_run().text = " here is bold"
    assert check("OVS106", make_deck(builder)) == []


def test_underlined_text_that_is_not_a_link_is_reported(builder, make_deck):
    plain = builder.text("Underlined for emphasis")
    plain.text_frame.paragraphs[0].runs[0].font.underline = True
    link = builder.text("Our website", y=2)
    run = link.text_frame.paragraphs[0].runs[0]
    run.font.underline = True
    run.hyperlink.address = "https://example.com"
    (f,) = check("OVS107", make_deck(builder))
    assert f.message == "underlined text in 'TextBox 1' that is not a link" and f.snippet == "Underlined for emphasis"


def test_distortion_within_a_small_images_pixel_rounding_is_not_counted(builder, make_deck):
    # The same 4% stretch: within a 28x32 icon's rounding, but not a 2800x3200 photo's.
    builder.picture(size=(28, 32), w=0.28 * 1.04, h=0.32)
    builder.picture(size=(2800, 3200), y=3, w=2.8 * 1.04, h=3.2)
    builder.picture(size=(773, 2), y=6.8, w=7.73, h=0.02 * 1.2)  # a 2-pixel rule: up to 25% taller is rounding
    (f,) = check("OVS202", make_deck(builder))
    assert f.message == "'Picture 2' is stretched 4% out of shape"


def test_a_frame_whose_padding_hangs_over_the_edge_is_fine(builder, make_deck):
    padded = builder.text("Fits", x=-0.05, w=4)  # 0.05in over the edge, inside the 0.1in left margin
    bare = builder.text("Reaches", x=-0.05, y=3, w=4)
    bare.text_frame.margin_left = 0
    (f,) = check("OVS004", make_deck(builder))
    assert f.message == "'TextBox 2' extends past the slide edge"
    assert padded.left < 0


def test_a_frame_entirely_off_the_slide_says_so(builder, make_deck):
    builder.text("Parked speaker notes", x=14, y=1, w=3)
    (f,) = check("OVS004", make_deck(builder))
    assert f.message == "'TextBox 1' is entirely off the slide"


def test_a_groups_scale_does_not_scale_its_childrens_text_margins(builder, make_deck):
    card = builder.group()
    builder.text("Inside a group", x=1, y=1, w=4, h=1, into=card)
    _scale_group(card, 50, 50)  # child coordinates 50 times smaller than the slide's
    (shape,) = make_deck(builder).slides[0].shapes
    left = int(Inches(0.1))  # the default margin, unscaled
    assert shape.text_area.x - shape.box.x == left
    assert shape.text_area.w == shape.box.w - 2 * left


def test_headings_sources_and_italic_quotations_are_not_overused_emphasis(builder, make_deck):
    def styled(text, y, bold=False, italic=False):
        run = builder.text(text, y=y, h=0.5).text_frame.paragraphs[0].runs[0]
        run.font.bold, run.font.italic = bold, italic
        return run

    styled("The International Style of the 1920s to the 1970s", 0.5, bold=True)  # a heading: ten words
    styled("Source: IMF, Developments in Exchange Rate Arrangements and Markets in 2024 and beyond", 1.2, italic=True)
    styled(
        "\u201cEstablished publishers have a strong motivation to hype claims of predation as a threat\u201d",
        2,
        italic=True,
    )
    assert check("OVS106", make_deck(builder)) == []
    # The same quotation in bold is still emphasis.
    styled(
        "\u201cEstablished publishers have a strong motivation to hype claims of predation as a threat\u201d",
        3,
        bold=True,
    )
    (f,) = check("OVS106", make_deck(builder))
    assert f.message == "a whole paragraph in bold in 'TextBox 4'"


def test_missing_alt_text_is_reported_once_per_slide(builder, make_deck):
    for i in range(3):
        _alt(builder.picture(x=1 + 3 * i), "")
    _alt(builder.picture(y=4), "IMG_0042.jpg")
    _alt(builder.picture(x=5, y=4), "Team photo at the 2025 offsite")
    builder.new_slide()
    _alt(builder.picture(), "")
    names = "'Picture 1', 'Picture 2', 'Picture 3', 'Picture 4'"
    found = check("OVS206", make_deck(builder))
    assert [(f.slide, f.message) for f in found] == [
        (1, f"4 visuals need alt text (3 with none, 1 with a file name): {names}"),
        (2, "picture 'Picture 1' has no alt text"),
    ]


def test_kendall_tau():
    from overset.rules.structure import kendall_tau

    assert kendall_tau([0, 1, 2, 3]) == 1.0
    assert kendall_tau([3, 2, 1, 0]) == -1.0
    assert kendall_tau([1, 0, 2, 3]) == pytest.approx(2 / 3)


def test_a_title_read_last_is_reported(builder, make_deck):
    slide = builder.new_slide(layout=5)  # Title Only
    builder.text("First point", y=2)
    builder.text("Second point", y=3)
    title = slide.shapes.title
    title.text = "Quarterly results"
    slide.shapes._spTree.remove(title._element)  # move the title to the end of the reading order
    slide.shapes._spTree.append(title._element)
    messages = [f.message for f in check("OVS212", make_deck(builder))]
    assert messages[0] == "the title is read 3rd, not first"
    assert messages[1].startswith("reading order follows the layout poorly"), "and the slide as a whole reads upward"


def test_two_columns_read_column_by_column_pass(builder, make_deck):
    for x in (1, 7):  # left column top to bottom, then the right column
        for y in (1, 2.5, 4, 5.5):
            builder.text(f"Column {x} row {y}", x=x, y=y, w=5, h=1)
    assert check("OVS212", make_deck(builder)) == []


def test_a_row_of_cards_read_left_to_right_passes_and_a_shuffled_slide_does_not(builder, make_deck):
    for x in (1, 4.5, 8):
        builder.text(f"Card at {x}", x=x, y=2, w=3, h=3)
    assert check("OVS212", make_deck(builder)) == []
    builder.new_slide()
    for x, y in [(8, 5), (1, 5), (8, 1), (4.5, 3), (1, 1)]:  # bottom-right first, top-left last
        builder.text(f"Box {x},{y}", x=x, y=y, w=3, h=1)
    (f,) = check("OVS212", make_deck(builder))
    assert f.slide == 2 and f.message.startswith("reading order follows the layout poorly (tau -")


def test_footers_and_decoration_do_not_count_toward_reading_order(builder, make_deck):
    slide = builder.new_slide(layout=1)
    slide.shapes.title.text = "Title"
    slide.placeholders[1].text_frame.text = "Body"
    builder.text("Footer text that a template would add last", y=7)
    deck = make_deck(builder)
    for shape in deck.slides[0].shapes:
        if shape.name.startswith("TextBox"):
            shape.quiet_placeholder = True  # stands in for a footer placeholder
    assert check("OVS212", deck) == []


def test_the_palette_can_be_matched_perceptually(builder, make_deck):
    # Close in RGB but visibly different, and far in RGB but indistinguishable.
    builder.text("Dark teal", color="001420")
    builder.text("Bright cyan", y=2, color="1EE0E0")
    palette = ["002020", "00E0E0"]
    by_rgb = check("OVS103", make_deck(builder), Settings(palette=palette))
    assert [f.message for f in by_rgb] == ["#1EE0E0 is not in the brand palette"]
    by_eye = check("OVS103", make_deck(builder), Settings(palette=palette, palette_delta_e=5))
    assert [f.message for f in by_eye] == ["#001420 is not in the brand palette"]


def test_too_many_colours_on_a_slide(builder, make_deck):
    colours = ["111111", "C0392B", "2471A3", "229954", "D68910", "7D3C98"]
    for i, c in enumerate(colours):
        builder.text(f"Colour {i}", y=0.5 + i, color=c)
    builder.text("A near-identical shade", y=6.6, color="121212")  # counts with #111111
    assert check("OVS108", make_deck(builder)) == []
    builder.text("A seventh colour", x=7, color="17A589")
    (f,) = check("OVS108", make_deck(builder))
    assert f.message.startswith("7 colours, over 6: #111111")


def test_saturated_blue_text_is_reported_and_navy_is_not(builder, make_deck):
    builder.text("Pure blue text", color="0000FF")
    builder.text("Navy text", y=2, color="1F3A5F")
    (f,) = check("OVS109", make_deck(builder))
    assert f.message == "text in saturated blue #0000FF in 'TextBox 1'" and f.snippet == "Pure blue text"


def test_red_and_blue_meeting_are_reported(builder, make_deck):
    from pptx.dml.color import RGBColor

    def filled(box, hex_color):
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor.from_string(hex_color)
        return box

    filled(builder.text("Red on blue", color="E00000"), "0010E0")
    filled(builder.text("Red box", x=1, y=3, w=2, h=1), "E00000")
    filled(builder.text("Blue box", x=3, y=3, w=2, h=1), "0010E0")  # touches the red one
    filled(builder.text("Far box", x=8, y=3, w=2, h=1), "0010E0")  # well away from it
    messages = [f.message for f in check("OVS110", make_deck(builder))]
    assert messages == [
        "#E00000 text on a #0010E0 fill in 'TextBox 1'",
        "'TextBox 2' (#E00000) and 'TextBox 3' (#0010E0) meet",
    ]
