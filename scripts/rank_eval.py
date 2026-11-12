#!/usr/bin/env python3
"""Do overset's findings order AI-made decks the way people do? (#21)

    uv run scripts/rank_eval.py                 # 20 topics, structure rules: downloads ~0.5 GB once
    uv run scripts/rank_eval.py --topics 40 --render
    uv run --extra vision scripts/rank_eval.py --vision   # adds the OVS4xx rules (needs OPENAI_API_KEY)

Slides-Align (Yqy6/Slides-Align, MIT) has decks from several AI slide products on the same topics, and
people's ranking of the products within each topic. Decks on one topic share their content, so a
difference in rank is mostly a difference in design and layout -- what overset claims to measure.

For each topic, each product's deck gets a score: overset's findings per slide (fewer is better), in
total and per rule. The script reports, over topics:

- Kendall's tau-b between the human ranking and overset's: 1 when overset orders the decks exactly as
  people did, 0 when unrelated, -1 when reversed;
- pairwise agreement: of the pairs of decks overset tells apart, the share where the one with fewer
  findings per slide is the one people preferred (50% is chance);
- the same pairwise agreement per rule, which shows which rules carry signal and which are noise.

The labels are deck-level rankings, so this can say whether overset's findings track preference; it
cannot calibrate a slide-level threshold (that is #20's). Decks are downloaded to data/rank/
(gitignored); results go to data/rank/results.json and are printed as a table.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import fetch_corpus as fc

from overset.engine import lint
from overset.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
SEED = 21
MAX_BYTES = 15 * 2**20
MIN_PRODUCTS = 5
# The rankings name products slightly differently from the dataset's folders.
FOLDERS = {"Skywork": "Skyworks", "Skywork-Banana": "Skyworks-Banana"}


def rankings() -> dict[tuple[str, str], dict[str, int]]:
    """{(category, topic): {product: rank}}, rank 1 best."""
    body, _ = fc.get(f"{fc.HF}/datasets/{fc.SLIDES_ALIGN}/resolve/main/Slides-Align.json")
    out: dict = defaultdict(dict)
    for r in json.loads(body)["results"]:
        out[(r["difficulty"], r["topic"])][r["product"]] = int(r["rank"])
    return dict(out)


def deck_index(products: list[str], cache: Path) -> dict[tuple[str, str], dict]:
    """{(product folder, topic folder): the topic's .pptx}, listed once and cached."""
    if cache.exists():
        raw = json.loads(cache.read_text())
    else:
        raw = {}
        for product in products:
            print(f"Listing {product} ...", file=sys.stderr)
            for f in fc.tree(fc.SLIDES_ALIGN, product, recursive=True):
                parts = f.path.split("/")
                if len(parts) == 4 and f.path.lower().endswith(".pptx"):
                    raw[f"{parts[0]}/{parts[2]}"] = {"path": f.path, "size": f.size, "sha256": f.sha256}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw))
    return {tuple(k.split("/", 1)): v for k, v in raw.items()}


def choose(ranks: dict, index: dict, n: int, rng: random.Random) -> dict[tuple[str, str], dict[str, dict]]:
    """Topics where at least MIN_PRODUCTS ranked products have a .pptx under the size cap."""
    usable = {}
    for (category, topic), by_product in sorted(ranks.items()):
        decks = {}
        for product in by_product:
            entry = index.get((FOLDERS.get(product, product), topic))
            if entry and entry["size"] <= MAX_BYTES:
                decks[product] = entry
        if len(decks) >= MIN_PRODUCTS:
            usable[(category, topic)] = decks
    picked = rng.sample(sorted(usable), min(n, len(usable)))
    return {k: usable[k] for k in sorted(picked)}


def tau_b(x: list[float], y: list[float]) -> float | None:
    """Kendall's tau-b, which allows ties."""
    concordant = discordant = ties_x = ties_y = 0
    for i, j in combinations(range(len(x)), 2):
        dx, dy = x[i] - x[j], y[i] - y[j]
        if dx == 0 and dy == 0:
            continue
        if dx == 0:
            ties_x += 1
        elif dy == 0:
            ties_y += 1
        elif (dx > 0) == (dy > 0):
            concordant += 1
        else:
            discordant += 1
    denominator = ((concordant + discordant + ties_x) * (concordant + discordant + ties_y)) ** 0.5
    return (concordant - discordant) / denominator if denominator else None


