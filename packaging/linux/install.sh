#!/usr/bin/env bash
# Install AlphaAvatar's Linux x86_64 base package, as CI builds it with packaging/linux/build.sh;
# then `alphaavatar setup` installs the capabilities a person chooses.
#
#   bash install.sh --version 0.6.9      # the package of a GitHub release
#   bash install.sh --file PACKAGE       # one already downloaded, such as a CI build of a commit
#   bash install.sh --url URL            # one from a mirror
#
# The package's SHA-256 comes from --sha256, or else from the .sha256 file beside it. Needs
# tar, gzip and coreutils, and curl to download; the package brings its own Python.
#
# Program files only; ALPHAAVATAR_HOME, Avatar workspaces and model caches live elsewhere:
#   <prefix>/versions/<version>-<commit>/        each package unpacked and checked before use
#   <prefix>/envs/<plan>/                        what `alphaavatar setup` installs over one
#   <bin-dir>/alphaavatar -> <prefix>/current/bin/alphaavatar   created before the switch,
#                                                    never over anything already there
#   <prefix>/current -> versions/... or envs/... switched last
#   <prefix>/.install.lock                       the lock every run and setup take, kept
# Installing the version current already runs keeps its setup environment. A failed or
# interrupted run removes only what it created, judged by where current points when it ends;
# the current version, the command and existing data stay as they were, and a path this script
# cannot tell it made is never removed.
set -euo pipefail

RELEASES="https://github.com/AlphaAvatar/AlphaAvatar/releases/download"

die() { echo "Error: $*" >&2; exit 1; }

usage() {
  cat <<EOF
usage: install.sh (--version X.Y.Z | --file PACKAGE | --url URL) [--sha256 HEX]
                  [--prefix DIR] [--bin-dir DIR]
  --prefix   program files (default: \$ALPHAAVATAR_INSTALL_DIR or ~/.local/lib/alphaavatar)
  --bin-dir  where the alphaavatar command goes (default: \$ALPHAAVATAR_BIN_DIR or ~/.local/bin)
EOF
}

version="" url="" file="" sha256=""
prefix="${ALPHAAVATAR_INSTALL_DIR:-$HOME/.local/lib/alphaavatar}"
bin_dir="${ALPHAAVATAR_BIN_DIR:-$HOME/.local/bin}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version|--file|--url|--sha256|--prefix|--bin-dir)
      [[ $# -ge 2 && -n "$2" ]] || die "$1 needs a value"
      case "$1" in
        --version) version="$2" ;;
        --file) file="$2" ;;
        --url) url="$2" ;;
        --sha256) sha256="$2" ;;
        --prefix) prefix="$2" ;;
        --bin-dir) bin_dir="$2" ;;
      esac
      shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
