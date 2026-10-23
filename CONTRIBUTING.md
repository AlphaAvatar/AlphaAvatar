# Contributing to AlphaAvatar

## Python 3.13 development environment

The development target is standard CPython 3.13, not a free-threaded interpreter.
`.python-version`, all package `requires-python` declarations, Ruff, mypy and CI use
that target. The root `pyproject.toml` owns workspace policy and development tools;
each distribution owns its runtime dependencies, entry points and packaged resources.
The shared `alphaavatar` namespace must not gain a root `__init__.py`.

### Migrate an existing Python 3.11 checkout

Stop the Host and wait for resource cleanup. Keep the working environment and workspace
backup; do not delete them to make a new installation succeed. Apply the source changes
in a separate worktree or checkout, then use a new virtual environment:

```bash
uv python install 3.13
uv lock --python 3.13
git diff -- uv.lock
UV_PROJECT_ENVIRONMENT=.venv313 uv sync --all-packages --locked --python 3.13
uv pip check --python .venv313/bin/python
.venv313/bin/alphaavatar --help
.venv313/bin/alphaavatar --version
```

Commit the resolver-generated lock together with the metadata after review. Never change
only the lock's Python header, use `--frozen` to accept a stale lock, or remove a failing
feature to claim the complete installation passed. Leave existing third-party pins in
place initially; update only a dependency with a demonstrated incompatibility, then
repeat resolution, installation and relevant feature checks. `uv sync --all-packages`
is the integration environment; a lint-only environment is deliberately not equivalent.

Run your chosen configuration with the new environment against your intended services.
Verify startup, a real dispatch and interaction, cancellation during startup and active
work, and normal shutdown before updating the service executable. Metadata, import and
wheel checks alone do not validate models, audio, tool effects, RTC or the AIRI browser.
Keep the old checkout/environment available for rollback; restoring code does not reverse
external tool effects or replace a workspace backup.

### Repeatable checks without loading models

Use the committed lock with uv 0.10.0 or newer. CI uses uv 0.10.0. Quality tools have their
own environment so checking code does not uninstall or replace runtime dependencies:

```bash
UV_PROJECT_ENVIRONMENT=.venv-quality uv sync --locked --only-group lint --no-install-workspace
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync python scripts/check_workspace.py
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff check .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff format --check .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync pre-commit validate-config
uv lock --check
```

`scripts/check_workspace.py` checks package metadata, dependency relationships, entrypoint
files, licenses and lock policy without importing the runtime. Its `--metadata-only` mode
is useful during authoring but explicitly skips source/lock validation; it is not a release
gate. `uv lock --check` is still required for resolver-level freshness. No command here
silently treats an unavailable tool or an empty test suite as a successful check.

Ruff is fixed at **0.12.9** in the dependency group, `required-version` and pre-commit.
Keep 100-column formatting and compact imports; trailing commas do not force expansion.
Unsafe fixes are not enabled. Inspect safe fixes and formatting before committing:

```bash
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff check --fix .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff format .
git diff --check
git diff
```

The existing E501 and B904 exceptions are retained; do not add blanket F/I/B/UP exclusions
to conceal migration failures. Vendored `third_party` code, generated environments and
workspace data are excluded, but `.github` is not blanket-excluded. TID251 rejects static
`livekit.agents` imports; dependency/lock checks also reject the removed Agents SDK.
This is not a security analysis of dynamic import strings or arbitrary third-party code.

The repository's `/tests/` directory is currently local-only. Run maintained local tests
with the runtime environment when present; pytest exit code 5 means no tests were collected,
not a passing regression run. The quality workflow runs installation/import/build checks
but does not claim an absent committed test suite passed.

### Install local commit and push hooks

A committed `.pre-commit-config.yaml` does not install Git hooks. In each checkout, run:

```bash
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync pre-commit install \
  --hook-type pre-commit --hook-type pre-push
```

Commit hooks fix/check staged files. The read-only push hooks run Ruff lint and formatting
against the complete workspace, including when only configuration files changed. They do
not build distributions or call model services. CI remains authoritative: local hooks can
be bypassed and do not accompany commits to another machine.

After changing lint policy or Python syntax targets, align the complete baseline once:

```bash
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff check --fix .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff format .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff check .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff format --check .
git diff --check
git diff
```

Review PEP 695 type aliases and generic declarations explicitly; do not add `--unsafe-fixes`
to the hook. An unchanged file can pass unnoticed by a staged-file commit check while
failing the whole-tree CI check. When diagnosing hook installation, inspect
`git config --show-origin --get core.hooksPath` and the hook files in the effective hook
directory; no configured `core.hooksPath` is itself not an error.

### Build every distribution

Build tooling is separate from the runtime and lint environments:

```bash
UV_PROJECT_ENVIRONMENT=.venv-build uv sync --locked --only-group build --no-install-workspace
(
  set -e
  constraints="$(mktemp)"
  trap 'rm -f "$constraints"' EXIT
  uv export --locked --only-group build --no-emit-workspace --no-hashes \
    --output-file "$constraints" > /dev/null
  uv build --all-packages --no-sources --build-constraints "$constraints"
  UV_PROJECT_ENVIRONMENT=.venv-build uv run --no-sync twine check dist/*
)
```

The build group's Twine 7 and packaging 26.1-or-newer readers support Core Metadata 2.5.
Keep the metadata writer and readers compatible in the committed lock. Isolated builds
use constraints exported from that lock; installing a pinned Hatchling in `.venv-build`
alone does not constrain an isolated PEP 517 build. A successful wheel build does not
substitute for `twine check`. Do not edit artifact metadata or skip validation to make a
release pass.

