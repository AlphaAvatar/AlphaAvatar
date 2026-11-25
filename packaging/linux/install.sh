#!/usr/bin/env bash
# Install AlphaAvatar's Linux x86_64 base package, as CI builds it with packaging/linux/build.sh;
# then `alphaavatar setup` installs the capabilities a person chooses.
#
#   bash install.sh                      # the latest release's package
#   bash install.sh --version 0.6.9      # the package of a GitHub release
#   bash install.sh --file PACKAGE       # one already downloaded, such as a CI build of a commit
#   bash install.sh --url URL            # one from a mirror
#   curl -fsSL https://github.com/AlphaAvatar/AlphaAvatar/releases/latest/download/install.sh | bash
#
# The latest release is named once, by the manifest it publishes beside its package; the
# package and its .sha256 come from that release, and the package must hold that manifest. A
# latest release without them is an error: no other release is tried. The package's SHA-256
# comes from --sha256, or else from the .sha256 file beside it. Needs tar, gzip and coreutils,
# and curl to download; the package brings its own Python.
#
# Program files only; ALPHAAVATAR_HOME, Avatar workspaces and model caches live elsewhere:
#   <prefix>/versions/<version>-<commit>/        each package unpacked and checked before use
#   <prefix>/envs/<plan>/                        what `alphaavatar setup` installs over one
#   <bin-dir>/alphaavatar -> <prefix>/current/bin/alphaavatar   created before the switch,
#                                                    never over anything already there
#   <prefix>/current -> versions/... or envs/... switched last
#   <prefix>/.install.lock                       the lock every run and setup take, kept
# For new terminals, the command's directory goes on PATH: a block marked as AlphaAvatar's in the
# login shell's startup file (~/.bashrc, ~/.zshrc or ~/.profile), added once and replaced whole,
# the rest of the file left as it is. In a terminal, a first installation then offers to run
# `alphaavatar setup` there, on the terminal's own input; --non-interactive never asks, and
# neither Doctor nor the Host is ever started.
# Installing the version current already runs keeps its setup environment. A failed or
# interrupted run removes only what it created, judged by where current points when it ends;
# the current version, the command and existing data stay as they were, and a path this script
# cannot tell it made is never removed. A signal acts between steps, never while one makes a
# directory or link and records it; what a stopped or failed removal leaves is a stage still
# marked, which the next run, setup or upgrade removes.

