# AGENTS.md

## Repo Introduction

A static site ([torch-compat.danielhou.me](https://torch-compat.danielhou.me)) answering which
PyTorch build works with which Python, CUDA/ROCm/XPU stack, OS, GPU and driver. Data is scraped
from the official wheel index plus curated vendor facts; a daily GitHub Action refreshes the data,
commits it to `main`, and deploys to GitHub Pages.

## Repo Map

| Path | Contents |
| --- | --- |
| `scripts/wheel_index.py` | Fetches and parses the PyTorch wheel index. |
| `scripts/update_data.py` | Regenerates `data/torch_matrix.json` from the wheel index. |
| `scripts/sync_curated_data.py` | Fills gaps in the curated CUDA/ROCm files from vendor sources. |
| `scripts/build_site.py` | Renders `_site/` from `data/` + `web/`. |
| `data/torch_matrix.json` | Generated. Never hand-edit; change the scraper instead. |
| `data/cuda_*.json`, `data/rocm_support.json`, `data/gpus.json` | Curated facts. Hand edits are expected here. |
| `web/` | Site template (`index.html.j2`), `app.js`, `style.css`. |
| `tests/` | pytest suite; `curated_data`-marked tests check curated coverage. |
| `.github/workflows/update-and-deploy.yml` | Daily refresh, test, commit and Pages deploy. |

`_site/` is build output and is gitignored.

## Commands

```sh
pip install -r requirements.txt
python -m pytest tests/ -q -m "not curated_data"   # unit tests
python -m pytest tests/ -q -m curated_data         # curated-data coverage
python scripts/build_site.py                       # build into _site/
```

`update_data.py` and `sync_curated_data.py` hit the network; the CUDA part of the sync needs
Linux x86_64.

## Working Together

- **Be honest.** Say what you actually did and what you verified. If tests fail or a step was
  skipped, say so plainly.
- **Disagree openly.** If a request or existing rule looks wrong, say so and explain why before
  proceeding.
- **Stay in scope.** Do what was asked; mention adjacent problems instead of fixing them unasked.
- **Data accuracy comes first.** Every curated fact should trace to an official vendor source. If
  a source is ambiguous, leave the value null and say so rather than guess.

## Workflow

- Branch off `main` (`feat/*`, `fix/*`, `chore/*`, `docs/*`) and merge through a PR. CI commits
  data updates to `main` daily, so rebase before pushing.
- Commits: `type(scope): imperative summary`. No AI attribution in commits or PRs.
- Work is test-driven: add or update a test with each change, and remove tests the change makes
  obsolete.

## Ask First

- Changing the deploy workflow, its schedule, or the site domain (`SITE_DOMAIN` in `scripts/build_site.py`).
- Adding dependencies beyond `requirements.txt`.
- Bulk rewrites of curated data files.
