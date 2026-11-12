# Labelling slides to calibrate overset

overset's thresholds -- OVS202's 2% distortion, OVS203's 90 words, OVS005-OVS009's off-by-default
limits -- come from the literature or from the starter corpus's distribution, not from labelled data.
No public dataset labels the defects overset measures, per slide, at a usable scale. This is how to
make one, and how to score overset against it (#20).

## The loop

```console
uv run --group corpus scripts/fetch_corpus.py                       # the decks
uv run scripts/label_corpus.py --rules OVS202,OVS004 --per-rule 40   # data/labels/sheet.csv
# ... label the sheet ...
uv run scripts/score_labels.py data/labels/sheet.csv                 # precision and recall per rule
uv run scripts/score_labels.py data/labels/sheet.csv --sweep OVS202:max_aspect_distortion=0.02,0.05,0.1
```

`label_corpus.py` picks, per rule, slides overset reported and an equal number it did not, with a
fixed seed, and shuffles them so the order gives nothing away. Labelling only reported slides would
measure precision and leave recall unknown.

## The sheet

| Column | Filled by | Meaning |
|---|---|---|
| `file`, `slide` | script | the deck (as in `data/manifest.csv`) and the 1-based slide |
| `code` | script | the rule being judged |
| `overset`, `message` | script | whether overset reported it, and what it said. **Hide these columns while labelling**: they bias the judgement |
| `defect` | labeller | `yes`, `no` or `unsure` |
| `labeller` | labeller | initials |
| `note` | labeller | anything that explains an odd call |

`unsure` rows are left out of the scores; if more than about one in ten rows of a rule are unsure,
its definition below needs sharpening, not more labels.

## What counts as a defect

Judge the slide as the audience sees it: open the deck in PowerPoint (not a preview, which may lay
text out differently), at full screen, from a normal viewing distance. Ask the question for the rule,
not whether the slide is good.

| Rule | A defect is ... | Not a defect |
|---|---|---|
| OVS001-OVS003 | text cut off by the slide edge, spilling out of its box, or drawn over other text | a box larger than its text; text that touches but does not overlap |
| OVS004 | text that reaches the edge or is off the slide | an empty margin over the edge |
| OVS101 | text you cannot read comfortably from the back of a meeting room | footnotes and source lines you are not meant to read in the room |
| OVS104 | text you have to strain to separate from its background | decorative text meant to be faint (a watermark) |
| OVS106 | a whole sentence or more in bold, italics or capitals, so nothing stands out | headings, labels, quotations |
| OVS202 | a picture that looks squashed or stretched -- faces, logos, circles, text in the image | abstract or decorative art where no one could tell |
| OVS204-OVS206 | as Microsoft's Accessibility Checker would report it | a slide whose title is intentionally hidden (a full-bleed image slide with a title placeholder off-slide) |
| OVS209-OVS211 | a list too long, a bullet too long, or a nest too deep to take in while the speaker talks | a slide meant to be read, not presented (an appendix) |
| OVS005-OVS009 | a slide that looks misaligned, lopsided, crammed, cluttered, or has text over a busy picture | a deliberately asymmetric or dense design that still reads easily |

For other rules, use the rule's explanation (`overset --explain OVS…`) as the definition.

## Who labels, and disagreements

- **Two labellers per sheet**, working independently on copies, each filling `defect` and
  `labeller`. One should not be the person who wrote the rule.
- **Measure agreement first**: Cohen's kappa per rule. Below about 0.6 the definition is ambiguous;
  rewrite it here and relabel that rule before scoring.
- **Resolve disagreements together**, with a third person deciding any that stay split, and record
  the outcome in `note`. Score against the resolved sheet.
- Keep sheets under `data/labels/` (gitignored, like the decks). Commit the scores and the chosen
  thresholds, with the date and the sheet's size, to `docs/corpus.md`.

## Other labelled sets

`score_labels.py` scores any sheet in this format. The dataset survey's pptx-format-error-200 (200
original/perturbed slide pairs, about 60 hand-checked, covering overlap, overflow, font size,
alignment, out-of-bounds and density) could be converted to it for a first check of OVS001-OVS004,
OVS101 and OVS203. Its licence is not stated, so it is for internal use only and is not fetched by
any script here.
