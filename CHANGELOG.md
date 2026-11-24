# Changelog

## 0.2.0 (2026-11-12)

Twenty-two new rules (fifteen on by default), a measured and much quieter set of existing ones, and the tooling to check
rules against real decks. Still alpha: rule codes and config keys may change.

### Upgrading: what will change in your results

Expect **more findings** on most decks. Each item below can be turned off or tuned.

- **Shapes inside groups are checked.** Groups are flattened into their children, so grouped text,
  pictures and frames are checked like any other; messages name a child with its group
  (`'Card 2 > TextBox 5'`).
- **Inherited font sizes are resolved**, from the layout, master and presentation defaults. OVS101
  sees most template text for the first time. Table text that doesn't state a size is still skipped.
- **OVS104 follows WCAG 2.2:** `min-contrast` is now 4.5 for body text (was 3.0) and the new
  `min-contrast-large` (3.0) covers 18pt and up, or 14pt bold. `min-contrast = 3.0` keeps the old
  behaviour.
- **New rules on by default:** the accessibility checks (OVS204-208, OVS212), typography and colour
  (OVS106, OVS107, OVS109, OVS110), and bullet structure (OVS209-211). `ignore` any you don't want.
- **OVS104 reports once per slide and threshold**, listing the low-contrast blocks, instead of once per
  block.
- **An empty title placeholder is OVS204**, not OVS201 (OVS201 still reports it if OVS204 is ignored).
- **OVS206 reports once per slide**, naming each visual that needs alt text.

### New rules, on by default

| Code | Rule |
|---|---|
| OVS106 | A whole paragraph of body text (more than ten words) in bold, italic or capitals |
| OVS107 | Underlined text that isn't a link |
| OVS109 | Text in a vivid saturated blue |
| OVS110 | Saturated red and blue side by side |
| OVS204 | A slide with no title |
| OVS205 | Two slides share a title |
| OVS206 | A picture, chart or graphic with no alt text, or only a file name for one |
| OVS207 | A table with no header row |
| OVS208 | A section left as "Default Section" or "Untitled Section" |
| OVS209 | A list with more than `max-bullets` (4) items at one level |
| OVS210 | A bullet that renders on more than `max-bullet-lines` (2) lines (render) |
| OVS211 | Bullets nested more than `max-bullet-depth` (2) levels |
| OVS212 | A reading order that doesn't follow the layout, or a title not read first |

### New rules, off by default until calibrated

Turn them on with `extend-select`. Their thresholds come from the starter corpus's distribution, not
from labelled data (see `docs/labelling.md`). OVS105 and OVS108 are off because, on Slides-Align, the
decks people preferred used *more* font families and colours (`docs/rank-eval.md`).

| Code | Rule |
|---|---|
| OVS105 | More than `max-font-families` (2) typeface families in the deck, theme and inherited fonts included |
| OVS108 | More than `max-colors` (6) distinct text and fill colours on a slide |
| OVS005 | Shapes that line up with nothing else on the slide (`align-tolerance-pt`, 4) |
| OVS006 | Content weighted heavily to one side (`min-balance`, 0.05) |
| OVS007 | Too little empty space (`min-whitespace`, 25%) |
| OVS008 | A slide far busier than the rest of its deck (`clutter-spread`, 3 MADs; render) |
| OVS009 | Text over a busy background (`max-background-busyness`, 0.19; render) |
| OVS111 | Body text as large as the title (`min-title-ratio`, 1.0) |
| OVS112 | A slide whose fonts or title size the rest of the deck doesn't use |

### Fewer false findings

From running every rule over a corpus of 63 real decks and checking samples of what each one found:

- **OVS202** allows for a small image's pixel rounding: a 28x32 icon's aspect is only known to
  about 4%. 287 findings on the corpus became 132.
- **OVS004** tests the area text can occupy, not the whole frame, so padding over the edge is fine;
  a frame entirely off the slide is said so. 103 became 53.
- **OVS106** counts only body text: headings, labels, source lines and italic quotations are exempt.
- **OVS104** measures the size of text the file doesn't size (table text, which inherits through the
  table style) from the render, so 18pt table text is held to WCAG's 3:1 for large text, not 4.5:1;
  findings are one per slide and threshold. 1,358 findings on the corpus became 514.
- **OVS003** sweeps words top to bottom instead of comparing every pair: a 2,000-word table is
  checked in 13 ms instead of 589 ms, with the same findings.

### Rendering as PowerPoint shows it

- Shrink-to-fit now scales inherited font sizes, and applies the line-spacing reduction to
  paragraphs that don't state their spacing, and to spacing in points. Both used to draw shrunk text
  larger than PowerPoint does, producing false OVS002/OVS003.
- A relative `--keep-render` directory no longer makes LibreOffice hang until the 180s timeout.

### Command line

- `overset deck.pptx | head` (or quitting a pager) no longer ends in a `BrokenPipeError` traceback.

### Configuration

- New: `palette-delta-e` matches the palette perceptually (CIEDE2000) instead of by
  `palette-tolerance`'s RGB distance, which keeps its meaning.
- New thresholds for the new rules: `max-font-families`, `max-colors`, `max-bullets`,
  `max-bullet-lines`, `max-bullet-depth`, `min-reading-order`, `min-contrast-large`, and the
  off-by-default rules' settings above.

### Vision rules

- The OVS4xx rules use a multimodal decision model: yes/no questions per slide and per consecutive
  pair, each answered with a probability. The default `vision-model` is `openai:gpt-6-luna`
  (needs `OPENAI_API_KEY`); `vision-threshold` is now that probability.
- A model id the API rejects stops the run with a clear message (exit 2) instead of a generic error.
- Removed the `vision-input` setting. The `vision` extra installs `httpx`, not pydantic-ai.

### Tooling and docs

- A starter corpus: `scripts/fetch_corpus.py` fetches 63 openly licensed decks (never committed;
  the manifest pins them) and `scripts/run_corpus.py` runs overset over them (`docs/corpus.md`).
- Calibration: `scripts/label_corpus.py` and `scripts/score_labels.py` for precision and recall
  against labelled slides, with threshold sweeps (`docs/labelling.md`).
- `scripts/rank_eval.py` compares overset's findings with people's rankings of AI-made decks
  (`docs/rank-eval.md`): on 60 topics, 62% pairwise agreement (50% is chance).
- CI's render job installs LibreOffice from Ubuntu `main` with cached package lists, so an Ubuntu
  mirror outage no longer blocks it.

## 0.1.0

First public release (alpha). Structure, render and opt-in vision rules; TOML configuration;
text and JSON output.
