#!/usr/bin/env bash
# Build the Linux x86_64 package: a Python, the Host and the plugins `config init`'s reference
# bundle selects, in one relocatable directory archived for install.sh.
#
#   packaging/linux/build.sh [--release vX.Y.Z] [--out DIR] [--max-glibc 2.28] [--allow-dirty]
#
# CI runs it in manylinux_2_28 (.github/workflows/linux-package.yml). It needs uv 0.10.0, git,
# curl, a C/C++ compiler and binutils. Every input is pinned: uv.lock for the packages and the
# llama-cpp-python source, the AlphaAvatar wheels built from this checkout as Quality CI builds
# them, torch-cpu.txt, and a CPython build that uv verifies. Three locked packages are replaced
# for a server: torch and torchaudio by their CPU builds, llama-cpp-python by a wheel built here,
# and opencv-python, the GUI OpenCV insightface names (it needs X11 and OpenGL), by the headless
# build persona pins, which provides the same cv2. The package needs glibc as new as the newest
# symbol version its native code references, and an x86-64-v3 CPU.
set -euo pipefail

PYTHON_VERSION="3.13.12"
UV_VERSION="0.10.0"
GROUP="reference-bundle"
CPU_FLAGS="avx2 fma f16c bmi2"
# llama-cpp-python, for semantic addressing on the CPU: portable x86-64-v3 code, ggml's own
# threads rather than the system's libgomp, and no multimodal library the router never loads.
LLAMA_CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_SSE42=ON -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON \
-DGGML_F16C=ON -DGGML_BMI2=ON -DGGML_OPENMP=OFF -DLLAVA_BUILD=OFF"
# Modules whose native code the installer loads before switching to a new version.
IMPORTS="llama_cpp onnxruntime torch torchaudio cv2 insightface lancedb livekit.rtc"

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
for cmd in git curl tar gzip sha256sum objdump uv; do
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

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
tree="$work/$name"
mkdir -p "$tree/bin" "$tree/share/alphaavatar" "$out"

echo "==> Python $PYTHON_VERSION"
UV_PYTHON_INSTALL_DIR="$work/pythons" uv python install --no-bin "$PYTHON_VERSION"
cp -a "$work/pythons/cpython-$PYTHON_VERSION-linux-x86_64-gnu" "$tree/python"
py="$tree/python/bin/python3"

echo "==> Locked inputs"
uv export --locked --only-group build --no-emit-workspace --no-hashes \
  --output-file "$work/build-constraints.txt" > /dev/null
# Third-party packages of the bundle, except the replaced ones: torch from torch-cpu.txt,
# without PyPI's CUDA libraries, llama-cpp-python compiled here, and no GUI OpenCV.
"$py" -I - "$root/uv.lock" "$here/torch-cpu.txt" > "$work/replaced.txt" <<'PY'
import re, sys, tomllib
lock = {p["name"]: p for p in tomllib.load(open(sys.argv[1], "rb"))["package"]}
pins = re.findall(r"^(torch\w*) @ \S+/\1-([\d.]+)%2Bcpu-", open(sys.argv[2]).read(), re.M)
if sorted(name for name, _ in pins) != ["torch", "torchaudio"]:
    sys.exit("torch-cpu.txt must pin torch and torchaudio")
for name, version in pins:
    if lock[name]["version"] != version:
        sys.exit(f"torch-cpu.txt has {name} {version}; uv.lock has {lock[name]['version']}")
llama = lock["llama-cpp-python"]["sdist"]
print(llama["url"], llama["hash"].removeprefix("sha256:"))
print(" ".join(["torch", "torchaudio", "llama-cpp-python", "opencv-python", "triton"]
               + [name for name in lock if name.startswith("nvidia-")]))
PY
{ read -r llama_url llama_sha; read -r -a replaced; } < "$work/replaced.txt"
uv export --locked --no-default-groups --only-group "$GROUP" --no-emit-workspace \
  "${replaced[@]/#/--no-emit-package=}" --output-file "$work/requirements.txt" > /dev/null
mapfile -t members < <(uv export --locked --no-default-groups --only-group "$GROUP" \
  --no-hashes --no-editable | grep '^\./')

echo "==> AlphaAvatar wheels"
for member in "${members[@]}"; do
  uv build --quiet --wheel --no-sources --python "$py" --build-constraints \
    "$work/build-constraints.txt" --out-dir "$work/wheels" "$member"
done

echo "==> llama-cpp-python from its locked source"
curl -fsSL --retry 3 -o "$work/${llama_url##*/}" "$llama_url"
echo "$llama_sha  $work/${llama_url##*/}" | sha256sum -c --quiet
CMAKE_ARGS="$LLAMA_CMAKE_ARGS" CMAKE_BUILD_PARALLEL_LEVEL="$(nproc)" \
  uv build --wheel --python "$py" --build-constraints "$work/build-constraints.txt" \
  --out-dir "$work/native" "$work/${llama_url##*/}" > "$work/llama-build.log" 2>&1 \
  || { tail -n 40 "$work/llama-build.log" >&2; die "llama-cpp-python did not build"; }

