#!/usr/bin/env bash
# Build AlphaAvatar for Linux x86_64: the base package install.sh installs, and the wheels
# `alphaavatar setup` installs beside it when a person chooses capabilities.
#
#   packaging/linux/build.sh [--release vX.Y.Z] [--out DIR] [--max-glibc 2.28] [--allow-dirty]
#
# Into DIR, one flat set (a release attaches these files as they are):
#   alphaavatar-<id>-linux-x86_64.tar.gz(.sha256)  the base: a Python, the Host, Agents and
#       Core, and base.txt's packages, which run the CLI, `config init|check` and setup; its
#       share/alphaavatar holds the manifest and catalog.json, every requirement setup can
#       install, each distribution's artifact with its SHA-256
#   *.whl  the artifacts this build makes: AlphaAvatar's packages, and the locked sources with
#       no wheel for the platform (llama-cpp-python, compiled for x86-64-v3)
#   install.sh  the installer, as packaging/linux holds it
#   SHA256SUMS  every file above
# Other artifacts are uv.lock's wheels (torch and torchaudio: torch-cpu.txt's CPU builds), which
# setup downloads from where the lock records them.
#
# CI runs it in manylinux_2_28 (.github/workflows/linux-package.yml). It needs uv 0.10.0, git,
# curl, unzip, a C/C++ compiler and binutils. Every input is pinned: uv.lock, torch-cpu.txt,
# and a CPython build uv verifies. A wheel built here needs glibc as new as the newest symbol
# version its native code references, at most --max-glibc; llama-cpp-python also needs x86-64-v3.
set -euo pipefail

PYTHON_VERSION="3.13.12"
UV_VERSION="0.10.0"
# llama-cpp-python, for semantic addressing on the CPU: portable x86-64-v3 code, ggml's own
# threads rather than the system's libgomp, and no multimodal library the router never loads.
LLAMA_CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_SSE42=ON -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON \
-DGGML_F16C=ON -DGGML_BMI2=ON -DGGML_OPENMP=OFF -DLLAVA_BUILD=OFF"
LLAMA_CPU="avx2,bmi2,f16c,fma"
# The base's native modules, which install.sh loads before switching to a new version.
IMPORTS="numpy pydantic_core yaml"

die() { echo "Error: $*" >&2; exit 1; }

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/packaging/linux"
release="" out="$root/dist/linux" max_glibc="2.28" allow_dirty=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release|--out|--max-glibc)
      [[ $# -ge 2 ]] || die "$1 needs a value"
      case "$1" in
        --release) release="$2" ;;
        --out) out="$2" ;;
        --max-glibc) max_glibc="$2" ;;
      esac
      shift 2 ;;
    --allow-dirty) allow_dirty=1; shift ;;
    *) die "Unknown option: $1" ;;
  esac
done
for cmd in git curl tar gzip sha256sum objdump unzip uv; do
  command -v "$cmd" >/dev/null 2>&1 || die "Missing command: $cmd"
done
[[ "$(uv --version)" == "uv $UV_VERSION"* ]] || die "Use uv $UV_VERSION, as CI does"
[[ "$(uname -s)/$(uname -m)" == "Linux/x86_64" ]] || die "Build on Linux x86_64"

cd "$root"
commit="$(git rev-parse HEAD)"
version="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' avatar-host/alphaavatar/host/version.py)"
[[ -n "$version" ]] || die "Cannot read the Host version"
id="$version-${commit:0:12}"
if [[ -n "$(git status --porcelain)" ]]; then
  # Untracked files count: wheels include whatever their package directories hold.
  [[ -n "$allow_dirty" && -z "$release" ]] || die "The checkout has changes; build a commit"
  id+="-dirty.$(date -u +%Y%m%d%H%M%S)"
fi
name="alphaavatar-$id-linux-x86_64"
if [[ -n "$release" ]]; then
  [[ "$release" == "v$version" ]] || die "Tag $release does not match the Host version $version"
  [[ "$(git rev-parse "$release^{commit}")" == "$commit" ]] || die "$release is not HEAD"
  name="alphaavatar-$version-linux-x86_64"
fi
# Archive entries take the commit's time: the same build inputs archive the same way.
export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)"

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
tree="$work/$name" wheels="$work/wheels"
mkdir -p "$tree/bin" "$tree/share/alphaavatar" "$wheels" "$out"
[[ -z "$(ls -A "$out")" ]] || die "$out is not empty; a build's files belong together"

