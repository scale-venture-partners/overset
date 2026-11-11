#!/usr/bin/env python3
"""Write a labelling sheet: slides of the starter corpus to judge, rule by rule.

    uv run scripts/label_corpus.py --rules OVS202,OVS004 --per-rule 40     # writes data/labels/sheet.csv

For each rule the sheet holds slides overset reported (to measure precision) and, in equal number,
slides it did not (to measure recall), drawn with a fixed seed. A labeller fills in the `defect`
column -- yes, no or unsure -- following docs/labelling.md, and scripts/score_labels.py scores
overset against the result. Rules that are off by default are run for the sheet all the same.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

from overset.engine import lint
from overset.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
SEED = 20
COLUMNS = ["file", "slide", "code", "overset", "message", "defect", "labeller", "note"]


def findings_by_slide(data: Path, codes: list[str], render: bool) -> tuple[dict, list[tuple[str, int]]]:
    """{(file, slide, code): message} for every finding, and every (file, slide) in the corpus."""
    with (data / "manifest.csv").open(newline="", encoding="utf-8") as f:
        decks = list(csv.DictReader(f))
    found, slides = {}, []
    settings = Settings(select=tuple(codes), render=render)
    for deck in decks:
        try:
            result = lint(data / "pptx" / deck["file"], settings)
        except Exception as e:  # a deck overset can't read has no slides to label
            print(f"skipping {deck['file']}: {type(e).__name__}", file=sys.stderr)
            continue
        slides += [(deck["file"], n) for n in range(1, result.slides + 1)]
        for x in result.findings:
            if x.slide is not None:
                found.setdefault((deck["file"], x.slide, x.code), x.message)
    return found, slides


def sheet(found: dict, slides: list, codes: list[str], per_rule: int, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for code in codes:
        hits = sorted(k for k in found if k[2] == code)
        hit_slides = {(f, s) for f, s, _ in hits}
        misses = sorted(s for s in slides if s not in hit_slides)
        chosen = rng.sample(hits, min(per_rule // 2, len(hits)))
        chosen_misses = rng.sample(misses, min(per_rule - len(chosen), len(misses)))
        rows += [
            {"file": f, "slide": s, "code": c, "overset": "yes", "message": found[(f, s, c)]} for f, s, c in chosen
        ]
        rows += [{"file": f, "slide": s, "code": code, "overset": "no", "message": ""} for f, s in chosen_misses]
    # Shuffled, so a labeller can't tell overset's verdict from the order; the column is there for scoring.
    rng.shuffle(rows)
    return [{c: r.get(c, "") for c in COLUMNS} for r in rows]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rules", required=True, help="comma-separated rule codes to label")
    p.add_argument("--per-rule", type=int, default=40, help="slides per rule, half reported and half not")
    p.add_argument("--render", action="store_true", help="the rules need the render (LibreOffice)")
    p.add_argument("--data", type=Path, default=ROOT / "data")
    p.add_argument("--out", type=Path, default=None, help="default: data/labels/sheet.csv")
    args = p.parse_args(argv)
    codes = [c.strip() for c in args.rules.split(",") if c.strip()]
    found, slides = findings_by_slide(args.data, codes, args.render)
    rows = sheet(found, slides, codes, args.per_rule)
    out = args.out or args.data / "labels" / "sheet.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} slides to label in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
