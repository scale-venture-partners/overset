# Changelog

## Unreleased

- New typography rules, from Kosslyn et al. (2012): OVS105 (too-many-font-families, more than
  `max-font-families` = 2 families across the deck, counting inherited and theme fonts, with weights of
  one family counted once), OVS106 (emphasis-overuse, a whole paragraph of four or more words in bold,
  italic or capitals, outside titles) and OVS107 (underline-not-link). On by default.
- New rules for bullet structure, from the most-violated measurable rules in Kosslyn et al. (2012):
  OVS209 (too-many-bullets, more than `max-bullets` = 4 items at one level of one list), OVS210
  (long-bullet, a render rule: a bullet on more than `max-bullet-lines` = 2 rendered lines) and OVS211
  (bullet-depth, nested more than `max-bullet-depth` = 2 levels). A paragraph is a bullet when it shows
  a bullet or number, stated or inherited from the layout. On by default; OVS203's word count stays as
  a coarse backstop.
- New rules OVS207 (table-without-header) and OVS208 (default-section-name), two more errors from
  Microsoft's Accessibility Checker: a table whose "Header Row" option is off, and a section still
  named "Default Section" or "Untitled Section". Both on by default.
- `--vision` with a model id the API rejects now stops with a clear message naming the model and the
  `vision-model` setting (exit 2), instead of a generic `DecisionError: HTTP 404` for the deck.
- OVS003 sweeps rendered words top to bottom instead of comparing every pair, so dense slides
  (tables, appendix pages) are checked in a fraction of the time. Findings are unchanged.
- New rule OVS206 (missing-alt-text): a picture (including video), chart, SmartArt graphic or embedded
  object with no alt text, or alt text that is only a file name (`IMG_1234.jpg`, `Picture 3`, a
  screenshot's default name). Visuals marked decorative in PowerPoint, and the layout's and master's
  own, are exempt. On by default.
- New rules OVS204 (missing-slide-title) and OVS205 (duplicate-slide-title), the two title checks in
  Microsoft's Accessibility Checker. Only a title placeholder counts as a title; hidden slides are
  skipped. An empty title placeholder is now reported as OVS204 instead of OVS201 (OVS201 still
  reports it if OVS204 is ignored). Both are on by default, so decks of untitled slides will report
  more findings.
- OVS104 now uses WCAG 2.2's size-dependent contrast thresholds: `min-contrast` defaults to 4.5
  (was 3.0) for body text, and the new `min-contrast-large` (3.0) applies to text of 18pt and up,
  or 14pt bold. Text whose size isn't known is held to 4.5:1. Expect more OVS104 findings on
  small grey text; set `min-contrast = 3.0` to keep the old behaviour.
- Rendering as PowerPoint now applies a shrink's line-spacing reduction to paragraphs that don't
  state their own spacing (they get their inherited spacing, or 100%, reduced), and to spacing
  given in points. Before, those lines were drawn at full spacing: false OVS002 on shrunk text.
- Rendering as PowerPoint now scales inherited font sizes too. A shrink-to-fit text body whose
  text inherits its size was drawn at 100% instead of PowerPoint's stored `fontScale`, which
  produced false OVS002/OVS003 findings on placeholder text.
- OVS101 now checks text whose size is inherited rather than stated: from the shape's list style,
  the layout and master placeholders, the master's title/body/other text styles, or the
  presentation default. Most template text inherits its size, so expect more OVS101 findings.
  Table text that doesn't state a size is still skipped.
- Shapes inside groups are now checked. Each group is flattened into its children, placed on the
  slide through the group's transform, so OVS101/102/103 see grouped text, OVS202 sees grouped
  pictures, OVS004/OVS201 see grouped frames, and OVS002/OVS003 use each child as its own frame
  rather than the group's whole box. Messages name a child with its group, e.g.
  `'Card 2 > TextBox 5'`. Decks with grouped cards will report more findings.
- A relative `--keep-render` directory no longer makes LibreOffice hang until the 180s timeout.
- The vision rules (OVS4xx) now use a multimodal decision model instead of a language model:
  yes/no questions per slide and per consecutive pair, each answered with a probability. The
  default `vision-model` is `openai:gpt-6-luna` (needs `OPENAI_API_KEY`).
- Removed the `vision-input` setting; every slide and the contact sheet are always used where a
  question needs them. The `vision` extra now installs `httpx`, not pydantic-ai.
- Re-tune `vision-threshold`: it is now the model's probability, not a self-reported confidence.

## 0.1.0

First public release (alpha). Structure, render and opt-in vision rules; TOML configuration;
text and JSON output.
