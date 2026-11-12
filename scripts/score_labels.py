#!/usr/bin/env python3
"""Score overset against labelled slides: precision and recall per rule, and optionally across a
threshold.

    uv run scripts/score_labels.py data/labels/sheet.csv
    uv run scripts/score_labels.py data/labels/sheet.csv --sweep OVS202:max_aspect_distortion=0.02,0.05,0.1

Labels are the CSV scripts/label_corpus.py writes, filled in: one row per (deck file, slide, rule)
with `defect` yes or no (unsure rows are left out). overset is run afresh on the labelled decks, so
the scores reflect the current code and settings, not the sheet's `overset` column. A sweep re-runs
one rule at each value of one setting, which is how a threshold is chosen from data (#20).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

from overset.engine import lint
from overset.settings import Settings

ROOT = Path(__file__).resolve().parent.parent


def read_labels(path: Path) -> dict[tuple[str, int, str], bool]:
    labels = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            verdict = row["defect"].strip().lower()
            if verdict in ("yes", "no"):
                labels[(row["file"], int(row["slide"]), row["code"])] = verdict == "yes"
    return labels


def predictions(labels: dict, data: Path, settings: Settings) -> dict[tuple[str, int, str], bool]:
    """Whether overset reports each labelled (file, slide, rule) under these settings."""
    codes = sorted({c for _, _, c in labels})
    settings.select = tuple(codes)
    reported = set()
    for file in sorted({f for f, _, _ in labels}):
        result = lint(data / "pptx" / file, settings)
        reported |= {(file, x.slide, x.code) for x in result.findings if x.slide is not None}
    return {k: k in reported for k in labels}


def scores(labels: dict, predicted: dict) -> dict[str, dict]:
    counts = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
    for key, truth in labels.items():
        guess = predicted[key]
        cell = "tp" if truth and guess else "fp" if guess else "fn" if truth else "tn"
        counts[key[2]][cell] += 1
    out = {}
    for code, c in sorted(counts.items()):
        precision = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else None
        recall = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else None
        out[code] = {**c, "precision": precision, "recall": recall}
    return out


def table(rows: dict[str, dict], label: str = "Rule") -> str:
    def pct(v):
        return "-" if v is None else f"{v:.0%}"

    lines = [f"| {label} | Precision | Recall | TP | FP | FN | TN |", "|---|---|---|---|---|---|---|"]
    for name, s in rows.items():
        lines.append(
            f"| {name} | {pct(s['precision'])} | {pct(s['recall'])} | {s['tp']} | {s['fp']} | {s['fn']} | {s['tn']} |"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("labels", type=Path, help="a filled-in labelling sheet")
    p.add_argument("--data", type=Path, default=ROOT / "data")
    p.add_argument("--render", action="store_true", help="run the render rules too (LibreOffice)")
    p.add_argument("--sweep", help="RULE:setting=v1,v2,... -- score RULE at each value of the setting")
    args = p.parse_args(argv)
    labels = read_labels(args.labels)
    if not labels:
        raise SystemExit(f"No yes/no labels in {args.labels}.")
    if args.sweep:
        code, _, spec = args.sweep.partition(":")
        name, _, values = spec.partition("=")
        rule_labels = {k: v for k, v in labels.items() if k[2] == code}
        if not rule_labels:
            raise SystemExit(f"No labels for {code}.")
        rows = {}
        for raw in values.split(","):
            default = getattr(Settings(), name)
            value = (type(default) if default is not None else float)(float(raw))
            settings = Settings(render=args.render, **{name: value})
            rows[f"{name} = {raw.strip()}"] = scores(rule_labels, predictions(rule_labels, args.data, settings))[code]
        print(f"{code}, {len(rule_labels)} labelled slides\n")
        print(table(rows, label="Setting"))
    else:
        result = scores(labels, predictions(labels, args.data, Settings(render=args.render)))
        print(f"{len(labels)} labelled slides\n")
        print(table(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
