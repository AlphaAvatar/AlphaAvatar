#!/usr/bin/env bash
set -euo pipefail

# -------------------------------
# Config
# -------------------------------
# 包目录（相对仓库根目录）的发布顺序：先依赖、再上层
PACKAGES=(
  "avatar-agents"
  "avatar-plugins/avatar-plugins-memory"
  "avatar-plugins/avatar-plugins-persona"
)

# PyPI 仓库名：pypi 或 testpypi
REPO="${REPO:-pypi}"              # 用法：REPO=testpypi ./release.sh 0.1.0
# Dry run：不执行发布、不推送，只做版本写入和构建
DRY="${DRY:-0}"                    # 用法：DRY=1 ./release.sh 0.1.0
# PyPI Token（必填）
PYPI_TOKEN="${PYPI_TOKEN:-}"

# -------------------------------
# Helpers
# -------------------------------
die() { echo "Error: $*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

get_version_file_from_pyproject() {
  # 从 pyproject.toml 里解析 [tool.hatch.version].path
  # 兼容 macOS/BSD grep：尽量用 awk+sed
  local proj="$1"
  awk '
    $0 ~ /^\[tool\.hatch\.version\]/ { inblock=1; next }
    inblock && $0 ~ /^\[/ { inblock=0 }
    inblock && $0 ~ /^path *=/ {
      match($0, /"([^"]+)"/, m); if (m[1] != "") { print m[1]; exit 0 }
    }
  ' "$proj"
}

set_version_in_file() {
  local file="$1"
  local version="$2"
  [[ -f "$file" ]] || die "version file not found: $file"
  # 用 Python 更稳妥地替换 __version__ = "x.y.z"
  python3 - "$file" "$version" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
ver = sys.argv[2]
s = p.read_text(encoding="utf-8")
if re.search(r'^__version__\s*=\s*["\'].*?["\']\s*$', s, flags=re.M):
    s = re.sub(r'^__version__\s*=\s*["\'].*?["\']\s*$', f'__version__ = "{ver}"', s, flags=re.M)
else:
    s = f'__version__ = "{ver}"\n' + s
p.write_text(s, encoding="utf-8")
print(f"Updated {p} -> {ver}")
PY
}

build_and_publish() {
  local dir="$1"
  echo "==> Building in $dir"
  ( cd "$dir" && uv build )
  if [[ "$DRY" == "1" ]]; then
    echo "DRY=1: skip publish for $dir"
  else
    [[ -n "$PYPI_TOKEN" ]] || die "PYPI_TOKEN is required for publishing"
    echo "==> Publishing $dir to $REPO"
    ( cd "$dir" && uv publish --repository "$REPO" --token "$PYPI_TOKEN" )
  fi
}

# -------------------------------
# Main
# -------------------------------
require_cmd git
require_cmd python3
require_cmd uv

VERSION="${1:-}"
[[ -n "$VERSION" ]] || die "Usage: ./release.sh <version> (e.g., 0.1.0). You can also set REPO=pypi|testpypi, DRY=1."

# 1) 检查工作区干净
if [[ "$DRY" != "1" ]]; then
  git diff --quiet || die "Working tree not clean. Commit or stash changes first."
  if git rev-parse "v$VERSION" >/dev/null 2>&1; then
    die "Git tag v$VERSION already exists."
  fi
fi

# 2) 逐包写入版本
for pkgdir in "${PACKAGES[@]}"; do
  pyproj="$pkgdir/pyproject.toml"
  [[ -f "$pyproj" ]] || die "Missing $pyproj"
  vpath="$(get_version_file_from_pyproject "$pyproj")"
  if [[ -z "$vpath" ]]; then
    # 回退：常见路径猜测
    if [[ -f "$pkgdir/alphaavatar/version.py" ]]; then
      vpath="alphaavatar/version.py"
    elif [[ -f "$pkgdir/alphaavatar/agents/version.py" ]]; then
      vpath="alphaavatar/agents/version.py"
    else
      die "Cannot locate [tool.hatch.version].path in $pyproj and no common fallback found."
    fi
  fi
  set_version_in_file "$pkgdir/$vpath" "$VERSION"
done

# 3) 提交与打标签
if [[ "$DRY" != "1" ]]; then
  git add -A
  git commit -m "chore(release): v$VERSION"
  git tag -a "v$VERSION" -m "Release v$VERSION"
fi

# 4) 构建并发布（按顺序）
for pkgdir in "${PACKAGES[@]}"; do
  build_and_publish "$pkgdir"
done

# 5) 推送
if [[ "$DRY" != "1" ]]; then
  git push
  git push --tags
fi

echo "Done. Version: $VERSION | Repo: $REPO | DRY=$DRY"