def agreement(pairs: list[tuple[float, float]]) -> tuple[int, int]:
    """(agreeing, decided) over (human rank difference, overset score difference) pairs: a pair
    agrees when the deck people ranked better has fewer findings per slide."""
    decided = [(h, s) for h, s in pairs if s != 0 and h != 0]
    return sum(1 for h, s in decided if (h > 0) == (s > 0)), len(decided)


def evaluate(topics: dict, data: Path, settings: Settings, ranks: dict) -> dict:
    per_topic, pairs_total, pairs_rule = [], [], defaultdict(list)
    for (category, topic), decks in topics.items():
        scored = {}
        for product, entry in decks.items():
            path = data / "pptx" / product / f"{topic}.pptx"
            if not path.exists() or fc.sha256(path) != entry["sha256"]:
                fc.download(fc.Remote(fc.SLIDES_ALIGN, entry["path"], entry["size"], entry["sha256"]).url,
                            path, entry["sha256"])  # fmt: skip
            try:
                result = lint(path, settings)
            except Exception as e:  # a deck overset can't read can't be ranked
                print(f"skipping {path}: {type(e).__name__}", file=sys.stderr)
                continue
            slides = max(result.slides, 1)
            by_rule = defaultdict(int)
            for f in result.findings:
                by_rule[f.code] += 1
            scored[product] = (sum(by_rule.values()) / slides, {c: n / slides for c, n in by_rule.items()})
        products = sorted(scored)
        if len(products) < 3:
            continue
        human = [ranks[(category, topic)][p] for p in products]
        total = [scored[p][0] for p in products]
        per_topic.append({"category": category, "topic": topic, "products": products, "human_rank": human,
                          "findings_per_slide": total, "tau_b": tau_b(human, total)})  # fmt: skip
        rules = {c for p in products for c in scored[p][1]}
        for i, j in combinations(range(len(products)), 2):
            dh = human[i] - human[j]
            pairs_total.append((dh, total[i] - total[j]))
            for code in rules:
                a, b = scored[products[i]][1].get(code, 0), scored[products[j]][1].get(code, 0)
                pairs_rule[code].append((dh, a - b))
    taus = [t["tau_b"] for t in per_topic if t["tau_b"] is not None]
    return {
        "topics": per_topic,
        "mean_tau_b": sum(taus) / len(taus) if taus else None,
        "agreement": agreement(pairs_total),
        "agreement_by_rule": {c: agreement(p) for c, p in sorted(pairs_rule.items())},
    }


def report(result: dict) -> str:
    agree, decided = result["agreement"]
    lines = [
        f"{len(result['topics'])} topics; mean Kendall tau-b {result['mean_tau_b']:+.2f} "
        "(1: overset orders decks as people did; 0: unrelated)",
        f"pairwise agreement, all rules: {agree}/{decided} = {agree / decided:.0%} (50% is chance)" if decided else "",
        "",
        "| Rule | Pairs it tells apart | Agrees with people |",
        "|---|---|---|",
    ]
    rows = sorted(result["agreement_by_rule"].items(), key=lambda kv: -kv[1][1])
    for code, (a, d) in rows:
        if d:
            lines.append(f"| {code} | {d} | {a / d:.0%} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--topics", type=int, default=20, help="topics to sample (default 20)")
    p.add_argument("--render", action="store_true", help="also the render rules (LibreOffice; slow)")
    p.add_argument("--vision", action="store_true", help="also the OVS4xx vision rules (OPENAI_API_KEY)")
    p.add_argument("--data", type=Path, default=ROOT / "data" / "rank")
    args = p.parse_args(argv)
    ranks = rankings()
    products = sorted({FOLDERS.get(p, p) for r in ranks.values() for p in r})
    index = deck_index(products, args.data / "listing.json")
    topics = choose(ranks, index, args.topics, random.Random(SEED))
    settings = Settings(render=args.render, vision=args.vision)
    result = evaluate(topics, args.data, settings, ranks)
    (args.data / "results.json").write_text(json.dumps(result, indent=1))
    print(report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
