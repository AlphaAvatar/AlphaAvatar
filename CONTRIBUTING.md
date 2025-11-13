## 🧩 Release Process

This project uses **Git tags** and **GitHub Actions** to automate the packaging and publishing of all workspace packages to PyPI.
Once the `main` branch is stable, releases are created simply by tagging a version — no manual builds required.

### 1️⃣ Prerequisites

* Ensure your local `main` branch is **clean and up to date**:

  ```bash
  git pull origin main
  git status
  ```
* Make sure all changes are committed and tested.
* Verify that each package’s `__version__` field and `pyproject.toml` are consistent.
* Check that CI secrets are configured in the repository:

  * `TEST_PYPI_TOKEN`
  * `PYPI_TOKEN`

---

### 2️⃣ Test Release (TestPyPI)

To test a release on [TestPyPI](https://test.pypi.org/):

```bash
make release VERSION=0.1.0 TYPE=test
```

This command:

1. Creates a tag named `test-v0.1.0`
2. Pushes it to GitHub
3. Triggers the GitHub Actions workflow
4. Publishes all workspace packages to **TestPyPI**

You can install the test release with:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple alpha-avatar-agents
```

---

### 3️⃣ Production Release (PyPI)

After verifying that the TestPyPI release works as expected:

```bash
make release VERSION=0.1.0 TYPE=prod
```

This creates a tag `v0.1.0` and pushes it to GitHub.
The GitHub Actions workflow will automatically:

* Build and publish all packages to **PyPI**
* Generate structured **Release Notes** (What’s Changed, New Contributors, Full Changelog)
* Attach the notes to a new GitHub Release page

---

### 4️⃣ Optional Commands

| Command                                    | Description                                                    |
| ------------------------------------------ | -------------------------------------------------------------- |
| `make setup`                               | Create a local development environment (`uv venv` + `uv sync`) |
| `make dry-run VERSION=0.1.0`               | Build packages locally without pushing or publishing           |
| `REPO=testpypi ./scripts/release.sh 0.1.0` | Manual call to publish script                                  |
| `DRY=1 ./scripts/release.sh 0.1.0`         | Test version bump/build without release                        |

---

### 5️⃣ Verification

After CI completes, verify:

* Packages are live on [PyPI](https://pypi.org/) or [TestPyPI](https://test.pypi.org/)
* GitHub Release page includes the generated **structured changelog**
* `alphaavatar`, `alpha-avatar-agents`, and related plugin packages install successfully.

---

### ✅ Release Summary

Once everything is configured, releasing is just **one command**:

```bash
# TestPyPI
make release VERSION=0.1.0 TYPE=test

# Production PyPI
make release VERSION=0.1.0 TYPE=prod
```
