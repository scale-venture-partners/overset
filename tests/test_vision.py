"""The vision rules, against pydantic-ai's TestModel: what is sent, how the
one review fans out into rule codes, and where the confidence floor sits."""

from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from overset.engine import Context
from overset.rules import load_rules
from overset.rules.base import REGISTRY
from overset.rules.vision import CODES, instructions
from overset.settings import Settings

load_rules()

REVIEW = {
    "issues": [
        {"code": "OVS401", "slide": 3, "message": "Seven elements and no focal point", "confidence": 0.9},
        {"code": "OVS405", "slide": 5, "message": "Slides 4 and 5 are the same card grid", "confidence": 0.8},
        {"code": "OVS403", "slide": 2, "message": "Logo slightly off", "confidence": 0.4},
    ]
}


def ctx(make_deck, builder, fake_render, model, **settings):
    builder.text("x")
    c = Context(make_deck(builder), Settings(vision=True, **settings), render=fake_render([[], []]), vision_model=model)
    c.render.contact_sheet = c.render.pages[0].image
    return c


def test_one_review_answers_every_vision_rule(builder, make_deck, fake_render):
    model = TestModel(custom_output_args=REVIEW)
    c = ctx(make_deck, builder, fake_render, model)
    found = {code: REGISTRY[code].check(c) for code in CODES}
    assert [f.message for f in found["OVS401"]] == ["Seven elements and no focal point"]
    assert found["OVS401"][0].slide == 3 and found["OVS401"][0].confidence == 0.9
    assert [f.slide for f in found["OVS405"]] == [5]
    assert found["OVS403"] == [], "under the 0.7 floor"
    assert c.cache["vision"] is not None


def test_the_floor_is_configurable(builder, make_deck, fake_render):
    c = ctx(make_deck, builder, fake_render, TestModel(custom_output_args=REVIEW), vision_threshold=0.3)
    assert len(REGISTRY["OVS403"].check(c)) == 1


def test_it_sends_each_slide_and_the_whole_deck(builder, make_deck, fake_render):
    seen = {}

    def answer(messages, info: AgentInfo):
        from pydantic_ai.messages import ModelResponse, ToolCallPart

        parts = messages[0].parts[-1].content
        seen["text"] = [p for p in parts if isinstance(p, str)]
        seen["images"] = sum(1 for p in parts if not isinstance(p, str))
        seen["instructions"] = messages[0].instructions
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"issues": []})])

    c = ctx(make_deck, builder, fake_render, FunctionModel(answer), vision_brief="One green element per slide.")
    assert REGISTRY["OVS401"].check(c) == []
    assert seen["images"] == 3, "two slides and the contact sheet"
    assert seen["text"] == ["A deck of 2 slides.", "Slide 1:", "Slide 2:", "The whole deck:"]
    assert "One green element per slide." in seen["instructions"]


def test_the_rubric_keeps_measured_problems_out_of_the_review():
    text = instructions()
    for code in CODES:
        assert code in text
    assert "Do not report text overflow" in text
