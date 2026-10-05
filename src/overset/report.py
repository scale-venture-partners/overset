"""Render results as human text or JSON."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

from overset.engine import Result

_COLOR = {"error": "\033[31m", "warning": "\033[33m", "info": "\033[36m"}
_DIM, _BOLD, _RESET = "\033[2m", "\033[1m", "\033[0m"


def _use_color(stream) -> bool:
    return stream.isatty() and "NO_COLOR" not in os.environ


def render_text(results: list[Result], stream=None, summary: bool = True) -> None:
    stream = stream or sys.stdout
    color = _use_color(stream)
    dim, bold, reset = (_DIM, _BOLD, _RESET) if color else ("", "", "")
    counts: Counter = Counter()
    for result in results:
        for note in result.notes:
            print(f"{dim}{result.path}: {note}{reset}", file=stream)
        for f in result.sorted():
            counts[f.code] += 1
            where = f"slide {f.slide}" if f.slide else "deck"
            conf = f" p={f.confidence:.2f}" if f.confidence is not None else ""
            code = f"{_COLOR.get(f.severity, '')}{f.code}{reset}" if color else f.code
            print(f"{bold}{result.path}{reset}:{where}: {code} {f.message}{dim}{conf}{reset}", file=stream)
            if f.snippet:
                print(f"    {dim}{f.snippet}{reset}", file=stream)
    if summary:
        total = sum(counts.values())
        files = len(results)
        if not total:
            print(f"All clear: {files} deck{'s' if files != 1 else ''} checked.", file=stream)
        else:
            top = ", ".join(f"{c} ×{n}" for c, n in counts.most_common())
            print(
                f"\n{total} finding{'s' if total != 1 else ''} in {files} deck{'s' if files != 1 else ''} ({top}).",
                file=stream,
            )


def render_json(results: list[Result], stream=None) -> None:
    stream = stream or sys.stdout
    out = []
    for r in results:
        out.append(
            {
                "path": str(r.path),
                "slides": r.slides,
                "rendered": r.rendered,
                "skipped": r.skipped,
                "notes": r.notes,
                "findings": [
                    {
                        "code": f.code,
                        "message": f.message,
                        "slide": f.slide,
                        "label": f"slide {f.slide}" if f.slide else None,
                        "severity": f.severity,
                        "snippet": f.snippet,
                        "confidence": f.confidence,
                    }
                    for f in r.sorted()
                ],
            }
        )
    json.dump(out, stream, indent=2)
    stream.write("\n")