Each distribution includes its own copy of the root Apache-2.0 `LICENSE`, README,
`pyproject.toml`, namespace source and existing package resources. License copies are
checked for drift. `--no-sources` verifies that building does not depend on uv's editable
workspace overrides; it does not prove that all runtime dependencies can be installed.
Use a clean output directory when reviewing a release's artifacts.

### Network and installation failures

Distinguish DNS errors, TCP connection failures, TLS verification failures and resolver
conflicts. A failed GitHub connection does not mean that a repository or dependency version
is missing. Use the environment's approved network/proxy configuration. Do not disable TLS
verification or write guessed IP addresses into permanent Git/DNS settings. A container
with no outbound connection cannot be repaired by changing a package constraint.

When working offline, use a previously populated uv cache or a controlled package mirror
with the required Python 3.13 artifacts. Do not replace the runtime installation result with
syntax checks. Record the failing command and stage without publishing proxy credentials,
access tokens or environment files.

## Plugin development

Plugin packages are grouped by responsibility:

| Layer | Package location | Responsibility |
| :--- | :--- | :--- |
| Foundation | `avatar-plugins/foundation/` | Shared service components used by other plugins. |
| Perception | `avatar-plugins/perception/` | User understanding, memory, identity, and interaction. |
| Tools | `avatar-plugins/tools/` | Research, document access, and external operations. |

Read [Plugin Layout and Boundaries](avatar-plugins/README.md) before adding or moving a package.

Keep public namespaces under `alphaavatar.plugins.<plugin>`. Do not encode layer names into Python imports or YAML plugin selections. Keep processor-specific configuration, prompts, model specifications, and business logic with their owning processor.

Consumers own their tasks, streams, and request state; `FoundationRuntime` owns shared service components. Plugin registration must not initialize models. Select inference runners from the active configuration and resolve model files inside runner initialization.

Package changes must keep workspace membership, `[tool.uv.sources]`, `scripts/release.sh`, dependency metadata, and `uv.lock` consistent. Review lockfile changes before committing, then verify:

```bash
uv lock --check
uv sync --all-packages --locked
```

Update the root plugin catalog with a concise capability description and accurate status. Existing plugins link to their README; planned plugins must not use placeholder links or imply that an implementation is available.

---

## 🧩 Release Process

GitHub Releases and Python package index uploads are **independent** operations.
Pushing a production `vX.Y.Z` tag runs this pipeline:

```text
push v* tag
    ↓
Quality checks (lint, build, install)
    ↓
Generate Release Notes
    ↓
Create GitHub Release
```

`.github/workflows/release.yml` does not upload anything to PyPI or TestPyPI.
A passing source build does not prove that a particular distribution is available
on either package index.

### 1. Prepare the release on `main`

Use CPython 3.13 and the committed lockfile. Ensure `main` is up-to-date and clean.
Confirm all packages have matching `__version__` values and that the quality
workflow passes. Prepare human-written notes before pushing the tag:

```bash
git switch main
git pull --ff-only origin main
make prepare-release VERSION=0.6.9
# Edit docs/releases/v0.6.9.md and update README.md as needed.
git add docs/releases/v0.6.9.md README.md
git commit -m "docs: prepare v0.6.9 release notes"
make release VERSION=0.6.9 TYPE=prod
```

The final `make release` pushes the `v0.6.9` tag; GitHub Actions runs the
quality, notes, and Release creation stages. Alternatively, push an existing
local `vX.Y.Z` tag after checking that it points to the intended source commit.
The workflow combines `docs/releases/vX.Y.Z.md` (if present) with GitHub's
configured PR changelog (`.github/release.yml`). Re-running the release job
will preserve an existing GitHub Release rather than overwrite its notes.

Do not create a `test-v*` tag to trigger TestPyPI: those tags no longer have
an automatic publishing workflow.

### 2. Optional, manual PyPI / TestPyPI publishing

If a specific Python distribution should be uploaded, open GitHub **Actions**
→ **Publish Package to PyPI (manual)** → **Run workflow** on `main`.
Select the existing `vX.Y.Z` **tag**, the **single package** to publish, and
`testpypi` or `pypi` (TestPyPI is the default). Required repository secrets:

* `TEST_PYPI_API_TOKEN` for TestPyPI.
* `PYPI_API_TOKEN` for PyPI.

The manual job validates that the tag exists on the `main` history, that the
selected package belongs to the workspace, and that its packaged version
matches the tag. It builds and checks only the selected distribution before
uploading. It does **not** retag, rewrite package versions, or release the
other workspace packages. Existing successfully uploaded artifacts are not
removed when another package fails.

For CLI users with repository write access, a corresponding manual invocation
is:

```bash
gh workflow run publish-pypi.yml --ref main \
  -f tag=v0.6.9 \
  -f package=alpha-avatar-core \
  -f repository=testpypi
```

**Availability warning:** the source workspace currently contains 16 Python
packages, but a GitHub Release does **not** guarantee that all 16 packages,
or their matching version, exist on PyPI or TestPyPI. Check the exact package
and version in the index before documenting a `pip install` command. For a
complete matched installation, use the release-tag source checkout and its
committed `uv.lock`, as described in the main README.

### 3. Verify the result

Verify that GitHub Actions completed the three release stages and that
`https://github.com/AlphaAvatar/AlphaAvatar/releases/tag/vX.Y.Z` contains
the expected manual and generated notes. Verify PyPI separately, **only**
for a package that was deliberately published.

Changing `.github/workflows/release.yml` on `main` does not retroactively fix
old failed tag-triggered runs. A previously created GitHub Release and already
uploaded PyPI distributions remain in place.