echo "==> Python $PYTHON_VERSION"
UV_PYTHON_INSTALL_DIR="$work/pythons" uv python install --no-bin "$PYTHON_VERSION"
cp -a "$work/pythons/cpython-$PYTHON_VERSION-linux-x86_64-gnu" "$tree/python"
py="$tree/python/bin/python3"
uv export --locked --only-group build --no-emit-workspace --no-hashes \
  --output-file "$work/build-constraints.txt" > /dev/null

echo "==> AlphaAvatar wheels"
mapfile -t members < <(uv export --locked --all-packages --no-default-groups --no-hashes \
  --no-editable | grep '^\./')
for member in "${members[@]}"; do
  uv build --quiet --wheel --no-sources --python "$py" --build-constraints \
    "$work/build-constraints.txt" --out-dir "$wheels" "$member"
done

echo "==> The base"
# base.txt's packages from the lock, with the hashes it records; then the three base wheels.
"$py" -I "$here/catalog.py" base "$root" > "$work/base-requirements.txt"
install=(uv pip install --quiet --python "$py" --break-system-packages --no-deps)
"${install[@]}" --compile-bytecode --require-hashes -r "$work/base-requirements.txt"
"${install[@]}" --compile-bytecode "$wheels"/alpha_avatar_{host,agents,core}-*.whl

echo "==> Wheels from locked sources"
# Those setup may install without a wheel for the platform; llama-cpp-python for x86-64-v3.
"$py" -I "$here/catalog.py" sdists "$root" > "$work/sdists.txt"
while read -r sdist url sha; do
  curl -fsSL --retry 3 -o "$work/${url##*/}" "$url"
  echo "$sha  $work/${url##*/}" | sha256sum -c --quiet
  flags=""
  [[ "$sdist" == "llama-cpp-python" ]] && flags="$LLAMA_CMAKE_ARGS"
  CMAKE_ARGS="$flags" CMAKE_BUILD_PARALLEL_LEVEL="$(nproc)" \
    uv build --wheel --python "$py" --build-constraints "$work/build-constraints.txt" \
    --out-dir "$wheels" "$work/${url##*/}" > "$work/$sdist-build.log" 2>&1 \
    || { tail -n 40 "$work/$sdist-build.log" >&2; die "$sdist did not build"; }
done < "$work/sdists.txt"

