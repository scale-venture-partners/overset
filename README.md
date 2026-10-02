# overset

A deck linter. It renders a `.pptx` and **measures** what each slide actually
shows: text off the slide, text spilling out of its frame, frames colliding,
type too small, text too faint, fonts and colours off the brand. It reports
with ruff-style rule codes you can select, ignore, and configure.

```console
$ overset product_overview.pptx --config examples/brand.toml
product_overview.pptx:slide 2: OVS002 text spills out of 'text105'
    Up 42% year over
product_overview.pptx:slide 3: OVS203 167 words, over 90
product_overview.pptx:slide 4: OVS203 99 words, over 90

3 findings in 1 deck (OVS203 ×2, OVS002 ×1).
```

*Overset* is the typesetter's word for text that doesn't fit its frame.

It is the companion to [riff](https://github.com/scale-venture-partners/riff),
which lints a deck's *words*. overset lints what the words *look like* on the
slide. 
## Why measure

A model reviewing its own slides misses things. A generated deck that the model had inspected slide by
slide still shipped with a title ran off the top of the slide and a caption had slid out of its
highlight pill. Both are measurable: LibreOffice renders the deck, and
poppler's `pdftotext -bbox-layout` reports every word's box, including words
pushed past the slide edge, which come back with negative coordinates. overset
compares those boxes with the frames in the file.

## Install

```console
uv tool install git+https://github.com/scale-venture-partners/overset
uv tool install "overset[vision] @ git+https://github.com/scale-venture-partners/overset"   # + vision rules
```

The render rules need **LibreOffice** and **poppler** on PATH
(`brew install --cask libreoffice && brew install poppler`, or
`apt install libreoffice-impress poppler-utils`). Without them,
`--no-render` runs the file-only rules, and a failed render is reported:
the render rules are listed as *skipped*, never as passed.

## Usage

```console
overset deck.pptx                         # every default rule
overset deck.pptx --no-render             # file-only rules, no LibreOffice
overset deck.pptx --vision                # add the vision-model review (OVS4xx)
overset *.pptx --select OVS0 --format json
overset deck.pptx --keep-render out/      # keep the PDF and slide PNGs
overset --list-rules
overset --explain OVS002
```

**Exit codes:** `0` clean, `1` findings, `2` usage or file error.

## Rules

| Code | Kind | Rule |
|---|---|---|
| OVS000 | structure | The file isn't a well-formed package: a part with no content type, a relationship to a missing part, XML that doesn't parse (what PowerPoint offers to "repair") |
| OVS001 | render | Rendered text runs past the slide edge |
| OVS002 | render | Rendered text spills out of its own frame |
| OVS003 | render | Text from two frames is drawn on top of each other |
| OVS004 | structure | A text frame extends past the slide edge |
| OVS101 | structure | Text set below the minimum size (after shrink-to-fit) |
| OVS102 | structure | A font outside the configured set |
| OVS103 | structure | A colour outside the configured palette |
| OVS104 | render | Text too close in tone to what is behind it (sampled from pixels) |
| OVS201 | structure | A placeholder left empty |
| OVS202 | structure | A picture stretched out of its aspect ratio |
| OVS203 | structure | More words on a slide than an audience will read |
| OVS301 | structure | Two consecutive slides use the same layout *(off by default)* |
| OVS401–406 | vision | Clutter, weak hierarchy, misalignment, text over busy images, monotonous sequences, a slide that doesn't belong *(opt-in)* |

Three kinds, by what a rule needs:

- **structure** reads the `.pptx` alone: offline, milliseconds.
- **render** measures a LibreOffice render: offline, seconds, and
  deterministic.
- **vision** asks a model to look at every slide plus a contact sheet of the
  whole deck: a judgement, reported with a confidence, opt-in. It's for the
  questions nothing can measure (is this slide cluttered, do three slides in
  a row look the same). Measured problems are explicitly kept out of its
  rubric.

### Rendered as PowerPoint shows it

The audience opens the deck in PowerPoint, so that is the layout overset measures. The two renderers
disagree about one thing that matters a lot: **shrink text on overflow** (`<a:normAutofit>`).
PowerPoint applies the scale *stored* in the file when it opens a deck, and recomputes it only when
someone edits the text. A bare `<a:normAutofit/>` therefore shows at 100%. LibreOffice recomputes the
shrink on every render, so text that overflows in PowerPoint fits in LibreOffice, and in any preview
LibreOffice made.

Before rendering, overset freezes every shrink-to-fit box at its stored `fontScale` and
`lnSpcReduction` (100% and 0 when absent). LibreOffice then draws PowerPoint's layout: the same line
breaks, and the same text running into the next box. `render-as = "libreoffice"` turns this off.

*Seen in practice:* a generated deck rendered cleanly in LibreOffice previews, and the cover subtitle and closing questions overlapped when the deck was opened in
PowerPoint. The generator wrote a bare `normAutofit` and sized its boxes by estimate, counting on
a shrink that PowerPoint never applied.

### Measurement notes

- `pdftotext` boxes run from a font's ascender to its descender, not its ink.
  A correctly placed 80pt title sticks out of its frame's top by about a fifth
  of its height. Overflow allowances therefore scale with each word, and
  collisions compare approximate ink, not metric boxes.
- Frames set to **grow with their text** are exempt from OVS002: their stored
  box is stale, not wrong. OVS001 and OVS003 still catch growth that runs off
  the slide or into something else.
- Words no frame claims (text drawn by a chart or SmartArt) are left alone,
  not reported.
- overset renders the deck itself rather than trusting someone else's preview
  images, which can be stale.
- Contrast is sampled from the pixels under each block of words: the
  background is the commonest colour, and the ink is whichever candidate
  contrasts with it most -- every colour with a real share of the pixels, plus
  the farthest one in tone. That handles digits on a dot smaller than their box
  (paper around the dot is not the ink) and small thin type (whose ink is spread
  over many faint shades).
- Words are attributed to frames by reading order *and* column: pdftotext reads
  a row of cards line by line across the columns, so a word continues a frame's
  sequence only if it sits in that frame's column.
- The package is checked before the deck is read (OVS000). A deck python-pptx
  can't load is reported as that finding, not as overset failing; a file that
  isn't a zip at all (a `~$deck.pptx` lock file) is a usage error.
- Decks that embed their fonts render in those
  fonts. For others, `font-dirs` registers font folders with fontconfig.

## Configuration

`overset.toml` (or `.overset.toml`, or `[tool.overset]` in `pyproject.toml`),
found from the deck's folder upward. Flags override it.

```toml
select = ["OVS0", "OVS1"]           # omit for every default-on rule
ignore = ["OVS203"]
extend-select = ["OVS301"]
fonts = ["Inter"]         # by family: "Inter Medium" is Inter
palette = ["20211B", "F7F5F2", "00C756"]
palette-tolerance = 12              # RGB distance
font-dirs = ["fonts/"]              # relative to this file
min-font-pt = 10
max-words = 90
min-contrast = 3.0
tolerance-pt = 2.0
render = true
render-as = "powerpoint"            # or "libreoffice": don't freeze shrink-to-fit
vision = false
vision-model = "anthropic:claude-sonnet-4-6"
vision-threshold = 0.7
vision-input = "both"               # "slides" | "sheet" | "both"
vision-brief = "House style the reviewer should know."
```

`examples/brand.toml` is a small example configuration.

## Development

```console
uv sync
uv run pytest -q --cov     # integration tests skip without LibreOffice
uv run ruff check src tests
```
