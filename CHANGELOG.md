# Changelog

## Unreleased

- The vision rules (OVS4xx) now use a multimodal decision model instead of a language model:
  yes/no questions per slide and per consecutive pair, each answered with a probability. The
  default `vision-model` is `openai:gpt-6-luna` (needs `OPENAI_API_KEY`).
- Removed the `vision-input` setting; every slide and the contact sheet are always used where a
  question needs them. The `vision` extra now installs `httpx`, not pydantic-ai.
- Re-tune `vision-threshold`: it is now the model's probability, not a self-reported confidence.

## 0.1.0

First public release (alpha). Structure, render and opt-in vision rules; TOML configuration;
text and JSON output.
