# Publishing quner

The release workflow is `.github/workflows/release.yml`. It uses PyPI Trusted Publishing (OIDC),
with no stored upload token and no credentials borrowed from another project.

## Validation and promotion

Pull requests and pushes to `development` and `main` run the Layer-A sandbox, build a wheel and sdist,
and check package metadata. The sandbox writes only to its fake hardware/state tree; mandatory command
failures stop validation. Its before/after host-governor comparison must pass. Docker rehearsal is
conditional on Docker availability and reports a skip when unavailable.

Promote reviewed changes through `development` to `main` by PR. A merge validates but does not publish.
For a new package release, increment the version in `pyproject.toml`, then tag the verified production
commit `vX.Y.Z`. The workflow rejects a tag/version mismatch or a commit outside `main` ancestry.
Manual dispatch validates and builds without uploading. Infrastructure-only edits do not require a new
package version: do not retag or republish the existing 0.1.3 distribution just to add this workflow.

## Trusted publisher configuration

The expected PyPI publisher identity is:

- Owner: `GaryOcean428`
- Repository: `quner`
- Workflow: `release.yml`
- Environment: `pypi`

The matching GitHub environment is `pypi`, with tag deployment rules and any review rules configured by
the owner. Only the publish job receives `id-token: write`; build/test jobs have read-only repository
permissions. All external workflow actions are pinned to commit SHAs.

GitHub inspection when introducing this workflow found no repository environments or release workflow.
That does not prove whether a publisher is already configured on PyPI: the private PyPI configuration
must be checked against this exact identity. Do not claim trusted publishing is operational until that
configuration and a real new-version upload succeed. Do not fall back to a token if OIDC is rejected.

See [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/) for the contract.

## Local checks

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]' build twine uv
export PATH="$PWD/.venv/bin:$PATH"
bash sandbox/run_sandbox.sh
python -m build
python -m twine check dist/*
```

After upload the workflow compares the local wheel and sdist SHA-256 hashes with PyPI, not just the
existence of a version. Verify installation in a disposable environment with `quner --version` and
`quner doctor`; do not invoke `apply`, install a host service or change host power settings as a package
publication smoke test. Hardware actuation remains a separate, explicitly controlled validation.
