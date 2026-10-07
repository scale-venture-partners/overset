"""The vision rules against a mocked HTTP layer: what is sent to the decisions endpoint, how the
probabilities fan out into rule codes, where the floor sits, and how failures surface."""

import json

import httpx
import pytest
from PIL import Image

from overset import cli, decisions
from overset.engine import Context
from overset.rules import load_rules
from overset.rules.base import REGISTRY
from overset.rules.vision import CODES, QUESTIONS, preamble
from overset.settings import Settings

load_rules()


def backend(server):
    return decisions.OpenAIDecisions("gpt-6-luna", "sk-test", transport=httpx.MockTransport(server), backoff=0)


def ctx(make_deck, builder, fake_render, server, slides=3, **settings):
    builder.text("x")
    c = Context(
        make_deck(builder),
        Settings(vision=True, **settings),
        render=fake_render([[] for _ in range(slides)]),
        vision_backend=backend(server),
    )
    c.render.contact_sheet = c.render.pages[0].image
    return c


class ByQuestion:
    """A stand-in decisions endpoint. `by_code` maps (rule code, text the request opens with) to a probability."""

    def __init__(self, by_code, refuse=(), statuses=()):
        self.by_code = by_code
        self.refuse = set(refuse)
        self.statuses = list(statuses)
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.statuses:
            return httpx.Response(self.statuses.pop(0), text="try later")
        body = json.loads(request.content)
        self.requests.append(body)
        text = body["input"][0]["content"][0]["text"]
        answers = []
        for q in body["questions"]:
            name = q["name"]
            if name in self.refuse:
                answers.append({"type": "refusal", "name": name})
                continue
            p = 0.0
            for (code, marker), value in self.by_code.items():
                if code == name and marker in text:
                    p = value
            answers.append({"type": "predicate", "name": name, "probability": p})
        return httpx.Response(200, json={"answers": answers})


def test_probabilities_become_findings_by_code_and_slide(builder, make_deck, fake_render):
    server = ByQuestion(
        {
            ("OVS401", "Slide 3 of 3"): 0.9,
            ("OVS403", "Slide 2 of 3"): 0.4,
            ("OVS405", "Slide 2, then slide 3"): 0.8,
            ("OVS406", "is slide 1;"): 0.75,
        }
    )
    c = ctx(make_deck, builder, fake_render, server)
    found = {code: REGISTRY[code].check(c) for code in CODES}
    assert [(f.slide, f.confidence) for f in found["OVS401"]] == [(3, 0.9)]
    assert found["OVS401"][0].message == CODES["OVS401"][1]
    assert [f.slide for f in found["OVS405"]] == [3], "reported on the second slide of the pair"
    assert [f.slide for f in found["OVS406"]] == [1]
    assert found["OVS403"] == [], "under the 0.7 floor"
    assert found["OVS402"] == [] and found["OVS404"] == []


def test_the_floor_is_configurable(builder, make_deck, fake_render):
    server = ByQuestion({("OVS403", "Slide 2 of 3"): 0.4})
    c = ctx(make_deck, builder, fake_render, server, vision_threshold=0.3)
    assert [f.slide for f in REGISTRY["OVS403"].check(c)] == [2]


def test_requests_are_one_per_slide_one_per_style_check_and_one_per_pair(builder, make_deck, fake_render):
    server = ByQuestion({})
    c = ctx(make_deck, builder, fake_render, server, vision_brief="One green element per slide.")
    REGISTRY["OVS401"].check(c)
    asked = [[q["name"] for q in r["questions"]] for r in server.requests]
    assert asked.count(["OVS401", "OVS402", "OVS403", "OVS404"]) == 3
    assert asked.count(["OVS406"]) == 3
    assert asked.count(["OVS405"]) == 2
    pair = next(r for r in server.requests if r["questions"][0]["name"] == "OVS405")
    parts = pair["input"][0]["content"]
    assert [p["type"] for p in parts] == ["input_text", "input_image", "input_image"]
    assert parts[1]["image_url"].startswith("data:image/png;base64,")
    assert "One green element per slide." in parts[0]["text"]
    assert {r["model"] for r in server.requests} == {"gpt-6-luna"}
    assert server.requests[0]["questions"][0]["instructions"] == QUESTIONS["OVS401"]


