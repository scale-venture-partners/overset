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

## First run

20 topics (seeded), structure rules only, on the rules as of #48. 5-8 products per topic with a `.pptx`
under 15 MB; NotebookLM, which produces PDFs, is never included.

- Mean Kendall's tau-b: **+0.22** (1 would be overset ordering decks exactly as people did).
- Pairwise agreement, all rules together: **175 of 281 pairs, 62%**.

| Rule | Pairs it tells apart | Agrees with people |
|---|---|---|
| OVS109 saturated-blue-text | 60 | 73% |
| OVS106 emphasis-overuse | 197 | 68% |
| OVS202 image-distorted | 186 | 67% |
| OVS203 too-many-words | 187 | 65% |
| OVS000 invalid-package | 250 | 64% |
| OVS004 frame-off-slide | 144 | 58% |
| OVS212 reading-order | 165 | 50% |
| OVS206 missing-alt-text | 167 | 47% |
| OVS204 missing-slide-title | 91 | 43% |
| OVS108 too-many-colors | 102 | 40% |
| OVS105 too-many-font-families | 129 | 27% |
| OVS101 text-too-small | 76 | 21% |
| OVS207 table-without-header | 55 | 11% |
| OVS107 underline-not-link | 4 | 25% |

## Reading it

- **overset's findings track preference, modestly.** Several rules that measure visible layout and
  typography -- distortion, emphasis, word count, saturated blue, broken packages -- each agree with
  people about two times in three.
- **The accessibility rules are close to chance** (OVS206, OVS212, OVS204): people judged how the decks
  look, and alt text and reading order are invisible. That is not evidence against those rules.
- **Some rules run the other way**: preferred decks have more small text (OVS101), more tables
  without a header row (OVS207), more font families (OVS105) and more colours (OVS108). A likely reading
  is that richer, more polished decks use more tables, more typographic variety and small source lines,
  so these counts measure richness here as much as defects. Worth checking before tuning any of them on
  this evidence.
- **Not significance-tested.** Pairs within a topic share decks, so they are not independent, and 20
  topics is a small sample: treat this as direction, not effect size. Run with more topics before relying
  on it.
- **Deck-level only.** The labels rank whole decks, so this cannot set a slide-level threshold; that
  needs labelled slides (docs/labelling.md, #20).
- **The vision rules were not run** (no API key in the environment that produced this); `--vision`
  adds them.
