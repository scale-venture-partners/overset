#!/usr/bin/env python3
"""Run overset over the starter corpus and summarise the findings per rule and per source.

    uv run scripts/run_corpus.py              # structure rules only: offline, a few seconds
    uv run scripts/run_corpus.py --render     # the render rules too: needs LibreOffice, minutes

Reads data/manifest.csv (written by scripts/fetch_corpus.py) and writes, under data/results/:

- overset_<mode>.json: every deck's findings, and any deck overset could not read
- overset_<mode>_summary.txt: findings and decks per rule, split by source

Exits 1 if overset crashed on a deck: the corpus doubles as a crash and regression check.
A deck that python-pptx cannot load is reported by OVS000, not as a crash.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

from overset.engine import lint
from overset.rules import load_rules
from overset.rules.base import REGISTRY
from overset.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


def run(data: Path, render: bool) -> tuple[list[dict], list[dict]]:
    with (data / "manifest.csv").open(newline="", encoding="utf-8") as f:
        decks = list(csv.DictReader(f))
    results, crashes = [], []
    for n, deck in enumerate(decks, start=1):
        path = data / "pptx" / deck["file"]
        print(f"[{n}/{len(decks)}] {deck['file']}", file=sys.stderr)
        try:
            result = lint(path, Settings(render=render))
        except Exception as e:  # a crash is what this run is for finding
            crashes.append({"file": deck["file"], "source": deck["source"], "error": f"{type(e).__name__}: {e}",
                            "traceback": traceback.format_exc()})  # fmt: skip
            continue
        results.append(
            {
                "file": deck["file"],
                "source": deck["source"],
                "slides": result.slides,
                "rendered": result.rendered,
                "skipped": result.skipped,
                "notes": result.notes,
                "findings": [asdict(f) for f in result.findings],
            }
        )
    return results, crashes


def summary(results: list[dict], crashes: list[dict], render: bool) -> str:
    load_rules()
    sources = sorted({r["source"] for r in results} | {c["source"] for c in crashes})
    findings = collections.Counter()
    decks = collections.defaultdict(set)
    by_source = collections.Counter()
    for r in results:
        for f in r["findings"]:
            findings[f["code"]] += 1
            decks[f["code"]].add(r["file"])
            by_source[(f["code"], r["source"])] += 1
    flagged = sum(1 for r in results if r["findings"])
    lines = [
        f"overset over {len(results) + len(crashes)} decks ({'with' if render else 'without'} the render rules): "
        f"{sum(findings.values())} findings; {flagged} of {len(results)} decks have at least one.",
        "",
        "| Rule | Findings | Decks | " + " | ".join(sources) + " |",
        "|---|---|---|" + "---|" * len(sources),
    ]
    for code in sorted(findings):
        name = REGISTRY[code].name if code in REGISTRY else ""
        per = " | ".join(str(by_source[(code, s)]) for s in sources)
        lines.append(f"| {code} {name} | {findings[code]} | {len(decks[code])} | {per} |")
    ran = [c for c in sorted(REGISTRY) if REGISTRY[c].default and (render or REGISTRY[c].kind == "structure")]
    silent = [c for c in ran if c not in findings]
    off = [c for c in sorted(REGISTRY) if not REGISTRY[c].default]
    lines += ["", f"Rules with no findings: {', '.join(silent) or 'none'}.",
              f"Off by default, so not run: {', '.join(off)}."]  # fmt: skip
    if crashes:
        lines += ["", f"overset crashed on {len(crashes)} decks:"]
        lines += [f"- {c['file']}: {c['error']}" for c in crashes]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--data", type=Path, default=ROOT / "data", help="the corpus directory (default: data/)")
    p.add_argument("--render", action="store_true", help="also run the render rules (needs LibreOffice)")
    args = p.parse_args(argv)
    if not (args.data / "manifest.csv").exists():
        raise SystemExit(f"No {args.data / 'manifest.csv'}: run scripts/fetch_corpus.py first.")
    results, crashes = run(args.data, args.render)
    out = args.data / "results"
    out.mkdir(parents=True, exist_ok=True)
    mode = "render" if args.render else "norender"
    (out / f"overset_{mode}.json").write_text(json.dumps({"decks": results, "crashes": crashes}, indent=1))
    text = summary(results, crashes, args.render)
    (out / f"overset_{mode}_summary.txt").write_text(text)
    print(text)
    return 1 if crashes else 0


if __name__ == "__main__":
    sys.exit(main())