def test_only_the_active_rules_are_asked(builder, make_deck, fake_render):
    server = ByQuestion({})
    c = ctx(make_deck, builder, fake_render, server, select=("OVS405",))
    REGISTRY["OVS405"].check(c)
    assert [q["name"] for r in server.requests for q in r["questions"]] == ["OVS405", "OVS405"]


def test_the_deck_is_judged_once_whichever_rules_ask(builder, make_deck, fake_render):
    server = ByQuestion({})
    c = ctx(make_deck, builder, fake_render, server)
    for code in CODES:
        REGISTRY[code].check(c)
    assert len(server.requests) == 8


def test_a_refusal_is_reported_not_dropped(builder, make_deck, fake_render):
    server = ByQuestion({}, refuse={"OVS405"})
    c = ctx(make_deck, builder, fake_render, server)
    assert REGISTRY["OVS405"].check(c) == []
    assert any("refused 2" in n for n in c.notes)


def test_a_large_slide_is_downscaled_before_upload(tmp_path):
    big = tmp_path / "big.png"
    Image.new("RGB", (4000, 2250), "white").save(big)
    url = decisions._data_url(big)
    import base64
    import io

    im = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(im.size) == decisions.MAX_EDGE_PX


def test_transient_failures_are_retried_then_raised(tmp_path):
    image = tmp_path / "s.png"
    Image.new("RGB", (10, 10)).save(image)
    prompt = decisions.Prompt("x", [image])
    flaky = ByQuestion({}, statuses=[429, 503])
    assert backend(flaky).predicates(prompt, {"A": "?"}).probabilities == {"A": 0.0}
    down = ByQuestion({}, statuses=[500] * 10)
    with pytest.raises(decisions.DecisionError, match="HTTP 500"):
        backend(down).predicates(prompt, {"A": "?"})
    refused = ByQuestion({}, statuses=[401])
    with pytest.raises(decisions.DecisionError, match="HTTP 401"):
        backend(refused).predicates(prompt, {"A": "?"})
    assert refused.statuses == [] and len(down.statuses) == 10 - (decisions.MAX_RETRIES + 1)


def test_a_malformed_answer_is_an_error(tmp_path):
    image = tmp_path / "s.png"
    Image.new("RGB", (10, 10)).save(image)
    prompt = decisions.Prompt("x", [image])
    for answers in ([], [{"type": "predicate", "name": "B", "probability": 0.5}], [{"type": "choice", "name": "A"}]):
        server = httpx.MockTransport(lambda r, a=answers: httpx.Response(200, json={"answers": a}))
        with pytest.raises(decisions.DecisionError):
            decisions.OpenAIDecisions("m", "k", transport=server).predicates(prompt, {"A": "?"})


def test_a_missing_key_stops_the_run_with_the_fix(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(decisions.BackendUnavailable, match="OPENAI_API_KEY"):
        decisions.resolve("openai:gpt-6-luna")


def test_an_unknown_provider_lists_the_known_ones():
    with pytest.raises(decisions.BackendUnavailable, match="openai"):
        decisions.resolve("anthropic:claude-sonnet-5-5")
    with pytest.raises(decisions.BackendUnavailable):
        decisions.resolve("gpt-6-luna")


def test_the_environment_configures_the_openai_backend(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9/v1/")
    b = decisions.resolve("openai:gpt-6-luna")
    assert str(b.client.base_url) == "http://localhost:9/v1/"
    assert b.client.headers["Authorization"] == "Bearer sk-env"


def test_the_cli_stops_with_a_fix_when_the_key_is_missing(monkeypatch, tmp_path, builder, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    builder.text("x")
    deck = builder.save(tmp_path / "d.pptx")
    assert cli.main([str(deck), "--vision"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_the_scope_keeps_measured_problems_out_of_the_review():
    text = preamble("House.")
    assert "Do not judge text overflow" in text and "House." in text
    assert set(QUESTIONS) == set(CODES)
