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

die() { echo "Error: $*" >&2; exit 1; }

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
trap cleanup EXIT  # Also on SIGINT, SIGTERM and SIGHUP: bash exits through the EXIT trap.
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
if [[ -z "$version$file$url" ]]; then
  echo "Finding the latest release"
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
  echo "The latest release is $tag"
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
  echo "Downloading $url"
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

echo "Installed AlphaAvatar $package_version, build $id: $entry -> $prefix/current -> $switch"
if [[ "$previous" == envs/* && "$switch" != "$previous" ]]; then
  echo "The capabilities \`alphaavatar setup\` installed belong to the previous version:" \
    "run \`alphaavatar setup <bundle>\` for the bundle you use."
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
  local profile="$1" target text="" line bare number=0 inside="" found="" staged
  target="$profile"
  if [[ -e "$profile" || -L "$profile" ]]; then
    # A link is followed: the file it names is the one that changes.
    target="$(realpath -e -- "$profile" 2>/dev/null)" && [[ -f "$target" ]] \
      || { path_result="not configured: $profile is not a file this installer edits"; return 1; }
    [[ -r "$target" ]] || { path_result="not configured: cannot read $profile"; return 1; }
    # A marker line is one, spaces around it aside. The first block takes the place of every
    # one; every other line stays as it is.
    while IFS= read -r line || [[ -n "$line" ]]; do
      number=$((number + 1))
      bare="${line#"${line%%[![:space:]]*}"}" bare="${bare%"${bare##*[![:space:]]}"}"
      if [[ "$bare" == "$begin" ]]; then
        if [[ -n "$inside" ]]; then
          path_result="not configured: line $number of $profile begins AlphaAvatar's block"
          path_result+=" inside another"; return 1
        fi
        inside=$number
        [[ -n "$found" ]] || text+="$block"$'\n' found=1
      elif [[ "$bare" == "$end" ]]; then
        if [[ -z "$inside" ]]; then
          path_result="not configured: line $number of $profile ends AlphaAvatar's block,"
          path_result+=" never begun"; return 1
        fi
        inside=""
      elif [[ -z "$inside" ]]; then
        text+="$line"$'\n'
      fi
    done < "$target"
    if [[ -n "$inside" ]]; then
      path_result="not configured: AlphaAvatar's block begun on line $inside of $profile"
      path_result+=" never ends"; return 1
    fi
  fi
  if [[ -n "$found" ]]; then
    [[ -w "$target" ]] || { path_result="not configured: cannot write $profile"; return 1; }
    staged="$(mktemp "$(dirname -- "$target")/.alphaavatar-path-XXXXXX" 2>/dev/null)" \
      || { path_result="not configured: cannot write beside $profile"; return 1; }
    if ! { printf '%s' "$text" > "$staged" && chmod --reference="$target" -- "$staged"; } \
        2>/dev/null; then
      rm -f -- "$staged"; path_result="not configured: cannot write beside $profile"; return 1
    fi
    if cmp -s -- "$staged" "$target"; then
      rm -f -- "$staged"; path_result="$profile already adds $bin_dir, for new terminals"
      return 0
    fi
    mv -f -- "$staged" "$target" 2>/dev/null \
      || { rm -f -- "$staged"; path_result="not configured: cannot write $profile"; return 1; }
    path_result="updated $profile with $bin_dir, for new terminals"
  else
    { printf '\n%s\n' "$block" >> "$target"; } 2>/dev/null \
      || { path_result="not configured: cannot write $profile"; return 1; }
    path_result="added $bin_dir to $profile, for new terminals"
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
on_path="" path_failed="" path_source=""
case ":$PATH:" in *":$bin_dir:"*) on_path=1 ;; esac
if [[ -n "$on_path" ]]; then
  echo "PATH: $bin_dir is on PATH already"
elif [[ "$bin_dir" == *$'\n'* ]]; then
  echo "PATH: not configured: the directory's name holds a line break"; path_failed=1
elif [[ "${#path_files[@]}" -eq 0 ]]; then
  echo "PATH: not configured: the login shell (${SHELL:-none}) is not bash, zsh or sh"
  path_failed=1
else
  for file in "${path_files[@]}"; do
    if configure_file "$file"; then
      [[ -n "$path_source" ]] || path_source="$file"
    else
      path_failed=1
    fi
    echo "PATH: $path_result"
  done
fi
if [[ -n "$path_failed" ]]; then
  echo "PATH: to add it yourself:"
  echo "  export PATH=\"$quoted:\$PATH\""
fi

# A first setup, offered in a terminal and run on that terminal, its input included: piped to
# bash, this script's own input is the download. Whatever setup does, the installation stays.
next="alphaavatar setup    # choose capabilities; it installs them"
if [[ "$switch" == envs/* || "$previous" == envs/* ]]; then
  :  # Set up already: the bundles there stay as they are.
elif [[ -z "$non_interactive" ]] && { : < /dev/tty; } 2>/dev/null; then
  # Read in the background, where Ctrl-C is ignored: this script takes it while it waits, a
  # wait a trapped signal always ends, then ends the reading. A Ctrl-C reaching a shell as its
  # read begins can be lost, leaving the question unanswered. It answers no, as the end of
  # input does. However this script ends, by a signal too, the reader ends with it, never left
  # on the terminal to take a line meant for the shell.
  answer="" reader="" reply="$(mktemp "${TMPDIR:-/tmp}/alphaavatar-reply.XXXXXX" 2>/dev/null)" \
    || reply=""
  if [[ -n "$reply" ]]; then
    trap '[[ -z "$reader" ]] || kill "$reader" 2>/dev/null; rm -f -- "$reply"' EXIT
    trap 'printf "\n" > /dev/tty' INT
    { IFS= read -r line < /dev/tty && printf 'answered:%s' "$line" > "$reply"; } &
    reader=$!
    printf 'Run alphaavatar setup now, to choose what the Avatar runs with? [Y/n] ' > /dev/tty
    wait "$reader" || :
    trap - INT
    kill "$reader" 2>/dev/null || :
    wait "$reader" 2>/dev/null || :
    answer="$(< "$reply")"
    rm -f -- "$reply"
    trap - EXIT
  fi
  if [[ "$answer" =~ ^answered:([Yy]([Ee][Ss])?)?$ ]]; then
    status=0
    trap ':' INT  # Ctrl-C ends setup, never this script: its report still follows.
    PATH="$bin_dir:$PATH" "$entry" setup < /dev/tty > /dev/tty 2>&1 || status=$?
    trap - INT
    if [[ "$status" -eq 0 ]]; then
      echo "Setup: done"
    else
      echo "Setup: did not finish (exit $status); AlphaAvatar stays installed. Next: $next"
    fi
  else
    echo "Setup: not run. Next: $next"
  fi
else
  echo "Next: $next"
fi
if [[ -n "$path_source" && -z "$path_failed" ]]; then
  printf 'This terminal finds alphaavatar in a new terminal, or after: source %q\n' "$path_source"
elif [[ -n "$path_source" ]]; then
  printf 'This terminal finds alphaavatar after: source %q\n' "$path_source"
elif [[ -z "$on_path" ]]; then
  echo "This terminal finds alphaavatar once $bin_dir is on PATH."
fi
}
