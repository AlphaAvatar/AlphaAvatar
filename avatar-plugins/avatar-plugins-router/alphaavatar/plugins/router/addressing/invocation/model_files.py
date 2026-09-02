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
from __future__ import annotations

import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from alphaavatar.agents.utils.files import build_model_cache_dir

MODEL_NAME = "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
MODEL_URL = (
    f"https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/{MODEL_NAME}.tar.bz2"
)

REQUIRED_FILES = (
    "tokens.txt",
    "en.phone",
    "encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx",
    "decoder-epoch-13-avg-2-chunk-8-left-64.onnx",
    "joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx",
)


def _model_dir() -> Path:
    return build_model_cache_dir(
        "router",
        "addressing",
        "invocation",
        "sherpa_onnx",
        MODEL_NAME,
    )


def _valid_model_dir(path: Path) -> bool:
    return path.is_dir() and all((path / filename).is_file() for filename in REQUIRED_FILES)


def _safe_extract(archive: Path, destination: Path) -> None:
    root = destination.resolve()

    with tarfile.open(archive, "r:bz2") as tar:
        for member in tar.getmembers():
            target = (destination / member.name).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError(f"Unsafe model archive path: {member.name}")

        tar.extractall(destination)


def download_sherpa_kws_model() -> Path:
    target = _model_dir()
    if _valid_model_dir(target):
        return target

    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="sherpa-kws-",
        dir=target.parent,
    ) as temporary:
        temporary_dir = Path(temporary)
        archive = temporary_dir / f"{MODEL_NAME}.tar.bz2"

        with urllib.request.urlopen(MODEL_URL, timeout=120) as response:
            with archive.open("wb") as output:
                shutil.copyfileobj(response, output)

        _safe_extract(archive, temporary_dir)

        extracted = temporary_dir / MODEL_NAME
        if not _valid_model_dir(extracted):
            raise RuntimeError(f"Downloaded Sherpa KWS model is incomplete: {extracted}")

        if target.exists():
            shutil.rmtree(target)

        extracted.replace(target)

    return target


def resolve_sherpa_kws_model_dir(*, local_files_only: bool) -> Path:
    target = _model_dir()

    if _valid_model_dir(target):
        return target

    if local_files_only:
        raise RuntimeError(
            f"Sherpa KWS model is unavailable at {target}. Run `alphaavatar download-files` first."
        )

    return download_sherpa_kws_model()
