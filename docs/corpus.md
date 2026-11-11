# The starter corpus

A small, fixed set of real `.pptx` decks to run overset over. The rules' unit tests build decks in
code, each with one defect. This corpus shows what the rules do on decks nobody built for them:
which rules fire, how often, whether any are mostly noise, and whether anything makes overset crash.
It is the data #22 (triage), #20 (calibration) and #17 (layout thresholds) need.

## Fetching it

```console
uv run --group corpus scripts/fetch_corpus.py   # about 190 MB, a couple of minutes the first time
uv run scripts/run_corpus.py                    # structure rules: about 20 seconds
uv run scripts/run_corpus.py --render           # all rules but vision: needs LibreOffice, much longer
```

`fetch_corpus.py` downloads the decks listed in `data/manifest.csv` into `data/pptx/` and checks each
one's SHA-256. A deck that is already there and intact is skipped, so a second run downloads nothing.
`--reselect` lists the sources again and picks the sample afresh; the choice is seeded, so it picks the
same decks while the sources are unchanged. `run_corpus.py` writes every finding to
`data/results/overset_<mode>.json` and a per-rule, per-source table to
`data/results/overset_<mode>_summary.txt`, and exits 1 if overset crashed on any deck.

The manifest is committed; the decks and results are not (`.gitignore`). The `corpus` CI workflow
does the same on demand (Actions, "Corpus", Run workflow).

## What is in it

63 decks, 1248 slides, 191 MB, each at most 8 MB. The sources are Hugging Face datasets:

| Source | Decks | What they are | Licence |
|---|---|---|---|
| [Zenodo10K](https://huggingface.co/datasets/Forceless/Zenodo10K) | 42 | Real academic and project decks published on Zenodo: six from each year 2018-2024 | Each deck's own, CC-BY-4.0 or CC0 only; DOI and title in the manifest |
| [Slides-Align](https://huggingface.co/datasets/Yqy6/Slides-Align) | 18 | Decks made by AI slide products: three from each of six products with `.pptx` output | MIT (the dataset); the decks are outputs of commercial products |
| [Datacluster multi-domain PowerPoint](https://huggingface.co/datasets/Dataclusterlabspvtltd/multi-domain-powerpoint-presentation-dataset) | 3 | Topic decks; the three smallest | CC-BY-4.0 |

Slides-Align products without `.pptx` output (NotebookLM produces PDFs) are left out. The products
are picked at random, seeded, from those with at least three decks under the size cap.

## Licensing

- **Fetched on demand, never committed.** Decks are downloaded from their sources when needed; the
  repository holds only the manifest, with each deck's source, licence, URL and (for Zenodo) DOI, so
  attribution travels with the list.
- **Used here, safe to redistribute with attribution:** Zenodo10K decks filtered to CC-BY-4.0 or CC0,
  Datacluster, Slides-Align.
- **Internal use only until their terms are clear, and not fetched by the script:**
  pptx-format-error-200 (no licence stated), SlidesBench and the derived preference_ppt (a SlideShare
  scrape), pptx_collection_templates (apparently commercial template sites), and the CC0 claims of
  ppt4web and znanio (an uploader's claim about scraped files).

## Baseline: overset on the corpus

Structure rules only, after the triage below. Counts are findings; "Decks" is how many decks have at
least one.

```
overset over 63 decks (without the render rules): 2554 findings; 63 of 63 decks have at least one.

| Rule | Findings | Decks | Datacluster | Slides-Align | Zenodo10K |
|---|---|---|---|---|---|
| OVS000 invalid-package | 165 | 10 | 0 | 161 | 4 |
| OVS004 frame-off-slide | 53 | 20 | 0 | 2 | 51 |
| OVS101 text-too-small | 231 | 22 | 97 | 29 | 105 |
| OVS105 too-many-font-families | 21 | 21 | 0 | 8 | 13 |
| OVS106 emphasis-overuse | 108 | 28 | 38 | 14 | 56 |
| OVS107 underline-not-link | 24 | 11 | 0 | 8 | 16 |
| OVS201 empty-placeholder | 62 | 11 | 0 | 0 | 62 |
| OVS202 image-distorted | 132 | 25 | 0 | 45 | 87 |
| OVS203 too-many-words | 165 | 41 | 32 | 40 | 93 |
| OVS204 missing-slide-title | 583 | 46 | 76 | 257 | 250 |
| OVS205 duplicate-slide-title | 182 | 20 | 0 | 0 | 182 |
| OVS206 missing-alt-text | 681 | 56 | 60 | 224 | 397 |
| OVS207 table-without-header | 35 | 9 | 0 | 21 | 14 |
| OVS209 too-many-bullets | 90 | 26 | 0 | 0 | 90 |
| OVS211 bullet-depth | 22 | 7 | 0 | 0 | 22 |

Rules with no findings: OVS102, OVS103, OVS208, OVS301.
```

No deck made overset crash.

## Triage (#22)

Each rule that fired a lot was checked against a sample of its findings, and fixed where the findings
were measurement artifacts rather than defects.

- **OVS000 (invalid package): kept as an error.** Almost all from Slides-Align: parts declared in
  `[Content_Types].xml` but missing from the package. A deck that lists parts it does not contain is a
  broken package, whatever PowerPoint tolerates.
- **OVS202 (image distorted): 287 to 132.** Over half the findings were tiny images (icons of 20-40
  pixels, 2-pixel rules) whose aspect ratio is only known to the nearest pixel: a 28x32 icon's to about
  4%, a 2-pixel line's to 25-33%. Distortion within that rounding is no longer counted. Of the rest, 85
  are stretched 10% or more, all PNG or JPEG. Some are decorative template art (abstract waves squeezed
  into a corner), where the stretch is real but invisible; the rule cannot tell those from photos. The
  2% tolerance stays: only 20 findings fall between 2% and 5% on images large enough to measure, a set
  small enough to label by hand for #20.
- **OVS004 (frame off slide): 103 to 53.** Half the findings were frames less than 10pt past the edge,
  where only the frame's inner margin (0.1in by default) overhung; the text could not reach the edge.
  The rule now tests the area text can occupy. Frames entirely off the slide, invisible in the slide
  show (often parked notes), are reported as such.
- **OVS201 (empty placeholder): kept.** The sample is content, body, subtitle and picture placeholders
  left empty: what PowerPoint shows as "Click to add text" to anyone editing the deck.
- **OVS101 (text too small): kept.** The 97 Datacluster findings are body and source text at 8.2-9.6pt,
  sizes shrink-to-fit reached, now measured since inherited sizes are resolved (#6). Real small text.
- **OVS106 (emphasis overuse): 619 to 108.** Most findings were not body text: bold headings and
  callouts in text boxes, italic source lines ("Source: IMF, ..."), italic quotations and closing
  slides ("THANK YOU FOR WATCHING"). The rule now counts only paragraphs of more than ten words, and
  exempts source, note and caption lines and italic quotations. What is left is whole sentences of body
  text in bold or italic.
- **OVS206 (missing alt text): 1,978 to 681, on by default.** Missing alt text is an error in
  Microsoft's Accessibility Checker, so the rule stays on, but a slide of ten unlabelled icons is one
  problem, not ten: it now reports once per slide, naming each visual.
