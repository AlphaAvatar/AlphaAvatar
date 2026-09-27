# Copyright 2026 AlphaAvatar project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Synchronous model-file resolution for inference initialization, never turn processing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from filelock import FileLock

from .model_cache import build_model_cache_dir

_TRUE_VALUES = {"1", "true", "yes", "on"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def models_offline() -> bool:
    return any(
        os.getenv(name, "").strip().lower() in _TRUE_VALUES
        for name in ("ALPHAAVATAR_MODEL_OFFLINE", "HF_HUB_OFFLINE")
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _filename(value: str) -> str:
    if not value or value in {".", ".."} or any(char in value for char in ("/", "\\", ":")):
        raise ValueError(f"Invalid model filename: {value!r}")
    return value


def _digest(value: str | None) -> str | None:
    if value is not None and not _SHA256.fullmatch(value):
        raise ValueError("Expected a lowercase SHA256 digest")
    return value


def _valid(path: Path, digest: str | None, size: int | None = None) -> bool:
    return (
        path.is_file()
        and path.stat().st_size > 0
        and (size is None or path.stat().st_size == size)
        and (digest is None or sha256_file(path) == digest)
    )


def _atomic_json(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def resolve_hf_file(
    *,
    namespace: tuple[str, ...],
    repo_id: str,
    revision: str,
    filename: str,
    sha256: str | None = None,
) -> str:
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    if not repo_id or not revision:
        raise ValueError("Model repository and revision are required")
    _filename(filename)
    _digest(sha256)
    root = build_model_cache_dir(*namespace, create=True)
    identity = {"repo_id": repo_id, "revision": revision, "filename": filename}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    marker = root / f".{key}.json"
    kwargs = {
        "repo_id": repo_id,
        "revision": revision,
        "filename": filename,
        "cache_dir": root / "hub",
    }

    with FileLock(str(root / f".{key}.lock"), timeout=300):
        metadata = _read_json(marker)
        expected = sha256 or (
            metadata.get("sha256") if metadata.get("source") == identity else None
        )
        expected = expected if isinstance(expected, str) and _SHA256.fullmatch(expected) else None
        path = None
        try:
            path = Path(hf_hub_download(**kwargs, local_files_only=True))
        except LocalEntryNotFoundError:
            pass

        if path is not None and expected is None and _SHA256.fullmatch(path.resolve().name):
            expected = path.resolve().name
        if path is not None and _valid(path, expected):
            _atomic_json(marker, {"source": identity, "sha256": expected or sha256_file(path)})
            return str(path)
        if models_offline():
            raise FileNotFoundError(
                f"Offline model is missing or invalid: {repo_id}@{revision}/{filename}"
            )

        attempts = (True,) if path is not None else (False, True)
        for force_download in attempts:
            path = Path(hf_hub_download(**kwargs, force_download=force_download))
            if expected is None and _SHA256.fullmatch(path.resolve().name):
                expected = path.resolve().name
            if _valid(path, expected):
                _atomic_json(marker, {"source": identity, "sha256": expected or sha256_file(path)})
                return str(path)
        raise RuntimeError(
            f"Model checksum/size validation failed: {repo_id}@{revision}/{filename}"
        )


def resolve_url_file(
    *,
    namespace: tuple[str, ...],
    filename: str,
    url: str,
    sha256: str | None = None,
    size: int | None = None,
) -> Path:
    _filename(filename)
    _digest(sha256)
    if not url.startswith("https://") or (size is not None and size <= 0):
        raise ValueError("Model downloads require HTTPS and a positive declared size")
    root = build_model_cache_dir(*namespace, create=True)
    target = root / filename
    marker = root / f".{filename}.json"
    source = {"url": url, "sha256": sha256, "size": size}

    with FileLock(str(root / f".{filename}.lock"), timeout=300):
        metadata = _read_json(marker)
        expected = sha256 or (metadata.get("sha256") if metadata.get("source") == source else None)
        expected = expected if isinstance(expected, str) and _SHA256.fullmatch(expected) else None
        if expected is not None and _valid(target, expected, size):
            return target
        if models_offline():
            raise FileNotFoundError(f"Offline model is missing or invalid: {target}")

        fd, name = tempfile.mkstemp(prefix=f".{filename}.", suffix=".part", dir=root)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as output:
                with urllib.request.urlopen(url, timeout=60) as response:
                    if not response.geturl().startswith("https://"):
                        raise RuntimeError("Model download redirected to an insecure URL")
                    shutil.copyfileobj(response, output)
                output.flush()
                os.fsync(output.fileno())
            if not _valid(temporary, expected, size):
                raise RuntimeError(f"Model checksum/size validation failed: {url}")
            actual = sha256_file(temporary)
            os.replace(temporary, target)
            _atomic_json(marker, {"source": source, "sha256": actual})
            return target
        finally:
            temporary.unlink(missing_ok=True)


def resolve_zip_directory(
    *,
    namespace: tuple[str, ...],
    name: str,
    url: str,
    files: tuple[str, ...],
    sha256: str | None = None,
    size: int | None = None,
) -> Path:
    """Install only declared model files; without an upstream digest, hashes are TOFU."""
    _filename(name)
    _digest(sha256)
    if not url.startswith("https://") or (size is not None and size <= 0):
        raise ValueError("Model downloads require HTTPS and a positive declared size")
    if not files or len(files) != len(set(files)):
        raise ValueError("Archive model files must be nonempty and unique")
    for filename in files:
        _filename(filename)
    root = build_model_cache_dir(*namespace, create=True)
    target = root / "models" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    identity = {"url": url, "sha256": sha256, "size": size, "files": list(files)}
    manifest_name = ".alphaavatar-model.json"

    with FileLock(str(root / f".{name}.lock"), timeout=300):
        manifest = _read_json(target / manifest_name)
        checksums = manifest.get("checksums", {})
        if manifest.get("source") == identity and isinstance(checksums, dict):
            if all(
                isinstance(checksums.get(file), str)
                and _SHA256.fullmatch(checksums[file])
                and _valid(target / file, checksums[file])
                for file in files
            ):
                return target

        archive = resolve_url_file(
            namespace=(*namespace, "archives"),
            filename=f"{name}.zip",
            url=url,
            sha256=sha256,
            size=size,
        )
        staging = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=target.parent))
        try:
            with ZipFile(archive) as bundle:
                names = bundle.namelist()
                if len(names) != len(set(names)):
                    raise ValueError("Duplicate archive entries are not allowed")
                for member in bundle.infolist():
                    path = PurePosixPath(member.filename)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or "\\" in member.filename
                        or ":" in member.filename
                    ):
                        raise ValueError("Unsafe model archive entry")
                    if stat.S_ISLNK(member.external_attr >> 16):
                        raise ValueError("Model archive symlinks are not allowed")
                if sum(bundle.getinfo(file).file_size for file in files) > 1024**3:
                    raise ValueError("Model archive exceeds the extraction limit")
                for file in files:
                    member = bundle.getinfo(file)
                    if member.is_dir() or member.file_size <= 0:
                        raise ValueError(f"Invalid model archive entry: {file}")
                    with bundle.open(member) as source, (staging / file).open("wb") as output:
                        shutil.copyfileobj(source, output)
            checksums = {file: sha256_file(staging / file) for file in files}
            _atomic_json(staging / manifest_name, {"source": identity, "checksums": checksums})
            if target.exists():
                shutil.rmtree(target)
            os.replace(staging, target)
            return target
        finally:
            shutil.rmtree(staging, ignore_errors=True)
