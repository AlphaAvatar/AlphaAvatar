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

### Build every distribution

Build tooling is separate from the runtime and lint environments:

```bash
UV_PROJECT_ENVIRONMENT=.venv-build uv sync --locked --only-group build --no-install-workspace
uv build --all-packages --no-sources
UV_PROJECT_ENVIRONMENT=.venv-build uv run --no-sync twine check dist/*
```

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

AlphaAvatar uses **Git tags**, **GitHub Actions**, and **GitHub Releases** to automate packaging and publishing all workspace packages.

A release is triggered by pushing a version tag:

* `test-vX.Y.Z` for **TestPyPI**
* `vX.Y.Z` for **PyPI**

The release flow is managed through the project `Makefile`.

---

### 1️⃣ Prerequisites

Before creating a release, make sure your local branch is clean and up to date:

```bash
git pull --rebase origin main
git status
```

Also verify:

* All changes are committed and tested.
* Package versions are consistent across `__version__` fields and `pyproject.toml` files.
* GitHub Actions secrets are configured:

  * `TEST_PYPI_API_TOKEN`
  * `PYPI_API_TOKEN`
* GitHub CLI is available if you want automatic GitHub Release creation and PR changelog generation:

```bash
gh auth status
```

Alternatively, set a GitHub API token through:

```bash
export GH_TOKEN="<your-github-token>"
```

The token should have permission to read repository metadata, read pull requests, and create or update releases.

---

### 2️⃣ Install pre-commit hooks

After setting up the development environment, install pre-commit hooks once:

```bash
pre-commit install
```

---

### 3️⃣ Prepare GitHub Release Notes Config

This only needs to be done once per repository.

```bash
make prepare-release-config
```

This creates:

```text
.github/release.yml
```

The config controls how GitHub groups merged PRs in generated release notes, for example:

* Features
* Persona / Memory
* Bug Fixes
* Documentation
* Maintenance

Commit the file after creation:

```bash
git add .github/release.yml
git commit -m "chore: add GitHub release notes config"
```

---

### 4️⃣ Prepare Manual Release Notes

For each production release, create a manual release note file:

```bash
make prepare-release VERSION=0.6.1
```

This creates:

```text
docs/releases/v0.6.1.md
```

Edit this file with the high-level summary and highlights for the release.

Example:

```md
## AlphaAvatar v0.6.1

This release adds visual identity support to AlphaAvatar’s Persona system and improves realtime multimodal identity resolution.

### Highlights

- Added visual identity support for the Persona plugin.
- Added face vector matching, retrieval, and persistence.
- Improved speaker-face identity fusion.
- Fixed Persona runtime state and VDB persistence issues.
```

Also update the `README.md` Latest News section if needed.

Then commit the release notes:

```bash
git add README.md docs/releases/v0.6.1.md
git commit -m "docs: prepare release notes for v0.6.1"
```

---

### 5️⃣ Test Release

To publish a test release to TestPyPI:

```bash
make release VERSION=0.6.1 TYPE=test
```

This command:

1. Checks release preconditions.
2. Pushes the current branch.
3. Creates a tag named `test-v0.6.1`.
4. Pushes the tag to GitHub.
5. Triggers the GitHub Actions workflow.
6. Publishes all workspace packages to **TestPyPI**.

You can install the test release with:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple alpha-avatar-agents
```

---

### 6️⃣ Production Release

After verifying the TestPyPI release, publish to PyPI:

```bash
make release VERSION=0.6.1 TYPE=prod PREVIOUS_TAG=v0.6.0
```

This command:

1. Checks release preconditions.
2. Pushes the current branch.
3. Creates a tag named `v0.6.1`.
4. Pushes the tag to GitHub.
5. Triggers the GitHub Actions workflow.
6. Publishes all workspace packages to **PyPI**.
7. Builds final GitHub Release notes by combining:

   * Manual notes from `docs/releases/v0.6.1.md`
   * Auto-generated GitHub PR changelog from merged PRs
8. Creates or updates the GitHub Release page.

The final generated release body is written to:

```text
docs/releases/.generated/v0.6.1.full.md
```

The release body format is:

```md
Manual release notes

---

Generated PR changelog
```

---

### 7️⃣ Release Notes and PR Changelog

For GitHub to generate a useful PR changelog, changes should be merged through Pull Requests.

Recommended workflow:

```text
feature branch
↓
Pull Request
↓
Add labels
↓
Merge PR
↓
Release
```

Recommended PR labels:

* `feature`
* `enhancement`
* `bug`
* `docs`
* `persona`
* `memory`
* `chore`
* `dependencies`
* `ignore-for-release`

Example PR creation:

```bash
gh pr create \
  --title "Add visual identity support for Persona" \
  --body "Adds face detection, face vector matching, and speaker-face identity fusion." \
  --label feature \
  --label persona
```

When releasing, pass the previous production tag to generate a clean changelog range:

```bash
make release VERSION=0.6.1 TYPE=prod PREVIOUS_TAG=v0.6.0
```

If `PREVIOUS_TAG` is omitted, GitHub will infer the changelog range automatically.

---

### 8️⃣ Optional Release Flags

| Command / Flag                                             | Description                                                          |
| ---------------------------------------------------------- | -------------------------------------------------------------------- |
| `make setup`                                               | Create a local development environment with `uv venv` and `uv sync`  |
| `make dry-run VERSION=0.6.1`                               | Build packages locally without pushing or publishing                 |
| `make prepare-release VERSION=0.6.1`                       | Create manual release notes under `docs/releases/`                   |
| `make prepare-release-config`                              | Create `.github/release.yml` for grouped PR changelogs               |
| `make release VERSION=0.6.1 TYPE=test`                     | Publish a test release to TestPyPI                                   |
| `make release VERSION=0.6.1 TYPE=prod PREVIOUS_TAG=v0.6.0` | Publish a production release to PyPI and create GitHub Release notes |
| `GH_RELEASE=0 make release VERSION=0.6.1 TYPE=prod`        | Skip GitHub Release creation                                         |
| `GH_GENERATE_NOTES=0 make release VERSION=0.6.1 TYPE=prod` | Use manual release notes only, without generated PR changelog        |
| `REPO=testpypi ./scripts/release.sh 0.6.1`                 | Manually publish packages to TestPyPI                                |
| `DRY=1 ./scripts/release.sh 0.6.1`                         | Test version bump and build without publishing                       |

---

### 9️⃣ Verification

After CI completes, verify:

* Packages are available on PyPI or TestPyPI.
* GitHub Actions completed successfully.
* GitHub Release page includes the manual release summary.
* GitHub Release page includes the generated PR changelog when PRs are available.
* Core packages install successfully:

```bash
pip install alpha-avatar-agents
```

---

### ✅ Release Summary

Typical production release flow:

```bash
git pull --rebase origin main
git status

make prepare-release VERSION=0.6.1

# Edit docs/releases/v0.6.1.md and README.md

git add README.md docs/releases/v0.6.1.md
git commit -m "docs: prepare release notes for v0.6.1"

make release VERSION=0.6.1 TYPE=test

# After TestPyPI verification

make release VERSION=0.6.1 TYPE=prod PREVIOUS_TAG=v0.6.0
```
