"""The `overset` command.

Exit codes follow riff and ruff: 0 clean, 1 findings, 2 a usage or file error.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from overset import __version__
from overset import settings as settings_mod
from overset.engine import lint
from overset.report import render_json, render_text
from overset.rules import load_rules
from overset.rules.base import REGISTRY


def _codes(value: str | None) -> tuple[str, ...]:
    return tuple(c.strip() for c in value.split(",") if c.strip()) if value else ()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="overset",
        description="A deck linter. Measures what each slide actually renders -- text off the slide, out of "
        "its frame, colliding, too small, too faint, off-brand -- and reports it with "
        "ruff-style rule codes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              overset deck.pptx
              overset deck.pptx --no-render          # file-only rules, no LibreOffice needed
              overset deck.pptx --vision             # add the vision-model review
              overset *.pptx --select OVS0 --format json
              overset --list-rules
              overset --explain OVS002
        """),
    )
    p.add_argument("paths", nargs="*", help=".pptx files to lint")
    p.add_argument("--select", help="only these rule codes/prefixes (comma-separated)")
    p.add_argument("--ignore", help="disable these rule codes/prefixes")
    p.add_argument("--extend-select", help="enable these on top of the defaults/select")
    p.add_argument("--no-render", action="store_true", help="skip rules that need a render (no LibreOffice)")
    p.add_argument("--vision", action="store_true", help="run the vision-model rules (OVS4xx)")
    p.add_argument("--config", type=Path, help="path to an overset.toml or pyproject.toml")
    p.add_argument("--keep-render", type=Path, metavar="DIR", help="write the render (PDF, PNGs) here")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("-q", "--quiet", action="store_true", help="findings only, no summary line")
    p.add_argument("--list-rules", action="store_true", help="print the rule catalog and exit")
    p.add_argument("--explain", metavar="CODE", help="print one rule's full explanation and exit")
    p.add_argument("--version", action="version", version=f"overset {__version__}")
    return p


def list_rules(stream=None) -> None:
    stream = stream or sys.stdout
    load_rules()
    for code, r in sorted(REGISTRY.items()):
        mark = " " if r.default else "·"
        print(f"{mark}{code}  {r.kind:<9}  {r.name:<22}  {r.summary}", file=stream)
    print("\n· off by default", file=stream)


def explain(code: str, stream=None) -> int:
    stream = stream or sys.stdout
    load_rules()
    r = REGISTRY.get(code.upper())
    if r is None:
        print(f"overset: no rule {code!r}", file=sys.stderr)
        return 2
    print(f"{r.code} {r.name} ({r.kind}, {r.severity}{'' if r.default else ', off by default'})", file=stream)
    print(f"\n{r.summary}.", file=stream)
    if r.explanation:
        print(f"\n{textwrap.fill(r.explanation, 88)}", file=stream)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_rules:
        list_rules()
        return 0
    if args.explain:
        return explain(args.explain)
    if not args.paths:
        print("overset: no decks given (try --help)", file=sys.stderr)
        return 2

    results = []
    for raw in args.paths:
        path = Path(raw)
        if not path.is_file() or path.suffix.lower() != ".pptx":
            print(f"overset: {raw}: not a .pptx file", file=sys.stderr)
            return 2
        try:
            s = settings_mod.load(args.config, start=path.parent)
        except (ValueError, OSError) as e:
            print(f"overset: config: {e}", file=sys.stderr)
            return 2
        s.select = _codes(args.select) or s.select
        s.ignore = s.ignore + _codes(args.ignore)
        s.extend_select = s.extend_select + _codes(args.extend_select)
        s.render = s.render and not args.no_render
        s.vision = s.vision or args.vision
        workdir = args.keep_render / path.stem if args.keep_render else None
        try:
            results.append(lint(path, s, workdir=workdir))
        except Exception as e:  # an unreadable deck is a file error, not a finding
            print(f"overset: {raw}: {type(e).__name__}: {e}", file=sys.stderr)
            return 2

    if args.format == "json":
        render_json(results)
    else:
        render_text(results, summary=not args.quiet)
    return 1 if any(r.findings for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
