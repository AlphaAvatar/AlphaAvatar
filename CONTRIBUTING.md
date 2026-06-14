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

  * `TEST_PYPI_TOKEN`
  * `PYPI_TOKEN`
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
