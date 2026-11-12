# Do overset's findings track what people prefer?

`scripts/rank_eval.py` (#21) checks overset against human judgement. [Slides-Align](https://huggingface.co/datasets/Yqy6/Slides-Align)
(MIT) has decks from several AI slide products on the same topics, with people's ranking of the
products for each topic. Decks on one topic share their content, so their difference in rank is
mostly design and layout -- what overset measures.

```console
uv run scripts/rank_eval.py --topics 20                       # structure rules: ~0.6 GB of decks, cached
uv run scripts/rank_eval.py --topics 40 --render              # the render rules too (LibreOffice; slow)
uv run --extra vision scripts/rank_eval.py --vision           # the OVS4xx vision rules (OPENAI_API_KEY)
```

Each deck is scored by its findings per slide. Per topic, the script compares overset's order with the
human ranking (Kendall's tau-b), and counts, over every pair of decks overset tells apart, how often the
deck with fewer findings is the one people preferred (pairwise agreement; 50% is chance). It does the
same per rule, to show which rules carry signal.

## Results

Structure rules only, on the rules as of 0.2.0. 5-8 products per topic with a `.pptx` under 15 MB;
NotebookLM, which produces PDFs, is never included. Two seeded samples:

| | 20 topics | 60 topics |
|---|---|---|
| Mean Kendall's tau-b | +0.22 | +0.20 |
| Pairwise agreement, all rules | 62% (175 / 281) | 62% (537 / 868) |

Per rule, 60 topics:

| Rule | Pairs it tells apart | Agrees with people |
|---|---|---|
| OVS109 saturated-blue-text | 153 | 69% |
| OVS000 invalid-package | 772 | 66% |
| OVS202 image-distorted | 576 | 65% |
| OVS203 too-many-words | 547 | 62% |
| OVS106 emphasis-overuse | 584 | 59% |
| OVS209 too-many-bullets | 17 | 59% |
| OVS004 frame-off-slide | 425 | 55% |
| OVS212 reading-order | 516 | 54% |
| OVS206 missing-alt-text | 505 | 44% |
| OVS204 missing-slide-title | 270 | 41% |
| OVS108 too-many-colors | 348 | 32% |
| OVS105 too-many-font-families | 385 | 28% |
| OVS101 text-too-small | 279 | 19% |
| OVS207 table-without-header | 156 | 8% |

(OVS107 and OVS205 tell fewer than 20 pairs apart and are left out.)

## Reading it

- **overset's findings track preference, modestly**, and the result held from 20 topics to 60. Rules
  that measure visible faults -- distortion, saturated blue, broken packages, word count, emphasis --
  each agree with people about two times in three.
- **The accessibility rules sit near chance or below** (OVS206, OVS212, OVS204, OVS207): people judged
  how the decks look, and alt text, reading order and table headers are invisible. That is not evidence
  against them; they stay on.
- **OVS101 runs strongly the other way** (19%): preferred decks have more small text -- source lines,
  captions, dense tables. Text too small to read from the room is still a defect, so it stays on, but its
  findings say "richer deck" as often as "worse deck".
- **OVS105 and OVS108 run the other way too** (28% and 32%, over hundreds of pairs): people preferred
  decks with more font families and more colours. These are style prescriptions (Kosslyn et al.'s "no
  more than two families"), not defects, and the evidence here contradicts them, so **from 0.2.0 both are
  off by default**. Turn them on for a house style that wants them.
- **Not significance-tested.** Pairs within a topic share decks, so they are not independent: treat this
  as direction, not effect size.
- **Deck-level only.** The labels rank whole decks, so this cannot set a slide-level threshold; that
  needs labelled slides (docs/labelling.md, #20).
- **The vision rules were not run** (no API key in the environment that produced this); `--vision`
  adds them.
