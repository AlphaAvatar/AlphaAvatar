# ===============================
# AlphaAvatar Release Automation
# ===============================

# 默认版本号（可通过命令行传入：make release VERSION=0.1.0 TYPE=test）
VERSION ?= 0.1.0
TYPE ?= test  # 可选：test 或 prod

# 默认 Python 版本
PYTHON ?= python3

# 主发布脚本路径
RELEASE_SCRIPT := scripts/release.sh

# -------------------------------
# 环境初始化
# -------------------------------
.PHONY: setup
setup:
	@echo "🚀 Setting up development environment..."
	uv venv .venv
	. .venv/bin/activate && uv sync --all-packages

# -------------------------------
# 本地构建检查（不推送）
# -------------------------------
.PHONY: dry-run
dry-run:
	@echo "🔍 Dry-run build for version $(VERSION)"
	DRY=1 $(RELEASE_SCRIPT) $(VERSION)

# -------------------------------
# TestPyPI 发布
# -------------------------------
.PHONY: release-test
release-test:
	@echo "🚢 Releasing to TestPyPI (version $(VERSION))"
	git tag test-v$(VERSION)
	git push origin test-v$(VERSION)

# -------------------------------
# 正式 PyPI 发布
# -------------------------------
.PHONY: release-prod
release-prod:
	@echo "🚀 Releasing to PyPI (version $(VERSION))"
	git tag v$(VERSION)
	git push origin v$(VERSION)

# -------------------------------
# 智能入口（TYPE 自动判断）
# -------------------------------
.PHONY: release
release:
	@if [ "$(TYPE)" = "test" ]; then \
		$(MAKE) release-test VERSION=$(VERSION); \
	else \
		$(MAKE) release-prod VERSION=$(VERSION); \
	fi