# Read whole before anything runs: piped to bash, a download cut short runs nothing.
{
set -euo pipefail

RELEASES="https://github.com/AlphaAvatar/AlphaAvatar/releases/download"
LATEST="https://github.com/AlphaAvatar/AlphaAvatar/releases/latest/download"
MANIFEST="alphaavatar-linux-x86_64.manifest.json"  # Beside a release's package (build.sh).
VERSION='^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$'

# Reported as the Python CLI reports (host/cli/render.py): a title, numbered steps, a status
# with the facts below it, then what to do next. Colors decorate a terminal only, as there:
# none with NO_COLOR set or TERM=dumb, and each stream decides for itself, so piped to bash,
# its input the download, the script still colors a terminal it writes to.
colored() { [[ -z "${NO_COLOR+set}" && "${TERM-}" != dumb && -t "$1" ]]; }
if colored 1; then
  BLUE=$'\e[38;2;96;165;250m' CYAN=$'\e[38;2;34;211;238m' GREEN=$'\e[32m' YELLOW=$'\e[33m'
  DIM=$'\e[90m' BOLD=$'\e[1m' RESET=$'\e[0m' live=1  # A step's line is updated in place.
else
  BLUE="" CYAN="" GREEN="" YELLOW="" DIM="" BOLD="" RESET="" live=""
fi
if colored 2; then
  RED=$'\e[31m' WARNED=$'\e[33m' ERESET=$'\e[0m'
else
  RED="" WARNED="" ERESET=""
fi

started=""  # The title is out: a result stands a blank line apart from what went before.
open=""  # The step under way: shown on a terminal at once, elsewhere once something goes below.
reported=""  # A failure die has said why: the end does not report it again.

title() { printf '\n%s%s%s\n\n' "$BLUE" "AlphaAvatar / $1" "$RESET"; }
settle() {
  # The step under way stays, its line ended, before what goes below it.
  if [[ -n "$open" ]]; then
    if [[ -n "$live" ]]; then printf '\n'; else printf '%s\n' "$open"; fi
    open=""
  fi
}
begin() {
  settle
  open="$(printf '%02d  %s' "$1" "$2")"
  [[ -z "$live" ]] || printf '%s%s%s' "$CYAN" "$open" "$RESET"
}
progress() { settle; printf '    %s\n' "$*"; }
step() {
  # Done, in its line's place: its summary, then each further line at the summary's column.
  if [[ -n "$open" ]]; then [[ -z "$live" ]] || printf '\r\e[K'; open=""; fi
  printf '%02d  %-15s%s\n' "$1" "$2" "$3"
  shift 3
  local more
  for more in "$@"; do printf '%19s%s\n' "" "$more"; done
}
status() {
  local color=""
  case "$1" in OK) color="$GREEN" ;; WARN) color="$YELLOW" ;; SKIP) color="$DIM" ;; esac
  settle
  printf '%s%s%s%*s%s\n' "$color" "$1" "$RESET" $((6 - ${#1})) "" "$2"
}
row() { printf '      %-13s%s\n' "$1" "$2"; }
commands() {
  # Commands to copy, each with why: the commands in signal cyan, their reasons dimmed, in
  # one column.
  local width=0 index command
  for ((index = 1; index <= $#; index += 2)); do
    command="${!index}"
    (( ${#command} <= width )) || width=${#command}
  done

  while [[ $# -ge 2 ]]; do
    printf '  %s%s%s%*s  %s# %s%s\n' "$CYAN" "$1" "$RESET" $((width - ${#1})) "" "$DIM" "$2" \
      "$RESET"
    shift 2
  done
}
# shellcheck disable=SC2088  # The ~ is shown, never expanded.
shown_path() {
  # A path for people to read: under the home directory, from ~.
  if [[ "$1" == "$HOME"/* ]]; then printf '~/%s' "${1#"$HOME"/}"; else printf '%s' "$1"; fi
}
# shellcheck disable=SC2088  # The ~ is for the shell the command is pasted into.
shell_path() {
  # The same for a shell to read: from ~, the rest quoted as it needs.
  if [[ "$1" == "$HOME"/* ]]; then printf '~/%q' "${1#"$HOME"/}"; else printf '%q' "$1"; fi
}
die() {
  # On stderr, apart from the steps: the status, then why, whole. The step's own line ends
  # where it is, on stdout.
  reported=1
  settle
  { [[ -z "$started" ]] || echo
    printf '%sFAIL%s  Not installed\n      %s\n' "$RED" "$ERESET" "$*"; } >&2
  exit 1
}

# A step that makes something holds signals until it is recorded, then they end the run as they
# would have: without a trap bash runs the cleanup at once, beside a command still under way.
held=""
hold() { trap 'held=130' INT; trap 'held=143' TERM; trap 'held=129' HUP; }
release() { trap - INT TERM HUP; [[ -z "$held" ]] || exit "$held"; }
calm() ( trap '' INT TERM HUP; exec "$@" )  # Its commands: Ctrl-C reaches them too.
mark=".alphaavatar-install"  # In each stage in versions/, install.sh's or upgrade's.
remove_stage() (
  # The mark last, once all else is gone: stopped or failing at any point, what is left is a
  # stage still marked. A removal that fails returns at once: where the cleanup calls this,
  # set -e does not act.
  shopt -s dotglob nullglob
  for item in "$1"/*; do
    [[ "$item" == "$1/$mark" ]] || rm -rf -- "$item" || return
  done
  rm -f -- "$1/$mark"
  rmdir -- "$1"
)

usage() {
  cat <<EOF
usage: install.sh [--version X.Y.Z | --file PACKAGE | --url URL] [--sha256 HEX]
                  [--prefix DIR] [--bin-dir DIR] [--non-interactive]
  none of --version, --file, --url: the latest release
  --non-interactive  install and put the command on PATH; never ask to run setup
  --prefix   program files (default: \$ALPHAAVATAR_INSTALL_DIR or ~/.local/lib/alphaavatar)
  --bin-dir  where the alphaavatar command goes (default: \$ALPHAAVATAR_BIN_DIR or ~/.local/bin)
EOF
}

version="" url="" file="" sha256="" non_interactive=""
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
    --non-interactive) non_interactive=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
(( (${#version} > 0) + (${#file} > 0) + (${#url} > 0) <= 1 )) || { usage >&2; exit 2; }
title Install
started=1
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in  # A terminal that shows UTF-8 gets its dot.
  *[Uu][Tt][Ff]-8* | *[Uu][Tt][Ff]8*) dot="·" ;;
  *) dot="-" ;;
esac
if [[ -n "$version" ]]; then
  [[ "$version" =~ $VERSION ]] || die "Invalid version"
  url="$RELEASES/v$version/alphaavatar-$version-linux-x86_64.tar.gz"
fi
[[ -z "$sha256" || "$sha256" =~ ^[0-9a-f]{64}$ ]] || die "--sha256 takes 64 hex digits"
for cmd in tar gzip sha256sum flock realpath mktemp getconf sort grep cut cmp \
    $([[ -n "$file" ]] || echo curl); do
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
# What this run makes, each recorded as it appears; the cleanup undoes it from here on.
made_versions="" stage="" fresh="" made_bin="" made_entry=""
cleanup() {
  trap '' INT TERM HUP  # Finish cleaning up whatever else arrives.
  # Removed unless current points to it: a signal may land just after the switch. Moved into
  # the stage whole, then removed with it: a stop leaves no half of it in place.
  if [[ -n "$fresh" && "$(readlink -f "$prefix/current" || true)" != "$(readlink -f "$fresh")" ]]
  then
    mv -T -- "$fresh" "$stage/fresh" || true
  fi
  [[ -z "$stage" ]] || remove_stage "$stage" || true
  # A first installation that ends without a current version leaves no command either: the
  # link it made, if it still points here, and the directories made for it, as far as empty.
  if [[ -n "$made_entry" && ! -e "$prefix/current" && "$(readlink "$entry")" == "$link" ]]; then
    rm -f -- "$entry"
    dir="$bin_dir"
    while [[ -n "$made_bin" && "$dir" != "$made_bin" ]] && rmdir -- "$dir" 2>/dev/null; do
      dir="$(dirname "$dir")"
    done
  fi
  # The prefix keeps the lock file, which another run may have opened already: removed, the
  # next would lock a new one beside it.
  [[ -z "$made_versions" ]] || rmdir -- "$prefix/versions" 2>/dev/null || true
}
ended() {
  # Ended early, by a signal or by a failure die did not report: cleaned up, then what stands
  # is said, on stderr. A terminal hung up takes no more: the run ends all the same.
  local code=$? label color stands now
  cleanup
  [[ "$code" -ne 0 && -z "$reported" ]] || return 0
  case "$code" in
    130) label=WARN color="$WARNED" stands="Interrupted" ;;
    129 | 143) label=WARN color="$WARNED" stands="Stopped" ;;
    *) label=FAIL color="$RED" stands="Not installed (exit $code)" ;;
  esac
  now="$(readlink "$prefix/current" || true)"
  if [[ -n "$now" && "$now" != "${previous-}" ]]; then
    stands+="; AlphaAvatar ${package_version-} is current, its PATH and setup not reached"
  elif [[ -n "$now" ]]; then
    stands+="; $now stays current"
  else
    stands+="; nothing is installed"
  fi
  # Said on stderr through its copy: errors writing to a terminal gone are not said at all.
  { settle; printf '\n%s%s%s%*s%s\n' "$color" "$label" "$ERESET" $((6 - ${#label})) "" \
    "$stands" >&3; } 3>&2 2>/dev/null || :
}
trap ended EXIT  # Also on SIGINT, SIGTERM and SIGHUP: bash exits through the EXIT trap.
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
hold
[[ -e "$prefix/versions" ]] || made_versions=1
calm mkdir -p -- "$prefix/versions"
release
for dir in "$prefix/versions"/.install-*; do
  # A stage whose run was stopped, marked as this script's or upgrade's: the lock is ours now.
  if [[ -d "$dir" && ! -L "$dir" && -f "$dir/$mark" ]]; then remove_stage "$dir"; fi
done
# This run's own directory, on the same file system as the versions it renames into.
hold
stage="$(calm mktemp -d "$prefix/versions/.install-XXXXXX")"
calm touch -- "$stage/$mark"
release

# No source given: the latest release, as its manifest names it, read once. Its package and
# SHA-256 are that release's, whatever is published meanwhile.
published=""
begin 1 Package
if [[ -z "$version$file$url" ]]; then
  published="$stage/$MANIFEST"
  curl -fsSL --retry 3 -o "$published" "$LATEST/$MANIFEST" \
    || die "Cannot download $LATEST/$MANIFEST:" \
      "the latest release publishes no Linux x86_64 package, or GitHub cannot be reached"
  text="$(< "$published")" tag=""
  pattern='"version": *"([^"]+)"'
  [[ "$text" =~ $pattern ]] && version="${BASH_REMATCH[1]}"
  pattern='"release": *"([^"]+)"'
  [[ "$text" =~ $pattern ]] && tag="${BASH_REMATCH[1]}"
  [[ "$version" =~ $VERSION && "$tag" == "v$version" ]] \
    || die "The latest release's manifest names no release of AlphaAvatar"
  progress "The latest release is $tag"
  url="$RELEASES/$tag/alphaavatar-$version-linux-x86_64.tar.gz"
fi

# The package is this run's own copy: what is checked is what unpacks and runs, whatever
# happens to the source meanwhile.
package="$stage/package.tar.gz"
if [[ -n "$url" ]]; then
  if [[ -z "$sha256" ]]; then
    sha256="$(curl -fsSL --retry 3 "$url.sha256" | cut -d' ' -f1)" || true
    [[ "$sha256" =~ ^[0-9a-f]{64}$ ]] || die "No SHA-256 at $url.sha256"
  fi
  progress "Downloading $url"
  curl -fL --retry 3 $([[ -t 2 ]] && echo --progress-bar || echo -sS) -o "$package" "$url" \
    || die "Cannot download $url"
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
[[ -z "$published" ]] || cmp -s "$published" "$manifest" \
  || die "The package of $tag holds another build than the manifest published beside it"
installed=""
for dir in "$prefix/versions"/*; do
  [[ -d "$dir" && ! -L "$dir" ]] || continue
  if cmp -s "$manifest" "$dir/share/alphaavatar/manifest.json"; then installed="$dir"; fi
done
[[ -n "$installed" ]] || tar -xzf "$package" -C "$stage/tree" --no-same-owner
fields="$("${installed:-$candidate}/python/bin/python3" -I -c 'import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
print(m["id"], m["version"], m["glibc"], *m["cpu"])
print(*m["imports"])
print(m.get("release") or "")' "$manifest")" || die "Not an AlphaAvatar package: no readable manifest"
# The release last: none, its empty line is gone with the output's trailing newlines.
{ read -r id package_version glibc cpu; read -r imports; read -r release || :; } <<< "$fields"
[[ "$id" =~ ^[0-9A-Za-z][0-9A-Za-z.+-]*$ ]] || die "Invalid package id"
[[ -z "$version" || "$package_version" == "$version" ]] || die "The package holds $package_version"
step 1 Package "AlphaAvatar $package_version $dot build $id $dot SHA-256 verified"
begin 2 Check

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
  check "$target" || die "$target does not run; remove it and install again"
  step 2 Check "AlphaAvatar $id is already installed $dot glibc $found $dot runs on this machine"
  begin 3 Install
elif [[ -e "$target" || -L "$target" ]]; then
  die "$target exists and holds something else; it is left as it is"
else
  check "$candidate" || die "The package does not run on this machine"
  step 2 Check "glibc $found $dot runs on this machine"
  begin 3 Install
  hold
  calm mv -T -- "$candidate" "$target"
  fresh="$target"  # This run's: removed at exit unless current points to it.
  release
  check "$target" || die "The package does not run from $target"
fi

if [[ "$(readlink "$entry" || true)" != "$link" ]]; then
  hold
  made_bin="$bin_dir"  # The deepest directory there already: those below it are this run's.
  while [[ ! -e "$made_bin" && ! -L "$made_bin" ]]; do made_bin="$(dirname "$made_bin")"; done
  calm mkdir -p -- "$bin_dir"
  # Created only if nothing is there: another installation may have made it meanwhile.
  calm ln -sT -- "$link" "$entry" 2>/dev/null && made_entry=1
  release
  [[ -n "$made_entry" ]] \
    || die "$entry appeared meanwhile and runs $(readlink "$entry" || echo something else); choose another --bin-dir"
fi
switch="versions/$id"
# A setup environment over this very version stays current: its capabilities remain.
if [[ "$previous" == envs/* ]] && "$target/python/bin/python3" -I -c 'import json, sys
sys.exit(json.load(open(sys.argv[1], encoding="utf-8"))["base"] != sys.argv[2])' \
    "$prefix/$previous/share/alphaavatar/plan.json" "$id" 2>/dev/null; then
  switch="$previous"
fi
hold  # The switch is whole before a signal acts: the cleanup tells by current what stays.
calm ln -s -- "$switch" "$stage/current"
calm mv -Tf -- "$stage/current" "$prefix/current"
release
if ! (cd / && [[ "$("$entry" --version)" == "AlphaAvatar $package_version" ]]); then
  hold
  if [[ -n "$previous" ]]; then
    calm ln -s -- "$previous" "$stage/previous" \
      && calm mv -Tf -- "$stage/previous" "$prefix/current"
  else
    calm rm -f -- "$prefix/current"
  fi
  release
  die "$entry does not run AlphaAvatar $package_version; the previous version stays current"
fi

if [[ "$switch" == "$previous" && "$switch" == envs/* ]]; then
  step 3 Install "$(shown_path "$target") $dot current: $switch, set up over this build"
else
  step 3 Install "$(shown_path "$target") $dot current"
fi

# The installation is whole: this run's stage goes, and the lock with its descriptor, before
# anything else runs, so setup takes the lock itself. Signals act as they would anywhere again.
cleanup
trap - EXIT INT TERM HUP
exec 9>&-

# The command's directory as the startup file of the login shell can hold it for new terminals:
# within double quotes, its \, ", $ and ` escaped.
quoted="${bin_dir//\\/\\\\}" quoted="${quoted//\"/\\\"}"
quoted="${quoted//\$/\\\$}" quoted="${quoted//\`/\\\`}"
begin="# >>> AlphaAvatar >>>" end="# <<< AlphaAvatar <<<"
block="$begin
# Where AlphaAvatar's command is, added by its install.sh; replaced whole when it runs again.
case \":\$PATH:\" in *\":$quoted:\"*) ;; *) export PATH=\"$quoted:\$PATH\" ;; esac
$end"
path_result=""
configure_file() {
  # Puts the block in one startup file and sets path_result; fails, having changed nothing,
  # where it cannot say the block is in place. Every marker is checked before anything is
  # written: begun and ended in turn, none inside another, the last one ended.
  local profile="$1" target text="" line bare number=0 inside="" found="" staged name
  target="$profile" name="$(shown_path "$1")"
  if [[ -e "$profile" || -L "$profile" ]]; then
    # A link is followed: the file it names is the one that changes.
    target="$(realpath -e -- "$profile" 2>/dev/null)" && [[ -f "$target" ]] \
      || { path_result="not configured: $name is not a file this installer edits"; return 1; }
    [[ -r "$target" ]] || { path_result="not configured: cannot read $name"; return 1; }
    # A marker line is one, spaces around it aside. The first block takes the place of every
    # one; every other line stays as it is.
    while IFS= read -r line || [[ -n "$line" ]]; do
      number=$((number + 1))
      bare="${line#"${line%%[![:space:]]*}"}" bare="${bare%"${bare##*[![:space:]]}"}"
      if [[ "$bare" == "$begin" ]]; then
        if [[ -n "$inside" ]]; then
          path_result="not configured: line $number of $name begins AlphaAvatar's block"
          path_result+=" inside another"; return 1
        fi
        inside=$number
        [[ -n "$found" ]] || text+="$block"$'\n' found=1
      elif [[ "$bare" == "$end" ]]; then
        if [[ -z "$inside" ]]; then
          path_result="not configured: line $number of $name ends AlphaAvatar's block,"
          path_result+=" never begun"; return 1
        fi
        inside=""
      elif [[ -z "$inside" ]]; then
        text+="$line"$'\n'
      fi
    done < "$target"
    if [[ -n "$inside" ]]; then
      path_result="not configured: AlphaAvatar's block begun on line $inside of $name"
      path_result+=" never ends"; return 1
    fi
  fi
  if [[ -n "$found" ]]; then
    [[ -w "$target" ]] || { path_result="not configured: cannot write $name"; return 1; }
    staged="$(mktemp "$(dirname -- "$target")/.alphaavatar-path-XXXXXX" 2>/dev/null)" \
      || { path_result="not configured: cannot write beside $name"; return 1; }
    if ! { printf '%s' "$text" > "$staged" && chmod --reference="$target" -- "$staged"; } \
        2>/dev/null; then
      rm -f -- "$staged"; path_result="not configured: cannot write beside $name"; return 1
    fi
    if cmp -s -- "$staged" "$target"; then
      rm -f -- "$staged"; path_result="$name already adds $shown_bin, for new terminals"
      return 0
    fi
    mv -f -- "$staged" "$target" 2>/dev/null \
      || { rm -f -- "$staged"; path_result="not configured: cannot write $name"; return 1; }
    path_result="updated $name with $shown_bin, for new terminals"
  else
    { printf '\n%s\n' "$block" >> "$target"; } 2>/dev/null \
      || { path_result="not configured: cannot write $name"; return 1; }
    path_result="added $shown_bin to $name, for new terminals"
  fi
}
# The startup files the login shell reads in a new terminal. Bash reads ~/.bashrc in an
# interactive shell and, logging in, the first of ~/.bash_profile, ~/.bash_login and
# ~/.profile there is; ~/.profile when there is none, never a file that would hide another.
path_files=() login=""
case "${SHELL##*/}" in
  bash)
    for login in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
      [[ -e "$login" || -L "$login" ]] && break
    done
    path_files=("$HOME/.bashrc" "$login") ;;
  zsh) path_files=("${ZDOTDIR:-$HOME}/.zshrc") ;;
  sh|dash) path_files=("$HOME/.profile") ;;
esac
on_path="" path_failed="" path_source="" shown_bin="$(shown_path "$bin_dir")" told=()
case ":$PATH:" in *":$bin_dir:"*) on_path=1 ;; esac
begin 4 PATH
if [[ -n "$on_path" ]]; then
  told=("$shown_bin is on PATH already")
elif [[ "$bin_dir" == *$'\n'* ]]; then
  told=("not configured: the directory's name holds a line break"); path_failed=1
elif [[ "${#path_files[@]}" -eq 0 ]]; then
  told=("not configured: the login shell (${SHELL:-none}) is not bash, zsh or sh"); path_failed=1
else
  for startup in "${path_files[@]}"; do
    if configure_file "$startup"; then
      [[ -n "$path_source" ]] || path_source="$startup"
    else
      path_failed=1
    fi
    told+=("$path_result")
  done
fi
step 4 PATH "${told[@]}"

echo
status OK "AlphaAvatar $package_version installed"
row Build "$id"
row Command "$(shown_path "$entry")"
row Current "$(shown_path "$prefix/current") -> $switch"
if [[ "$previous" == envs/* && "$switch" != "$previous" ]]; then
  status WARN "The capabilities \`alphaavatar setup\` installed belong to the previous version:"
  printf '      %s\n' "run \`alphaavatar setup <bundle>\` for the bundle you use."
fi
[[ -z "$path_failed" ]] || status WARN "PATH: a startup file is not configured; add it yourself"

# A first setup, offered in a terminal and run on that terminal, its input included: piped to
# bash, this script's own input is the download. Whatever setup does, the installation stays.
setup_next=1  # Whether setup is still to run.
# A build that is no release publishes its own wheels nowhere: setup takes them from beside
# the package given, where a build's files are kept together, and is told so.
setup=(setup)
if [[ -z "$release" && -n "$file" ]]; then
  beside="$(cd -- "$(dirname -- "$file")" && pwd -P)"
  if compgen -G "$beside/*.whl" > /dev/null; then setup+=(--artifacts "$beside"); fi
fi
if [[ "$switch" == envs/* || "$previous" == envs/* ]]; then
  setup_next=""  # Set up already: the bundles there stay as they are.
elif [[ -z "$non_interactive" ]] && { : < /dev/tty; } 2>/dev/null; then
  # Read in the background, by a reader that ignores Ctrl-C, whatever the bash version: this
  # script takes it, wherever it finds it, records the question cancelled, and its next look, a
  # tenth of a second on at most, ends the reader. Looking, not a wait: a Ctrl-C reaching a
  # shell as its read or a wait begins can be lost. However this script ends, by a signal too,
  # the reader ends with it, never left on the terminal to take a line meant for the shell:
  # killed, as a signal it could take might come before it has put down the traps it began
  # with, this script's, and be held there.
  answer="" reader="" cancelled="" held=""
  reply="$(mktemp "${TMPDIR:-/tmp}/alphaavatar-reply.XXXXXX" 2>/dev/null)" || reply=""
  if [[ -n "$reply" ]]; then
    trap 'kill -s KILL "$reader" 2>/dev/null || :; rm -f -- "$reply"' EXIT
    trap 'cancelled=1; echo > /dev/tty 2>/dev/null || :' INT
    # TERM and HUP wait while the reader starts, until its process is recorded: the end they
    # bring then finds the reader, and ends it with this script.
    trap 'held=TERM' TERM
    trap 'held=HUP' HUP
    { trap '' INT; IFS= read -r line < /dev/tty && printf 'answered:%s' "$line" > "$reply"; } &
    reader=$!
    trap - TERM HUP
    [[ -z "$held" ]] || kill -s "$held" "$$"
    echo
    # A Ctrl-C can cut the question's own writing short: that cancels, never fails the install.
    question='Run alphaavatar setup now, to choose what the Avatar runs with? [Y/n] '
    printf '%s%s%s' "$CYAN" "$question" "$RESET" > /dev/tty 2>/dev/null || :
    while [[ -z "$cancelled" ]] && kill -0 "$reader" 2>/dev/null; do sleep 0.1 || :; done
    trap - INT
    kill -s KILL "$reader" 2>/dev/null || :
    wait "$reader" 2>/dev/null || :
    reader=""  # Gone: its process ID may soon be another's.
    [[ -n "$cancelled" ]] || answer="$(< "$reply")"
    # The input ended at the question: what follows starts on a line of its own.
    [[ -n "$cancelled" || -n "$answer" ]] || echo > /dev/tty 2>/dev/null || :
    rm -f -- "$reply"
    trap - EXIT
  fi
  if [[ -n "$cancelled" ]]; then
    status WARN "Setup cancelled; not run"
  elif [[ "$answer" =~ ^answered:([Yy]([Ee][Ss])?)?$ ]]; then
    code=0
    trap ':' INT  # Ctrl-C ends setup, never this script: its report still follows.
    PATH="$bin_dir:$PATH" "$entry" "${setup[@]}" < /dev/tty > /dev/tty 2>&1 || code=$?
    trap - INT
    if [[ "$code" -eq 0 ]]; then
      status OK "Setup done"
      setup_next=""
    else
      status WARN "Setup did not finish (exit $code); AlphaAvatar stays installed"
    fi
  else
    status SKIP "Setup not run"
  fi
fi

# What is left to do: the command found in this terminal, then setup if it is still to run.
todo=()
if [[ -n "$path_failed" ]]; then
  todo+=("export PATH=\"$quoted:\$PATH\"")
  todo+=("this terminal; add it to the startup file above for new ones")
elif [[ -n "$path_source" ]]; then
  todo+=("source $(shell_path "$path_source")" "this terminal; new ones find alphaavatar")
fi
if [[ -n "$setup_next" && -z "$release" && "${#setup[@]}" -eq 1 ]]; then
  todo+=("alphaavatar setup --artifacts DIR" "DIR: this build's wheels; it is not a release")
elif [[ -n "$setup_next" ]]; then
  shown_setup="alphaavatar setup"
  [[ "${#setup[@]}" -eq 1 ]] || shown_setup+=" --artifacts $(shell_path "${setup[2]}")"
  todo+=("$shown_setup" "choose capabilities; it installs them")
fi
if [[ "${#todo[@]}" -gt 0 ]]; then
  printf '\n%sNext%s\n' "$BOLD" "$RESET"
  commands "${todo[@]}"
fi
echo
}