(( (${#version} > 0) + (${#file} > 0) + (${#url} > 0) == 1 )) || { usage >&2; exit 2; }
if [[ -n "$version" ]]; then
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] || die "Invalid version"
  url="$RELEASES/v$version/alphaavatar-$version-linux-x86_64.tar.gz"
fi
[[ -z "$sha256" || "$sha256" =~ ^[0-9a-f]{64}$ ]] || die "--sha256 takes 64 hex digits"
for cmd in tar gzip sha256sum flock realpath mktemp getconf sort grep cut cmp ${url:+curl}; do
  command -v "$cmd" >/dev/null 2>&1 || die "Missing command: $cmd"
done
[[ "$(uname -s)/$(uname -m)" == "Linux/x86_64" ]] || die "This package is for Linux x86_64"

[[ "$prefix" == /* && "$bin_dir" == /* ]] || die "--prefix and --bin-dir must be absolute"
prefix="$(realpath -m "$prefix")" bin_dir="$(realpath -m "$bin_dir")"
home="$(realpath -m "${ALPHAAVATAR_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/alphaavatar}")"
if [[ "$prefix/" == "$home/"* || "$home/" == "$prefix/"* ]]; then
  die "Keep program files ($prefix) and ALPHAAVATAR_HOME ($home) apart"
fi
entry="$bin_dir/alphaavatar" link="$prefix/current/bin/alphaavatar"
if [[ -e "$entry" || -L "$entry" ]] && [[ "$(readlink "$entry")" != "$link" ]]; then
  if [[ "$(readlink "$entry")" == */current/bin/alphaavatar ]]; then
    die "$entry runs the AlphaAvatar installed in $(dirname "$(dirname "$(dirname \
      "$(readlink "$entry")")")"); choose another --bin-dir, or that --prefix"
  fi
  die "$entry exists and is not AlphaAvatar's command; it is left as it is"
fi
if [[ "$(readlink "$entry" || true)" != "$link" ]]; then
  # The command must be creatable before anything is downloaded or switched.
  probe="$bin_dir"
  while [[ ! -e "$probe" && ! -L "$probe" ]]; do probe="$(dirname "$probe")"; done
  [[ -d "$probe" && -w "$probe" ]] || die "Cannot create $entry: $probe is not a writable directory"
fi

made_prefix=""
[[ -e "$prefix" ]] || made_prefix=1
mkdir -p "$prefix"
# The lock setup takes too: a regular file of the prefix, never through a link, never truncated,
# never removed: every run locks the same file.
lock="$prefix/.install.lock"
refused="$lock is not a lock file this script or setup made; it is left as it is"
[[ ! -L "$lock" && ( ! -e "$lock" || -f "$lock" ) ]] || die "$refused"
# Read and write: opening waits on no pipe put there meanwhile, and what it opened is checked.
exec 9<> "$lock"
[[ -f /dev/fd/9 ]] || die "$refused"
flock -n 9 || die "Another installation into $prefix is running"
previous="$(readlink "$prefix/current" || true)"
# What this script or setup made: versions/<name> or a marked envs/<name> of this prefix,
# reached through no other link.
if [[ -e "$prefix/current" || -L "$prefix/current" ]] \
    && ! { [[ "$previous" =~ ^(versions|envs)/[0-9A-Za-z][0-9A-Za-z._+-]*$ ]] \
      && [[ "$(realpath -m "$prefix/$previous")" == "$prefix/$previous" ]] \
      && [[ "$previous" == versions/* || -f "$prefix/$previous/.alphaavatar-setup" ]]; }; then
  die "$prefix/current is not a link this script or setup made; it is left as it is"
fi
[[ ! -L "$prefix/versions" ]] || die "$prefix/versions is a link; it is left as it is"
mkdir -p "$prefix/versions"
for dir in "$prefix/versions"/.install-*; do
  # A stage whose run was killed, marked as this script's: the lock is ours now.
  if [[ -d "$dir" && ! -L "$dir" && -f "$dir/.alphaavatar-install" ]]; then rm -rf -- "$dir"; fi
done
# This run's own directory, on the same file system as the versions it renames into.
stage="$(mktemp -d "$prefix/versions/.install-XXXXXX")"
touch "$stage/.alphaavatar-install"
fresh="" made_entry=""
cleanup() {
  trap '' INT TERM HUP  # Finish cleaning up whatever else arrives.
  rm -rf -- "$stage"
  # Removed unless current points to it: a signal may land just after the switch.
  if [[ -n "$fresh" && "$(readlink -f "$prefix/current" || true)" != "$(readlink -f "$fresh")" ]]
  then
    rm -rf -- "$fresh"
  fi
  # A first installation that ends without a current version leaves no command either: the
  # link it made, if it still points here. The prefix it made keeps the lock file alone, which
  # another run may have opened already: removed, the next would lock a new one beside it.
  if [[ -n "$made_entry" && ! -e "$prefix/current" && "$(readlink "$entry")" == "$link" ]]; then
    rm -f -- "$entry"
  fi
  if [[ -n "$made_prefix" && ! -e "$prefix/current" ]]; then
    rmdir -- "$prefix/versions" 2>/dev/null || true
  fi
}
trap cleanup EXIT  # Also on SIGINT and SIGTERM: bash exits through the EXIT trap.

# The package is this run's own copy: what is checked is what unpacks and runs, whatever
# happens to the source meanwhile.
package="$stage/package.tar.gz"
if [[ -n "$url" ]]; then
  echo "Downloading $url"
  curl -fL --retry 3 $([[ -t 2 ]] && echo --progress-bar || echo -sS) -o "$package" "$url"
  [[ -n "$sha256" ]] || sha256="$(curl -fsSL --retry 3 "$url.sha256" | cut -d' ' -f1)"
else
  [[ -f "$file" ]] || die "No package at $file"
  if [[ -z "$sha256" ]]; then
    [[ -f "$file.sha256" ]] || die "No SHA-256: pass --sha256 or keep $file.sha256 beside it"
    sha256="$(cut -d' ' -f1 "$file.sha256")"
  fi
  cp -- "$file" "$package" || die "Cannot copy $file"
fi
[[ "$(sha256sum < "$package" | cut -d' ' -f1)" == "$sha256" ]] \
  || die "${url:-$file} does not match its SHA-256: an incomplete download or another file"

# The manifest first: a version already installed is neither unpacked again nor given space.
mkdir "$stage/tree"
tar -xzf "$package" -C "$stage/tree" --no-same-owner --wildcards '*/share/alphaavatar/manifest.json' \
  || die "Not an AlphaAvatar package: no manifest"
unpacked=("$stage/tree"/*)
[[ ${#unpacked[@]} -eq 1 && -d "${unpacked[0]}" && ! -L "${unpacked[0]}" ]] \
  || die "Not an AlphaAvatar package: expected one top-level directory"
candidate="${unpacked[0]}"
manifest="$candidate/share/alphaavatar/manifest.json"
installed=""
for dir in "$prefix/versions"/*; do
  [[ -d "$dir" && ! -L "$dir" ]] || continue
  if cmp -s "$manifest" "$dir/share/alphaavatar/manifest.json"; then installed="$dir"; fi
done
[[ -n "$installed" ]] || tar -xzf "$package" -C "$stage/tree" --no-same-owner
fields="$("${installed:-$candidate}/python/bin/python3" -I -c 'import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
print(m["id"], m["version"], m["glibc"], *m["cpu"])
print(*m["imports"])' "$manifest")" || die "Not an AlphaAvatar package: no readable manifest"
{ read -r id package_version glibc cpu; read -r imports; } <<< "$fields"
[[ "$id" =~ ^[0-9A-Za-z][0-9A-Za-z.+-]*$ ]] || die "Invalid package id"
[[ -z "$version" || "$package_version" == "$version" ]] || die "The package holds $package_version"

found="$(getconf GNU_LIBC_VERSION 2>/dev/null | cut -d' ' -f2)" || true
[[ -n "$found" ]] || die "Cannot read the glibc version; this package needs glibc"
printf '%s\n%s\n' "$glibc" "$found" | sort -V -C || die "Needs glibc $glibc or newer; found $found"
for flag in $cpu; do
  grep -qw "$flag" /proc/cpuinfo || die "Needs an x86-64 CPU with $cpu; $flag is missing"
done

check() {
  # From /, isolated from the caller's Python: the command, its help, and each native library
  # the bundle loads. Chained: errexit does not apply where a caller tests the status.
  # shellcheck disable=SC2086
  (
    cd / \
      && [[ "$("$1/bin/alphaavatar" --version)" == "AlphaAvatar $package_version" ]] \
      && "$1/bin/alphaavatar" --help > /dev/null \
      && "$1/python/bin/python3" -I -c 'import importlib, sys
for name in sys.argv[1:]:
    importlib.import_module(name)' $imports
  )
}

target="$prefix/versions/$id"
if [[ -n "$installed" ]]; then
  [[ "$installed" == "$target" ]] || die "$installed holds AlphaAvatar $id under another name"
  echo "AlphaAvatar $id is already installed; checking it"
  check "$target" || die "$target does not run; remove it and install again"
elif [[ -e "$target" || -L "$target" ]]; then
  die "$target exists and holds something else; it is left as it is"
else
  echo "Checking AlphaAvatar $id"
  check "$candidate" || die "The package does not run on this machine"
  mv -T "$candidate" "$target"
  fresh="$target"  # This run's: removed at exit unless current points to it.
  check "$target" || die "The package does not run from $target"
fi

if [[ "$(readlink "$entry" || true)" != "$link" ]]; then
  mkdir -p "$bin_dir"
  made_entry=1  # First: a signal may land the moment the link exists.
  # Created only if nothing is there: another installation may have made it meanwhile.
  if ! ln -sT "$link" "$entry" 2>/dev/null; then
    made_entry=""
    die "$entry appeared meanwhile and runs $(readlink "$entry" || echo something else); choose another --bin-dir"
  fi
fi
switch="versions/$id"
# A setup environment over this very version stays current: its capabilities remain.
if [[ "$previous" == envs/* ]] && "$target/python/bin/python3" -I -c 'import json, sys
sys.exit(json.load(open(sys.argv[1], encoding="utf-8"))["base"] != sys.argv[2])' \
    "$prefix/$previous/share/alphaavatar/plan.json" "$id" 2>/dev/null; then
  switch="$previous"
fi
ln -s "$switch" "$stage/current"
mv -Tf "$stage/current" "$prefix/current"
if ! (cd / && [[ "$("$entry" --version)" == "AlphaAvatar $package_version" ]]); then
  if [[ -n "$previous" ]]; then
    ln -s "$previous" "$stage/previous" && mv -Tf "$stage/previous" "$prefix/current"
  else
    rm -f -- "$prefix/current"
  fi
  die "$entry does not run AlphaAvatar $package_version; the previous version stays current"
fi

echo "Installed AlphaAvatar $id: $entry -> $prefix/current -> $switch"
if [[ "$previous" == envs/* && "$switch" != "$previous" ]]; then
  echo "The capabilities \`alphaavatar setup\` installed belong to the previous version."
fi
[[ "$switch" == envs/* ]] || echo "Next: alphaavatar setup    # choose capabilities; it installs them"
case ":$PATH:" in
  *":$bin_dir:"*) ;;
  *) echo "Add $bin_dir to PATH to run alphaavatar from any directory, e.g. in ~/.profile:"
     echo "  export PATH=\"$bin_dir:\$PATH\"" ;;
esac
