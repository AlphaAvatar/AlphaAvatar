# ===============================
# AlphaAvatar Release Automation
# ===============================
#
# Usage:
#   make prepare-release-config
#   make prepare-release VERSION=0.6.1
#   make release VERSION=0.6.1 TYPE=prod PREVIOUS_TAG=v0.6.0
#   make release VERSION=0.6.1 TYPE=test
#
# Notes:
#   - This Makefile uses ".RECIPEPREFIX := >" to avoid Tab-related Makefile errors.
#   - For prod releases, docs/releases/vX.Y.Z.md must exist and be committed.
#   - GitHub generated PR notes will be appended after manual notes when GH_RELEASE=1 and GH_GENERATE_NOTES=1.

.RECIPEPREFIX := >

VERSION ?= 0.1.0
TYPE ?= test

PYTHON ?= python3

RELEASE_SCRIPT := scripts/release.sh

TAG := v$(VERSION)
TEST_TAG := test-v$(VERSION)

RELEASE_NOTES := docs/releases/$(TAG).md
RELEASE_TITLE := AlphaAvatar $(TAG)

RELEASE_CONFIG := .github/release.yml
GENERATED_RELEASE_DIR := docs/releases/.generated
GENERATED_PR_NOTES := $(GENERATED_RELEASE_DIR)/$(TAG).pr.md
FULL_RELEASE_NOTES := $(GENERATED_RELEASE_DIR)/$(TAG).full.md

# Optional previous tag used by GitHub generated release notes.
# Example:
#   make release VERSION=0.6.1 TYPE=prod PREVIOUS_TAG=v0.6.0
PREVIOUS_TAG ?=

# Whether to create/update GitHub Release after pushing the tag.
# Set GH_RELEASE=0 to skip.
GH_RELEASE ?= 0

# Whether to append GitHub generated PR notes after manual release notes.
# Set GH_GENERATE_NOTES=0 to use manual notes only.
GH_GENERATE_NOTES ?= 1

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
> @echo "  4. Run: make release VERSION=$(VERSION) TYPE=prod PREVIOUS_TAG=v0.6.0"

# -------------------------------
# Check release preconditions
# -------------------------------
.PHONY: check-release
check-release:
> @echo "🔎 Checking release preconditions for $(TAG)..."
> @if [ "$(TYPE)" = "prod" ] && [ ! -f "$(RELEASE_NOTES)" ]; then \
>   echo "❌ Missing release notes: $(RELEASE_NOTES)"; \
>   echo "Run: make prepare-release VERSION=$(VERSION)"; \
>   exit 1; \
> fi
> @if [ "$(TYPE)" = "prod" ] && [ "$(GH_RELEASE)" = "1" ] && [ "$(GH_GENERATE_NOTES)" = "1" ] && [ ! -f "$(RELEASE_CONFIG)" ]; then \
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
> @if [ "$(TYPE)" = "test" ] && git rev-parse "$(TEST_TAG)" >/dev/null 2>&1; then \
>   echo "❌ Local tag $(TEST_TAG) already exists."; \
>   exit 1; \
> fi
> @if [ "$(TYPE)" = "test" ] && git ls-remote --tags origin "$(TEST_TAG)" | grep -q "$(TEST_TAG)"; then \
>   echo "❌ Remote tag $(TEST_TAG) already exists."; \
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
# Build final GitHub Release notes
# manual notes + generated PR notes
# -------------------------------
.PHONY: build-release-notes
build-release-notes:
> @echo "🧩 Building final release notes for $(TAG)..."
> @if [ ! -f "$(RELEASE_NOTES)" ]; then \
>   echo "❌ Missing release notes: $(RELEASE_NOTES)"; \
>   exit 1; \
> fi
> @mkdir -p "$(GENERATED_RELEASE_DIR)"
> @cp "$(RELEASE_NOTES)" "$(FULL_RELEASE_NOTES)"
> @if [ "$(GH_GENERATE_NOTES)" = "1" ]; then \
>   if command -v gh >/dev/null 2>&1; then \
>     echo "📝 Generating PR notes from GitHub..."; \
>     if [ -n "$(PREVIOUS_TAG)" ]; then \
>       gh api "repos/:owner/:repo/releases/generate-notes" \
>         -f tag_name="$(TAG)" \
>         -f previous_tag_name="$(PREVIOUS_TAG)" \
>         -f configuration_file_path="$(RELEASE_CONFIG)" \
>         --jq '.body' > "$(GENERATED_PR_NOTES)"; \
>     else \
>       gh api "repos/:owner/:repo/releases/generate-notes" \
>         -f tag_name="$(TAG)" \
>         -f configuration_file_path="$(RELEASE_CONFIG)" \
>         --jq '.body' > "$(GENERATED_PR_NOTES)"; \
>     fi; \
>     if [ -s "$(GENERATED_PR_NOTES)" ]; then \
>       printf '\n\n---\n\n' >> "$(FULL_RELEASE_NOTES)"; \
>       cat "$(GENERATED_PR_NOTES)" >> "$(FULL_RELEASE_NOTES)"; \
>       echo "✅ Appended generated PR notes."; \
>     else \
>       echo "ℹ️ Generated PR notes are empty. Using manual notes only."; \
>     fi; \
>   else \
>     echo "⚠️ GitHub CLI 'gh' not found. Using manual notes only."; \
>   fi; \
> else \
>   echo "ℹ️ GH_GENERATE_NOTES=$(GH_GENERATE_NOTES). Using manual notes only."; \
> fi
> @echo "✅ Final release notes: $(FULL_RELEASE_NOTES)"

