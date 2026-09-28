# Development and publishing

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,docs]"
```

## Checks

```bash
pytest                                   # fully offline (respx mocks); live tests skip without keys
ruff check . && ruff format --check .
mypy                                     # strict
python scripts/generate_async.py --check
```

CI (`.github/workflows/ci.yml`) runs all of these on Python 3.9 to 3.13.

## Project layout

```
src/bitvavo_sdk/
  _base.py              config, request building, signing, response and error mapping
  _endpoints.py         every endpoint, written once as sync code   <- edit this
  _async_endpoints.py   GENERATED async twin                         <- never edit
  client.py             Bitvavo: sync transport, retry loop
  async_client.py       AsyncBitvavo: async transport, retry loop
  auth.py               HMAC signing
  errors.py             exception hierarchy + errorCode mapping
  rate_limit.py         RateLimitState
  types.py              TypedDict / Literal response types
  utils.py              number formatting, tick/decimal rounding
tests/                  SDK tests
docs/                   this documentation (mkdocs)
```

## Adding or changing an endpoint

1. Add the method to `SyncEndpoints` in `_endpoints.py`. Call `self._call(method, path, params=..., body=..., private=..., weight=...)` with the weight from Bitvavo's docs.
2. Add a response `TypedDict` to `types.py` if needed.
3. Run `python scripts/generate_async.py`.
4. Add a test, and a row in `docs/endpoints.md`.

## Docs site

```bash
mkdocs serve        # http://127.0.0.1:8000
mkdocs gh-deploy    # publish to GitHub Pages
```

## Releasing to PyPI

This is a Python package, so it's published to **PyPI** (installed with `pip`), not npm.

1. Bump `src/bitvavo_sdk/_version.py` and add a section to `CHANGELOG.md`.
2. Commit, then tag the commit: `git tag v0.1.0 && git push --tags`.
3. `.github/workflows/publish.yml` builds the sdist and wheel, and uploads them with PyPI **Trusted Publishing** (OIDC, so no API token is stored). Configure it once at <https://pypi.org/manage/account/publishing/> with the workflow name `publish.yml` and the environment `pypi`.

To publish manually:

```bash
python -m build
twine check dist/*
twine upload --repository testpypi dist/*   # dry run on TestPyPI first
twine upload dist/*
```