echo "==> Install into the package's Python"
install=(uv pip install --quiet --python "$py" --break-system-packages --no-deps)
install+=(--compile-bytecode)
"${install[@]}" --require-hashes -r "$work/requirements.txt" -r "$here/torch-cpu.txt"
"${install[@]}" "$work"/wheels/*.whl "$work"/native/*.whl
# Every requirement holds, except that insightface names the GUI OpenCV, replaced above.
report="$(uv pip check --python "$py" 2>&1)" || true
expected='^(Using Python .*|Checked [0-9]+ packages? in .*|All installed packages are compatible'
expected+='|Found [0-9]+ incompatibilit(y|ies)'
expected+='|The package `insightface` requires `opencv-python`, but it.s not installed)$'
if grep -Evq "$expected" <<< "$report"; then
  echo "$report" >&2
  die "The installed packages do not satisfy each other"
fi
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
# The newest glibc symbol version any native file references is the oldest glibc it runs on.
floor="$(find "$tree" -type f \( -name '*.so' -o -name '*.so.*' -o -perm -u+x \) -print0 \
  | { xargs -0 objdump -p 2>/dev/null || true; } | { grep -o 'GLIBC_[0-9][0-9.]*' || true; } \
  | cut -d_ -f2 | sort -uV | tail -n 1)"
[[ -n "$floor" ]] || die "No native file references glibc"
[[ "$(printf '%s\n' "$floor" "$max_glibc" | sort -V | tail -n 1)" == "$max_glibc" ]] \
  || die "The package needs glibc $floor, newer than $max_glibc"

echo "==> Manifest"
"$py" -I - "$tree" "$id" "$version" "$commit" "$release" "$floor" "$CPU_FLAGS" "$IMPORTS" \
  "$PYTHON_VERSION" "$UV_VERSION" "$GROUP" "$(sha256sum < uv.lock | cut -d' ' -f1)" <<'PY'
import json, sys
from importlib import metadata
from pathlib import Path
tree, id, version, commit, release, glibc, cpu, imports, python, uv, group, lock = sys.argv[1:]
site = sorted((Path(tree) / "python" / "lib").glob("python3.*/site-packages"))
packages = {d.metadata["Name"]: d.version for d in metadata.distributions(path=[str(site[0])])}
manifest = {
    "id": id, "version": version, "commit": commit, "release": release or None,
    "platform": "linux-x86_64", "glibc": glibc, "cpu": cpu.split(), "imports": imports.split(),
    "python": python, "uv": uv, "bundle": group, "uv_lock_sha256": lock,
    "replaced": {
        "torch": "CPU build, torch-cpu.txt",
        "torchaudio": "CPU build, torch-cpu.txt",
        "llama-cpp-python": "wheel built from the locked source for x86-64-v3",
        "opencv-python": "not installed; opencv-python-headless provides cv2",
    },
    "packages": dict(sorted(packages.items(), key=lambda item: item[0].lower())),
}
path = Path(tree) / "share" / "alphaavatar" / "manifest.json"
path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY
cp "$work/requirements.txt" "$tree/share/alphaavatar/requirements.txt"
cat "$here/torch-cpu.txt" >> "$tree/share/alphaavatar/requirements.txt"
(cd "$work" && sha256sum wheels/*.whl native/*.whl) \
  > "$tree/share/alphaavatar/built-wheels.sha256"

echo "==> Check the package from outside the checkout"
smoke="$work/smoke"
mkdir -p "$smoke"
# Chained: errexit does not apply inside a tested subshell.
# shellcheck disable=SC2086
(
  cd / \
    && [[ "$("$tree/bin/alphaavatar" --version)" == "AlphaAvatar $version" ]] \
    && "$tree/bin/alphaavatar" --help > /dev/null \
    && "$py" -I -c 'import importlib, sys; [importlib.import_module(m) for m in sys.argv[1:]]' \
      $IMPORTS \
    && env ALPHAAVATAR_HOME="$smoke/home" ENV_FILE="$smoke/absent.env" \
      "$tree/bin/alphaavatar" config init reference --avatar-id reference > /dev/null \
    && env ALPHAAVATAR_HOME="$smoke/home" ENV_FILE="$smoke/absent.env" \
      "$tree/bin/alphaavatar" config check > /dev/null
) || die "The built package does not run"

echo "==> Archive"
tar -C "$work" -czf "$out/$name.tar.gz" "$name"
(cd "$out" && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256")
echo "Built $out/$name.tar.gz ($(du -h "$out/$name.tar.gz" | cut -f1)), glibc >= $floor"
