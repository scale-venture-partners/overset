"""Rules, findings, and the registry they live in.

Three kinds, by what a rule needs:

  structure  the .pptx alone -- offline, milliseconds
  render     a LibreOffice render -- offline, seconds, measured not guessed
  vision     a vision model over the rendered slides -- a judgment, with a
             confidence, opt-in

Codes follow ruff: OVS0xx measured layout, OVS1xx type and colour, OVS2xx
content and structure, OVS3xx deck rhythm, OVS4xx vision.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from overset.engine import Context


@dataclass
class Finding:
    code: str
    message: str
    slide: int | None  # 1-based; None for a whole-deck finding
    severity: str = "warning"
    snippet: str = ""
    confidence: float | None = None  # vision findings only


@dataclass
class Rule:
    code: str
    name: str
    summary: str
    kind: str  # "structure" | "render" | "vision"
    check: Callable[[Context], list[Finding]]
    explanation: str = ""
    default: bool = True
    severity: str = "warning"


REGISTRY: dict[str, Rule] = {}


def rule(code, name, summary, kind, explanation="", default=True, severity="warning"):
    """Register the decorated function as a rule's check."""

    def wrap(fn):
        REGISTRY[code] = Rule(code, name, summary, kind, fn, explanation, default, severity)
        return fn

    return wrap


def finding(ctx: Context, code: str, message: str, slide: int | None, snippet: str = "", **kw) -> Finding:
    return Finding(code, message, slide, REGISTRY[code].severity, snippet, **kw)


def clip(text: str, n: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"