# -------------------------------
# TestPyPI release trigger
# -------------------------------
.PHONY: release-test
release-test: check-release push-branch
> @echo "🚢 Releasing to TestPyPI trigger tag $(TEST_TAG)"
> git tag "$(TEST_TAG)"
> git push origin "$(TEST_TAG)"

# -------------------------------
# PyPI release trigger
# -------------------------------
.PHONY: release-prod
release-prod: check-release push-branch
> @echo "🚀 Releasing to PyPI trigger tag $(TAG)"
> git tag "$(TAG)"
> git push origin "$(TAG)"
> @if [ "$(GH_RELEASE)" = "1" ]; then \
>   $(MAKE) release-github VERSION=$(VERSION) PREVIOUS_TAG="$(PREVIOUS_TAG)" GH_GENERATE_NOTES="$(GH_GENERATE_NOTES)"; \
> else \
>   echo "ℹ️ Skipping GitHub Release because GH_RELEASE=$(GH_RELEASE)"; \
> fi

# -------------------------------
# Create or update GitHub Release
# -------------------------------
.PHONY: release-github
release-github: build-release-notes
> @if ! command -v gh >/dev/null 2>&1; then \
>   echo "⚠️ GitHub CLI 'gh' not found. Skipping GitHub Release."; \
>   echo "You can manually create it with notes from $(FULL_RELEASE_NOTES)."; \
>   exit 0; \
> fi
> @if gh release view "$(TAG)" >/dev/null 2>&1; then \
>   echo "📝 Updating GitHub Release $(TAG)..."; \
>   gh release edit "$(TAG)" --title "$(RELEASE_TITLE)" --notes-file "$(FULL_RELEASE_NOTES)"; \
> else \
>   echo "📝 Creating GitHub Release $(TAG)..."; \
>   gh release create "$(TAG)" --title "$(RELEASE_TITLE)" --notes-file "$(FULL_RELEASE_NOTES)" --verify-tag; \
> fi
> @echo "✅ GitHub Release ready: $(TAG)"

# -------------------------------
# Smart release entry
# -------------------------------
.PHONY: release
release:
> @if [ "$(TYPE)" = "test" ]; then \
>   $(MAKE) release-test VERSION=$(VERSION) TYPE=$(TYPE); \
> elif [ "$(TYPE)" = "prod" ]; then \
>   $(MAKE) release-prod VERSION=$(VERSION) TYPE=$(TYPE) PREVIOUS_TAG="$(PREVIOUS_TAG)" GH_RELEASE="$(GH_RELEASE)" GH_GENERATE_NOTES="$(GH_GENERATE_NOTES)"; \
> else \
>   echo "❌ Unknown TYPE=$(TYPE). Use TYPE=test or TYPE=prod."; \
>   exit 1; \
> fi