# Console scripts name the Python they were installed with; let each run the one beside it.
cat > "$work/shebang" <<'SH'
#!/bin/sh
'''exec' "$(dirname -- "$(realpath -- "$0")")"/'python3' "$0" "$@"
' '''
SH
for script in "$tree/python/bin/"*; do
  [[ -f "$script" && ! -L "$script" && "$(head -c 2 "$script")" == "#!" ]] || continue
  if [[ "$(head -n 1 "$script")" =~ ^\#!/.*/bin/python[0-9.]*$ ]]; then
    sed -i -e "1r $work/shebang" -e 1d "$script"
  fi
done
cat > "$tree/bin/alphaavatar" <<'SH'
#!/bin/sh
# AlphaAvatar's command: the package's own Python, isolated from the caller's Python settings.
exec "$(dirname -- "$(realpath -- "$0")")/../python/bin/python3" -I -c \
  'import sys; from alphaavatar.host.main import main; sys.exit(main())' "$@"
SH
chmod 755 "$tree/bin/alphaavatar"

echo "==> Platform floor"
# The newest glibc symbol version a native file references is the oldest glibc it runs on.
floor() { "$root/packaging/linux/glibc-floor.sh" "$@"; }
base_floor="$(floor "$tree")"
mkdir "$work/unpacked"
for wheel in "$wheels"/*.whl; do
  unzip -q -o "$wheel" -d "$work/unpacked/${wheel##*/}"
done
built_floor="$(floor "$work/unpacked")"
rm -rf "$work/unpacked"
[[ -n "$base_floor" ]] || die "No native file references glibc"
for found in "$base_floor" "${built_floor:-0}"; do
  [[ "$(printf '%s\n' "$found" "$max_glibc" | sort -V | tail -n 1)" == "$max_glibc" ]] \
    || die "A native file needs glibc $found, newer than $max_glibc"
done

echo "==> Catalog and manifest"
"$py" -I "$here/catalog.py" write "$root" "$wheels" "$tree/share/alphaavatar/catalog.json" \
  --version "$version" --glibc "${built_floor:-$base_floor}" --cpu "llama-cpp-python=$LLAMA_CPU"
"$py" -I - "$tree" "$id" "$version" "$commit" "$release" "$base_floor" "$IMPORTS" \
  "$PYTHON_VERSION" "$UV_VERSION" "$(sha256sum < uv.lock | cut -d' ' -f1)" <<'PY'
import json, sys
from importlib import metadata
from pathlib import Path
tree, id, version, commit, release, glibc, imports, python, uv, lock = sys.argv[1:]
site = sorted((Path(tree) / "python" / "lib").glob("python3.*/site-packages"))
packages = {d.metadata["Name"]: d.version for d in metadata.distributions(path=[str(site[0])])}
manifest = {
    "id": id, "version": version, "commit": commit, "release": release or None,
    "platform": "linux-x86_64", "glibc": glibc, "cpu": [], "imports": imports.split(),
    "python": python, "uv": uv, "uv_lock_sha256": lock,
    "packages": dict(sorted(packages.items(), key=lambda item: item[0].lower())),
}
path = Path(tree) / "share" / "alphaavatar" / "manifest.json"
path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY

echo "==> Check the base from outside the checkout"
smoke="$work/smoke"
mkdir -p "$smoke"
run() { (cd / && env ALPHAAVATAR_HOME="$smoke/home" ENV_FILE="$smoke/absent.env" "$@"); }
# Chained: errexit does not apply where a caller tests the status.
# shellcheck disable=SC2086
{
  [[ "$(run "$tree/bin/alphaavatar" --version)" == "AlphaAvatar $version" ]] \
    && run "$tree/bin/alphaavatar" --help > /dev/null \
    && run "$py" -I -c 'import importlib, sys; [importlib.import_module(m) for m in sys.argv[1:]]' \
      $IMPORTS \
    && run "$tree/bin/alphaavatar" config init reference --avatar-id reference > /dev/null \
    && run "$tree/bin/alphaavatar" doctor --list > /dev/null
} || die "The base does not run"
# Without capabilities, config check names each implementation the bundle selects, where; the
# tree is not installed into a prefix, so nothing here is said to come from setup.
report="$(run "$tree/bin/alphaavatar" config check 2>&1)" && die "config check passed bare"
grep -q "voice.vad.plugin: no installed package provides voice.vad 'silero'" <<< "$report" \
  || { echo "$report" >&2; die "config check does not name what is missing"; }
# The catalog plans offline (the base is not installed into a prefix here) what setup installs:
# the reference bundle config init wrote above, from its settings in this bare base as
# `alphaavatar setup <bundle>` plans it, and the same with no model on this machine.
run "$py" -I - "$tree" <<'PY' || die "The catalog cannot plan the reference bundle"
import json, sys
from pathlib import Path
from alphaavatar.host.configs import load_selections, select_configuration
from alphaavatar.host.setup.choices import Selection, bundle_requirements, requirements
from alphaavatar.host.setup.plan import plan_install
catalog = json.loads((Path(sys.argv[1]) / "share/alphaavatar/catalog.json").read_text())
host, avatar = load_selections(select_configuration("reference"))
needs, unserved = bundle_requirements(host, avatar, catalog["plugins"])
assert not unserved and sorted(needs) == list(requirements(Selection())), (sorted(needs), unserved)
for label, needed in (
    ("reference bundle", sorted(needs)),
    ("no model on this machine", requirements(Selection(local_models=False))),
):
    plan = plan_install(catalog, needed, base="build")
    print(f"    {label}: {len(plan.artifacts)} packages, {plan.download_bytes / 1e6:,.0f} MB")
# With no model on this machine, no local model library nor its accelerators is planned.
local = {"torch", "torchaudio", "llama-cpp-python", "insightface", "transformers", "onnx", "scipy"}
assert not local & {artifact.name for artifact in plan.artifacts}, sorted(local & {a.name for a in plan.artifacts})
# What config check says setup installs: the implementations this build's wheels declare.
assert catalog["plugins"]["voice.vad"]["silero"] == "alpha-avatar-plugins-voice[silero]"
PY

echo "==> Archive"
tar -C "$work" --sort=name --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 --numeric-owner \
  -cf - "$name" | gzip -n > "$out/$name.tar.gz"
# The wheels the catalog references beside the package; other members' stay out.
"$py" -I -c 'import json, sys
catalog = json.load(open(sys.argv[1], encoding="utf-8"))
print("\n".join(d["file"] for d in catalog["distributions"].values() if d.get("sha256") and not d["url"]))' \
  "$tree/share/alphaavatar/catalog.json" | while read -r file; do cp "$wheels/$file" "$out/"; done
cp "$here/install.sh" "$out/"
(cd "$out" && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256" && sha256sum -- *.whl \
  install.sh "$name.tar.gz" > SHA256SUMS)
echo "Built $out/$name.tar.gz ($(du -h "$out/$name.tar.gz" | cut -f1)), glibc >= $base_floor;" \
  "$(ls "$out"/*.whl | wc -l) wheels, glibc >= ${built_floor:-none}"
