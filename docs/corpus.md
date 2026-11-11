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

Structure rules only, at the commit that added the corpus. Counts are findings; "Decks" is how many decks
have at least one.

```
overset over 63 decks (without the render rules): 4567 findings; 63 of 63 decks have at least one.

| Rule | Findings | Decks | Datacluster | Slides-Align | Zenodo10K |
|---|---|---|---|---|---|
| OVS000 invalid-package | 165 | 10 | 0 | 161 | 4 |
| OVS004 frame-off-slide | 103 | 24 | 0 | 3 | 100 |
| OVS101 text-too-small | 231 | 22 | 97 | 29 | 105 |
| OVS105 too-many-font-families | 21 | 21 | 0 | 8 | 13 |
| OVS106 emphasis-overuse | 619 | 53 | 166 | 258 | 195 |
| OVS107 underline-not-link | 24 | 11 | 0 | 8 | 16 |
| OVS201 empty-placeholder | 62 | 11 | 0 | 0 | 62 |
| OVS202 image-distorted | 287 | 25 | 0 | 199 | 88 |
| OVS203 too-many-words | 165 | 41 | 32 | 40 | 93 |
| OVS204 missing-slide-title | 583 | 46 | 76 | 257 | 250 |
| OVS205 duplicate-slide-title | 182 | 20 | 0 | 0 | 182 |
| OVS206 missing-alt-text | 1978 | 56 | 64 | 1111 | 803 |
| OVS207 table-without-header | 35 | 9 | 0 | 21 | 14 |
| OVS209 too-many-bullets | 90 | 26 | 0 | 0 | 90 |
| OVS211 bullet-depth | 22 | 7 | 0 | 0 | 22 |

Rules with no findings: OVS102, OVS103, OVS208, OVS301.
```

No deck made overset crash. Observations for #22:

- **OVS106 (emphasis-overuse)** fires on most decks. A sample of its findings shows real overuse, and
  also italic source lines ("Source: IMF, ...") and bold text boxes used as headings, which the rule
  only exempts when they are title placeholders. Worth narrowing before it stays on by default.
- **OVS206 (missing-alt-text)** dominates, with about a quarter of its findings for alt text that is a
  file name. That matches Microsoft's checker, but on a corpus of decks nobody wrote alt text for it
  is mostly a count of pictures.
- **OVS000** is almost all Slides-Align, as in #22's survey: parts declared in `[Content_Types].xml`
  but missing from the package.
