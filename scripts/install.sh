#!/usr/bin/env bash
# Install one AlphaAvatar release on Linux x86_64 with glibc 2.28 or newer.
#
#   curl -fsSLO https://raw.githubusercontent.com/AlphaAvatar/AlphaAvatar/<ref>/scripts/install.sh
#   bash install.sh --ref <ref>
#
# Needs curl, tar, gzip and coreutils, not Python or Node: a pinned uv brings CPython and
# installs alpha-avatar-host[livekit] from the release's source and uv.lock.
#
# Program files only; ALPHAAVATAR_HOME, Avatar workspaces and model caches live elsewhere:
#   <prefix>/versions/<version>-<commit>/   one environment per release, built in place
#   <prefix>/current -> versions/...        switched only after that environment passes checks
#   <bin-dir>/alphaavatar -> <prefix>/current/bin/alphaavatar
set -euo pipefail

UV_VERSION="0.10.0"
UV_SHA256="230e328948c92dd1ebad83949c4d56e83813dfe9c6362a4c519e6a227973f1ae"
UV_URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION"
SOURCE_URL="https://codeload.github.com/AlphaAvatar/AlphaAvatar/tar.gz"
PACKAGE="alpha-avatar-host"
EXTRA="livekit"
GLIBC_MIN="2.28" # The newest manylinux baseline among the locked wheels (livekit).

die() { echo "Error: $*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

usage() {
  cat <<'EOF'
Usage: install.sh --ref REF [--prefix DIR] [--bin-dir DIR]

  --ref      Release tag (vX.Y.Z), or a full 40-character commit SHA for development builds
  --prefix   Program files; default $ALPHAAVATAR_INSTALL_DIR or ~/.local/lib/alphaavatar
  --bin-dir  Location of the alphaavatar command; default $ALPHAAVATAR_BIN_DIR or ~/.local/bin
EOF
}

ref=""
prefix="${ALPHAAVATAR_INSTALL_DIR:-$HOME/.local/lib/alphaavatar}"
bin_dir="${ALPHAAVATAR_BIN_DIR:-$HOME/.local/bin}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref | --prefix | --bin-dir)
      [[ $# -ge 2 ]] || die "$1 needs a value"
      case "$1" in --ref) ref="$2" ;; --prefix) prefix="$2" ;; *) bin_dir="$2" ;; esac
      shift 2
      ;;
    -h | --help) usage; exit 0 ;;
    *) usage >&2; die "Unknown argument: $1" ;;
  esac
done

# A branch moves; a tag or a commit names one source tree and its uv.lock.
[[ "$ref" =~ ^(v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?|[0-9a-f]{40})$ ]] \
  || die "--ref must be a release tag (vX.Y.Z) or a full 40-character commit SHA"

for cmd in curl tar gzip sha256sum flock realpath getconf sort; do require_cmd "$cmd"; done
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] \
  || die "Supported platform: Linux x86_64; found $(uname -s) $(uname -m)"
glibc="$(getconf GNU_LIBC_VERSION 2>/dev/null || true)"
glibc="${glibc#glibc }"
[[ -n "$glibc" ]] || die "glibc not found; musl-based distributions are not supported"
printf '%s\n%s\n' "$GLIBC_MIN" "$glibc" | sort -V -C || die "glibc $glibc is older than $GLIBC_MIN"

