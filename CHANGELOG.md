# Changelog

## Unreleased

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
