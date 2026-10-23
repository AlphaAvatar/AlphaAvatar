# ===============================
# AlphaAvatar Release Automation
# ===============================
#
# Usage:
#   make prepare-release-config
#   make prepare-release VERSION=0.6.1
#   make release VERSION=0.6.9 TYPE=prod
#   Publish package: Actions -> Publish Package to PyPI (manual)
#
# Notes:
#   - This Makefile uses ".RECIPEPREFIX := >" to avoid Tab-related Makefile errors.
#   - For prod releases, docs/releases/vX.Y.Z.md must be committed.
#   - Production tags trigger GitHub Release only; PyPI is separate and opt-in.

.RECIPEPREFIX := >

VERSION ?= 0.1.0
TYPE ?= prod

PYTHON ?= python3

RELEASE_SCRIPT := scripts/release.sh

TAG := v$(VERSION)
RELEASE_NOTES := docs/releases/$(TAG).md
RELEASE_CONFIG := .github/release.yml
# -------------------------------
# Environment setup
# -------------------------------
.PHONY: setup
setup:
> @echo "🚀 Setting up development environment..."
> uv venv .venv
> . .venv/bin/activate && uv sync --all-packages

# -------------------------------
# Local build check without pushing
# -------------------------------
.PHONY: dry-run
dry-run:
> @echo "🔍 Dry-run build for version $(VERSION)"
> DRY=1 $(RELEASE_SCRIPT) $(VERSION)

# -------------------------------
# Prepare GitHub release note config
# -------------------------------
.PHONY: prepare-release-config
prepare-release-config:
> @echo "📝 Preparing GitHub release notes config: $(RELEASE_CONFIG)"
> @mkdir -p .github
> @if [ -f "$(RELEASE_CONFIG)" ]; then \
>   echo "ℹ️ $(RELEASE_CONFIG) already exists. Skipping."; \
> else \
>   printf '%s\n' \
>     'changelog:' \
>     '  exclude:' \
>     '    labels:' \
>     '      - ignore-for-release' \
>     '    authors:' \
>     '      - dependabot[bot]' \
>     '' \
>     '  categories:' \
>     '    - title: 🚀 Features' \
>     '      labels:' \
>     '        - feature' \
>     '        - enhancement' \
>     '' \
>     '    - title: 🧠 Persona / Memory' \
>     '      labels:' \
>     '        - persona' \
>     '        - memory' \
>     '' \
>     '    - title: 🐛 Bug Fixes' \
>     '      labels:' \
>     '        - bug' \
>     '        - fix' \
>     '' \
>     '    - title: 📚 Documentation' \
>     '      labels:' \
>     '        - docs' \
>     '        - documentation' \
>     '' \
>     '    - title: 🧹 Maintenance' \
>     '      labels:' \
>     '        - chore' \
>     '        - dependencies' \
>     '        - refactor' \
>     '' \
>     '    - title: Other Changes' \
>     '      labels:' \
>     '        - "*"' \
>     > "$(RELEASE_CONFIG)"; \
>   echo "✅ Created $(RELEASE_CONFIG)"; \
> fi

# -------------------------------
# Prepare manual release notes
# -------------------------------
.PHONY: prepare-release
prepare-release:
> @echo "📝 Preparing release notes: $(RELEASE_NOTES)"
> @mkdir -p docs/releases
> @if [ -f "$(RELEASE_NOTES)" ]; then \
>   echo "ℹ️ $(RELEASE_NOTES) already exists. Skipping."; \
> else \
>   printf '%s\n' \
>     '## AlphaAvatar $(TAG)' \
>     '' \
>     'This release improves AlphaAvatar’s realtime multimodal assistant runtime.' \
>     '' \
>     '### Highlights' \
>     '' \
>     '- Add release highlights here.' \
>     '- Add bug fixes here.' \
>     '- Add documentation updates here.' \
>     '' \
>     '### Notes' \
>     '' \
>     'Add additional release notes here.' \
>     > "$(RELEASE_NOTES)"; \
>   echo "✅ Created $(RELEASE_NOTES)"; \
> fi
> @echo ""
> @echo "Next steps:"
> @echo "  1. Edit $(RELEASE_NOTES)"
> @echo "  2. Update README.md Latest News"
> @echo "  3. Commit docs"
> @echo "  4. Run: make release VERSION=$(VERSION) TYPE=prod"

# -------------------------------
# Check release preconditions
# -------------------------------
.PHONY: check-release
check-release:
> @echo "🔎 Checking release preconditions for $(TAG)..."
> @if [ "$(TYPE)" = "prod" ] && [ "$$(git branch --show-current)" != "main" ]; then \
>   echo "Release tags must be created from main."; \
>   exit 1; \
> fi
> @if [ "$(TYPE)" = "prod" ] && [ ! -f "$(RELEASE_NOTES)" ]; then \
>   echo "❌ Missing release notes: $(RELEASE_NOTES)"; \
>   echo "Run: make prepare-release VERSION=$(VERSION)"; \
>   exit 1; \
> fi
> @if [ "$(TYPE)" = "prod" ] && [ ! -f "$(RELEASE_CONFIG)" ]; then \
>   echo "❌ Missing GitHub release config: $(RELEASE_CONFIG)"; \
>   echo "Run: make prepare-release-config"; \
>   exit 1; \
> fi
> @if [ -n "$$(git status --porcelain)" ]; then \
>   echo "❌ Working tree is not clean. Please commit or stash changes first."; \
>   git status --short; \
>   exit 1; \
> fi
> @if [ "$(TYPE)" = "prod" ] && git rev-parse "$(TAG)" >/dev/null 2>&1; then \
>   echo "❌ Local tag $(TAG) already exists."; \
>   exit 1; \
> fi
> @if [ "$(TYPE)" = "prod" ] && git ls-remote --tags origin "$(TAG)" | grep -q "$(TAG)"; then \
>   echo "❌ Remote tag $(TAG) already exists."; \
>   exit 1; \
> fi
> @echo "✅ Release preconditions passed."

# -------------------------------
# Push current branch
# -------------------------------
.PHONY: push-branch
push-branch:
> @CURRENT_BRANCH="$$(git branch --show-current)"; \
> if [ -z "$$CURRENT_BRANCH" ]; then \
>   echo "❌ Cannot detect current branch."; \
>   exit 1; \
> fi; \
> echo "⬆️ Pushing branch $$CURRENT_BRANCH..."; \
> git push origin "$$CURRENT_BRANCH"

# -------------------------------
# PyPI publishing is deliberately separate and manual.
# -------------------------------
.PHONY: release-test
release-test:
> @echo "TestPyPI is no longer triggered by a test-v* tag."
> @echo "Use Actions -> Publish Package to PyPI (manual), selecting testpypi."
> @exit 1

# -------------------------------
# GitHub-only production release tag
# -------------------------------
.PHONY: release-prod
release-prod: check-release push-branch
> @echo "Pushing GitHub Release trigger tag $(TAG) (no automatic PyPI upload)"
> git tag "$(TAG)"
> git push origin "$(TAG)"
> @echo "GitHub Actions will run Quality checks, generate notes and create the Release."

# -------------------------------
# Release entrypoint
# -------------------------------
.PHONY: release
release:
> @if [ "$(TYPE)" = "test" ]; then \
>   $(MAKE) release-test; \
> elif [ "$(TYPE)" = "prod" ]; then \
>   $(MAKE) release-prod VERSION=$(VERSION) TYPE=prod; \
> else \
>   echo "Unknown TYPE=$(TYPE). Use TYPE=prod for GitHub Release; PyPI uses Actions."; \
>   exit 1; \
> fi