[[ "$prefix" == /* && "$bin_dir" == /* ]] || die "--prefix and --bin-dir must be absolute paths"
prefix="$(realpath -m "$prefix")"
bin_dir="$(realpath -m "$bin_dir")"
# Releases are replaceable program files; the application home holds user data.
data="$(realpath -m "${ALPHAAVATAR_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/alphaavatar}")"
case "$prefix/" in "$data/"*) die "--prefix $prefix lies inside the application home $data" ;; esac
case "$data/" in "$prefix/"*) die "The application home $data lies inside --prefix $prefix" ;; esac
entry="$bin_dir/alphaavatar"
link="$prefix/current/bin/alphaavatar"
if [[ -e "$entry" || -L "$entry" ]] && [[ "$(readlink "$entry" || true)" != "$link" ]]; then
  die "$entry was not created by this installer; remove it or pass --bin-dir"
fi

unset VIRTUAL_ENV PYTHONPATH PYTHONHOME UV_PYTHON
export UV_CACHE_DIR="$prefix/cache" UV_PYTHON_INSTALL_DIR="$prefix/python" UV_MANAGED_PYTHON=1

mkdir -p "$prefix/versions"
exec 9>"$prefix/.install.lock"
flock -n 9 || die "Another installation is running in $prefix"
# Beside the result, so finished files arrive by an atomic rename. The fixed path keeps the
# source location that packages record identical between installations.
work="$prefix/.work"
rm -rf "$work"
mkdir "$work"
partial=""
# Also runs on SIGINT and SIGTERM: an interrupted candidate is removed, and current still
# names the previous release.
trap 'rm -rf "$work"; [[ -z "$partial" ]] || rm -rf "$partial"' EXIT

uv="$prefix/tools/uv-$UV_VERSION/uv"
if [[ ! -x "$uv" ]]; then
  echo "Downloading uv $UV_VERSION"
  curl -fsSL --retry 3 -o "$work/uv.tar.gz" "$UV_URL/uv-x86_64-unknown-linux-gnu.tar.gz"
  echo "$UV_SHA256  $work/uv.tar.gz" | sha256sum -c --quiet - || die "uv failed its SHA-256 check"
  mkdir -p "$work/uv" "${uv%/*}"
  tar -xzf "$work/uv.tar.gz" -C "$work/uv" --strip-components=1
  mv "$work/uv/uv" "$uv"
fi

echo "Downloading AlphaAvatar $ref"
curl -fsSL --retry 3 -o "$work/source.tar.gz" "$SOURCE_URL/$ref"
# git archive names the commit in its pax header, so a tag resolves to one commit here.
commit="$({ gzip -dc "$work/source.tar.gz" || true; } | head -c 1024 | tr -d '\0' \
  | sed -n 's/.*comment=\([0-9a-f]\{40\}\).*/\1/p')"
[[ -n "$commit" ]] || die "The source archive for $ref does not name its commit"
[[ "$ref" == v* || "$ref" == "$commit" ]] || die "The source archive is $commit, not $ref"
mkdir "$work/source"
tar -xzf "$work/source.tar.gz" -C "$work/source" --strip-components=1
version="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' \
  "$work/source/avatar-host/alphaavatar/host/version.py")"
[[ -n "$version" ]] || die "Cannot read the Host version of $ref"
[[ "$ref" != v* || "$ref" == "v$version" ]] || die "Tag $ref carries Host version $version"

check() { # The command must run from any directory before it becomes the stable entry.
  local out
  out="$(cd / && "$1" --version)" || die "$1 --version failed"
  [[ "$out" == "AlphaAvatar $version" ]] || die "$1 reports '$out', not 'AlphaAvatar $version'"
  (cd / && "$1" --help >/dev/null) || die "$1 --help failed"
}

name="$version-${commit:0:12}"
target="$prefix/versions/$name"
if [[ -f "$target/alphaavatar-install.json" ]]; then
  echo "AlphaAvatar $version ($commit) is already installed in $target"
  check "$target/bin/alphaavatar"
else
  # Only a finished environment is ever current; anything else here is a failed attempt.
  [[ "$(readlink "$prefix/current" || true)" != "versions/$name" ]] \
    || die "$target is current but incomplete; refusing to modify it"
  rm -rf "$target"
  partial="$target"
  echo "Installing AlphaAvatar $version ($commit) into $target"
  # Environments are not relocatable, so each release is built in its final directory.
  (cd "$work/source" && UV_PROJECT_ENVIRONMENT="$target" "$uv" sync --locked --no-editable \
    --compile-bytecode --no-default-groups --package "$PACKAGE" --extra "$EXTRA")
  check "$target/bin/alphaavatar"
  "$uv" pip check --python "$target/bin/python" >/dev/null || die "Inconsistent packages in $target"
  "$target/bin/python" -I - "$target/alphaavatar-install.json" "$ref" "$commit" "$version" \
    "$PACKAGE[$EXTRA]" "$UV_VERSION" <<'PY'
import json
import os
import platform
import sys
from datetime import UTC, datetime

path, ref, commit, version, package, uv = sys.argv[1:]
record = {
    "ref": ref,
    "commit": commit,
    "version": version,
    "package": package,
    "uv": uv,
    "python": platform.python_version(),
    "installed_at": datetime.now(UTC).isoformat(timespec="seconds"),
}
with open(f"{path}.tmp", "x", encoding="utf-8") as stream:
    json.dump(record, stream, indent=2)
    stream.write("\n")
os.replace(f"{path}.tmp", path)
PY
  partial=""
fi

# Switch the stable entry to the verified release; each rename is atomic.
ln -s "versions/$name" "$work/current"
mv -Tf "$work/current" "$prefix/current"
mkdir -p "$bin_dir"
if [[ "$(readlink "$entry" || true)" != "$link" ]]; then
  ln -s "$link" "$bin_dir/.alphaavatar.$$"
  mv -Tf "$bin_dir/.alphaavatar.$$" "$entry"
fi
check "$entry"

echo "Installed AlphaAvatar $version ($commit)"
echo "  command: $entry"
echo "  release: $target"
case ":$PATH:" in
  *":$bin_dir:"*) ;;
  *) echo "Add $bin_dir to PATH to run alphaavatar from any directory:"
     echo "  export PATH=\"$bin_dir:\$PATH\"" ;;
esac
