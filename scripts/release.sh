#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------
# Config
# ----------------------------------
PACKAGES=(
  "avatar-agents"
  "avatar-plugins/avatar-plugins-character"
  "avatar-plugins/avatar-plugins-deepresearch"
  "avatar-plugins/avatar-plugins-mcp"
  "avatar-plugins/avatar-plugins-memory"
  "avatar-plugins/avatar-plugins-persona"
  "avatar-plugins/avatar-plugins-rag"
)

REPO="${REPO:-pypi}"      # pypi | testpypi
DRY="${DRY:-0}"
SKIP_GIT="${SKIP_GIT:-0}"
PYPI_TOKEN="${PYPI_TOKEN:-}"

# ----------------------------------
# Helpers
# ----------------------------------
die() { echo "Error: $*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

get_version_file_from_pyproject() {
  local proj="$1"
  awk '
    $0 ~ /^\[tool\.hatch\.version\]/ { inblock=1; next }
    inblock && $0 ~ /^\[/ { inblock=0 }
    inblock && $0 ~ /^path *=/ {
      match($0, /"([^"]+)"/, m); if (m[1] != "") { print m[1]; exit 0 }
    }
  ' "$proj"
}

get_project_name_from_pyproject() {
  # 解析 [project].name
  local proj="$1"
  awk '
    $0 ~ /^\[project\]/ { inblock=1; next }
    inblock && $0 ~ /^\[/ { inblock=0 }
    inblock && $0 ~ /^name *=/ {
      match($0, /"([^"]+)"/, m); if (m[1] != "") { print m[1]; exit 0 }
    }
  ' "$proj"
}

set_version_in_file() {
  local file="$1"
  local version="$2"
  [[ -f "$file" ]] || die "version file not found: $file"
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
  local version="$2"

  echo "==> Building in $dir"
  ( cd "$dir" && uv build )

  # 产物在仓库根 dist/
  local dist_root="dist"
  [[ -d "$dist_root" ]] || die "dist directory not found at repo root"

  # 解析包名并定位产物文件（基名要将 - 规范化为 _）
  local pyproj="$dir/pyproject.toml"
  local pkg_name
  pkg_name="$(get_project_name_from_pyproject "$pyproj")"
  [[ -n "$pkg_name" ]] || die "Cannot read [project].name from $pyproj"

  local fname_base="${pkg_name//-/_}-${version}"

  mapfile -t files < <(ls -1 "$dist_root"/"$fname_base"* 2>/dev/null || true)
  [[ ${#files[@]} -gt 0 ]] || die "No built files found for $pkg_name ($fname_base*) in $dist_root"

  echo "Artifacts to publish:"
  printf '  %s\n' "${files[@]}"

  # 先做元数据检查（能提前发现 README/metadata 问题）
  echo "==> twine check"
  python -m twine check "${files[@]}"

  if [[ "$DRY" == "1" ]]; then
    echo "DRY=1: skip publish for $dir"
    return 0
  fi

  [[ -n "$PYPI_TOKEN" ]] || die "PYPI_TOKEN is required for publishing"

  local repo_url
  if [[ "$REPO" == "testpypi" ]]; then
    repo_url="https://test.pypi.org/legacy/"
  else
    repo_url="https://upload.pypi.org/legacy/"
  fi

  echo "==> Publishing $pkg_name to $REPO ($repo_url) via twine"
  TWINE_NON_INTERACTIVE=1 python -m twine upload \
    --repository-url "$repo_url" \
    --skip-existing \
    -u __token__ \
    -p "$PYPI_TOKEN" \
    "${files[@]}"
}

# ----------------------------------
# Main
# ----------------------------------
require_cmd git
require_cmd python3
require_cmd uv

VERSION="${1:-}"
[[ -n "$VERSION" ]] || die "Usage: ./scripts/release.sh <version> (e.g., 0.1.0)"

echo "Release config -> VERSION=$VERSION REPO=$REPO DRY=$DRY SKIP_GIT=$SKIP_GIT"

# 本地发布：确保工作区干净 & tag 未存在；CI（SKIP_GIT=1）跳过
if [[ "$DRY" != "1" && "$SKIP_GIT" != "1" ]]; then
  git diff --quiet || die "Working tree not clean. Commit or stash changes first."
  if git rev-parse "v$VERSION" >/dev/null 2>&1; then
    die "Git tag v$VERSION already exists."
  fi
fi

# 写版本号
for pkgdir in "${PACKAGES[@]}"; do
  pyproj="$pkgdir/pyproject.toml"
  [[ -f "$pyproj" ]] || die "Missing $pyproj"
  vpath="$(get_version_file_from_pyproject "$pyproj")"
  if [[ -z "$vpath" ]]; then
    if [[ -f "$pkgdir/alphaavatar/version.py" ]]; then
      vpath="alphaavatar/version.py"
    elif [[ -f "$pkgdir/alphaavatar/agents/version.py" ]]; then
      vpath="alphaavatar/agents/version.py"
    else
      die "Cannot locate [tool.hatch.version].path in $pyproj and no fallback found."
    fi
  fi
  set_version_in_file "$pkgdir/$vpath" "$VERSION"
done

# 本地发布才提交/打 tag
if [[ "$DRY" != "1" && "$SKIP_GIT" != "1" ]]; then
  git add -A
  git commit -m "chore(release): v$VERSION"
  git tag -a "v$VERSION" -m "Release v$VERSION"
fi

# 逐包构建并上传（只传该包文件）
for pkgdir in "${PACKAGES[@]}"; do
  build_and_publish "$pkgdir" "$VERSION"
done

# 本地发布才推送
if [[ "$DRY" != "1" && "$SKIP_GIT" != "1" ]]; then
  git push
  git push --tags
fi

echo "Done. Version: $VERSION | Repo: $REPO | DRY=$DRY | SKIP_GIT=$SKIP_GIT"
