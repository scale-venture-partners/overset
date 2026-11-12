# Contributing

```console
uv sync
uv run ruff format src tests scripts
uv run ruff check src tests scripts
uv run pytest -q --cov
```

Integration tests need LibreOffice and poppler and skip themselves without them; CI runs them.
A new rule needs a code in the README table, an `--explain` text, and a test that builds a small
deck (see `tests/conftest.py`) and asserts the finding. Rendering changes should be checked against
a real LibreOffice render, not only unit tests.

## Where rules live

| Module | Rules |
|---|---|
| `rules/structure.py` | the package, frames off the slide, size, brand fonts and palette, placeholders, distortion, word count, bullets, layouts (OVS000, OVS004, OVS101-103, OVS201-203, OVS209, OVS211, OVS301) |
| `rules/style.py` | typography and colour beyond the brand (OVS105-110) |
| `rules/accessibility.py` | what Microsoft's Accessibility Checker reports (OVS204-208, OVS212) |
| `rules/render_rules.py` | measured from a LibreOffice render (OVS001-003, OVS104, OVS210) |
| `rules/layout.py`, `rules/measured.py` | layout measures and measured counterparts of the vision rules, off by default (OVS005-009, OVS111-112) |
| `rules/vision.py` | the decision-model rules (OVS401-406) |

Codes follow the groups in `rules/base.py`, whatever module a rule lives in.

## Before changing what a rule reports

Run it over the starter corpus (`docs/corpus.md`) and look at a sample of what it finds: most of the
fixes so far came from findings that turned out to be measurement artifacts. A new threshold should
come from the corpus's distribution or, better, from labelled slides (`docs/labelling.md`), and
`scripts/rank_eval.py` shows whether a rule's findings track what people prefer (`docs/rank-eval.md`).
