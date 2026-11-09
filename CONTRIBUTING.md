# Contributing

Thanks for helping. TikTok changes its web app often, so selector fixes and new label translations are the most valuable contributions.

## Setup

```bash
git clone https://github.com/qiyascc/tiksocket
cd tiksocket
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

## Checks

```bash
ruff check .
pytest
```

Tests run offline. They cover parsers, labels, auth state, the CLI and the REST API with a fake backend. Please add a test for every parser change.

## When TikTok changes something

1. Run the failing command with `--show-browser -v`.
2. Look at the screenshot TikSocket saved in `<account folder>/debug/`.
3. Prefer `data-e2e` attributes and roles over class names. Add the new selector as a fallback instead of replacing the old one.
4. If a button text is missing in your language, add it to `src/tiksocket/labels.py`.

## Style

- Keep comments to a minimum and write them in English.
- Keep public names stable. Add, do not rename.
- One logical change per pull request.
