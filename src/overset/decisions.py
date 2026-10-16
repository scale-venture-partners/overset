"""Decision-model backends: images and yes/no questions in, a probability per question out.

A decision model answers fixed questions with probabilities instead of generating
text, which makes it a fraction of the cost of a language model and fast enough to ask one question
per slide. A backend is chosen by a `provider:name` spec such as `openai:gpt-6-luna`.

Only providers whose image wire format has been checked belong in PROVIDERS. To add one, write a
class with a `predicates` method and register it by name.
"""

from __future__ import annotations

import base64
import io
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from PIL import Image

if TYPE_CHECKING:
    import httpx

REQUEST_TIMEOUT = 60.0
MAX_RETRIES = 3
RETRYABLE_STATUS = {408, 409, 429}
# A slide's longest edge is capped before upload; text stays legible well below the render's native size.
MAX_EDGE_PX = 1600


class DecisionError(RuntimeError):
    """A decision request failed, or the backend answered something other than what was asked."""


class BackendUnavailable(RuntimeError):
    """The decision backend cannot be used as configured: an unknown provider or a missing key."""


@dataclass
class Prompt:
    """What a decision model is shown: some words, then images in order."""

    text: str
    images: list[Path] = field(default_factory=list)


@dataclass
class Answers:
    """One request's outcome: a probability per answered question, and the questions the model refused."""

    probabilities: dict[str, float] = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)


class Backend(Protocol):
    def predicates(self, prompt: Prompt, questions: dict[str, str]) -> Answers:
        """The probability that each named yes/no question is true of the prompt."""
        ...


def _data_url(path: Path) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > MAX_EDGE_PX:
            im.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _retryable(status: int) -> bool:
    return status in RETRYABLE_STATUS or status >= 500


class OpenAIDecisions:
    """OpenAI's Decisions API: `POST /v1/decisions`, with a `predicate` question per rule."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        transport: httpx.BaseTransport | None = None,
        backoff: float = 0.5,
    ):
        import httpx  # the vision extra; the offline rules never import it

        self.httpx = httpx
        self.model = model
        self.backoff = backoff
        self.client = self.httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=REQUEST_TIMEOUT,
            transport=transport,
        )

    def _body(self, prompt: Prompt, questions: dict[str, str]) -> dict:
        content = [{"type": "input_text", "text": prompt.text}]
        content += [{"type": "input_image", "image_url": _data_url(p)} for p in prompt.images]
        return {
            "model": self.model,
            "input": [{"role": "user", "content": content}],
            "questions": [{"type": "predicate", "name": n, "instructions": q} for n, q in questions.items()],
        }

    def _post(self, body: dict) -> dict:
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.client.post("decisions", json=body)
            except self.httpx.TransportError as e:
                if attempt == MAX_RETRIES:
                    raise DecisionError(f"{type(e).__name__}: {e}") from e
            else:
                if response.is_success:
                    return response.json()
                if attempt == MAX_RETRIES or not _retryable(response.status_code):
                    raise DecisionError(f"HTTP {response.status_code}: {response.text[:300]}")
            time.sleep(2**attempt * self.backoff)
        raise AssertionError("unreachable")

    def predicates(self, prompt: Prompt, questions: dict[str, str]) -> Answers:
        data = self._post(self._body(prompt, questions))
        answers = Answers()
        for answer in data.get("answers", []):
            name, kind = answer.get("name"), answer.get("type")
            if name not in questions:
                raise DecisionError(f"answer {name!r} matches no question asked")
            if kind == "refusal":
                answers.refused.append(name)
            elif kind == "predicate" and isinstance(answer.get("probability"), int | float):
                answers.probabilities[name] = float(answer["probability"])
            else:
                raise DecisionError(f"unexpected answer for {name!r}: {answer}")
        missing = questions.keys() - answers.probabilities.keys() - set(answers.refused)
        if missing:
            raise DecisionError(f"no answer for {sorted(missing)}")
        return answers


def _openai(model: str) -> OpenAIDecisions:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise BackendUnavailable(
            f"Cannot use decision model 'openai:{model}': OPENAI_API_KEY is not set.\n"
            "  Fix: export OPENAI_API_KEY=... (create one at https://platform.openai.com/api-keys)\n"
            "  Or:  run without --vision."
        )
    return OpenAIDecisions(model, key, os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))


PROVIDERS = {"openai": _openai}


def resolve(spec: str) -> Backend:
    provider, _, model = spec.partition(":")
    if provider not in PROVIDERS or not model:
        raise BackendUnavailable(
            f"Unknown decision model {spec!r}: use '<provider>:<model>' with a provider from "
            f"{', '.join(sorted(PROVIDERS))}, such as 'openai:gpt-6-luna'."
        )
    return PROVIDERS[provider](model)
