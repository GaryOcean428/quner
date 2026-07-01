# Publishing quner

**Gate:** publish only after Layer-A is green (`bash sandbox/run_sandbox.sh`) and
Braden approves. The PyPI name is effectively permanent — confirm `quner` (or a
rename) before the first upload.

## Build

```bash
uv build              # -> dist/quner-<ver>-py3-none-any.whl + dist/quner-<ver>.tar.gz
twine check dist/*    # metadata/rendering lint (must pass)
```

## TestPyPI dry-run first

```bash
# token from qig-verification/.env (PYPI_TOKEN) or a dedicated TestPyPI token
twine upload --repository testpypi dist/*
pipx install --index-url https://test.pypi.org/simple/ quner   # verify install
```

## Real PyPI

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD="$(grep -E '^PYPI_TOKEN=' /path/to/qig-verification/.env | cut -d= -f2-)"
twine upload dist/*
```

## Post-publish smoke test

```bash
pipx install quner
quner --version && quner doctor
```

## Versioning

Bump `version` in `pyproject.toml`, tag `vX.Y.Z`, rebuild, re-check, re-upload.
Never re-upload an existing version (PyPI rejects it) — bump instead.
