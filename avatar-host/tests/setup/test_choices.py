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
"""What setup offers: each selection asks for exactly what its bundle needs once installed."""

from __future__ import annotations

import importlib.util
import itertools
import os
from pathlib import Path
from unittest import mock

import pytest
import yaml
from omegaconf import OmegaConf

# Imported at collection: the persona plugin's OpenCV adjusts process variables (O-2).
import alphaavatar.plugins.persona  # noqa: F401
from alphaavatar.agents.runtime.inference import plan_inference_runners
from alphaavatar.host.configs import resolve_capabilities, validate_application
from alphaavatar.host.configs.template import render_bundle
from alphaavatar.host.setup.choices import PRESETS, Selection, credentials, requirements, sections
from alphaavatar.host.setup.plan import plan_install
from alphaavatar.host.workspace import ApplicationPaths

ROOT = Path(__file__).resolve().parents[3]
SELECTIONS = [
    Selection(*values)
    for values in itertools.product(
        (True, False), (True, False), (True, False), ("lancedb", "qdrant")
    )
]
# Models and the libraries that run them, besides Silero's ONNX Runtime; and CUDA.
LOCAL = {
    "insightface",
    "llama-cpp-python",
    "onnx",
    "safetensors",
    "scikit-image",
    "scipy",
    "tokenizers",
    "torch",
    "torchaudio",
    "transformers",
}


def compose(selection: Selection, home: Path):
    texts = render_bundle("chosen", "chosen", sections=sections(selection))
    bundle = yaml.safe_load(texts["bundles/chosen.yaml"])
    for section, reference in bundle.pop("profiles").items():
        bundle[section] = yaml.safe_load(texts[f"profiles/{reference}.yaml"])
    resolved = OmegaConf.to_container(OmegaConf.create(bundle), resolve=True)
    return validate_application(resolved, paths=ApplicationPaths.from_root(home))


def label(selection: Selection) -> str:
    parts = (selection.voice, selection.vision, selection.local_models, selection.vector_store)
    return "-".join(map(str, parts))


@pytest.mark.parametrize("selection", SELECTIONS, ids=label)
def test_each_selection_asks_for_exactly_what_its_bundle_resolves_to(
    selection: Selection, tmp_path: Path
) -> None:
    # An endpoint in the environment moves no vector store a LanceDB selection chose.
    with mock.patch.dict(os.environ, {"QDRANT_URL": "http://qdrant.invalid:6333"}):
        config = compose(selection, tmp_path / "home")
        found = sorted({need.requirement for need in resolve_capabilities(config).needs})
    assert found == list(requirements(selection))
    names = [credential.name for credential in credentials(selection) if credential.required]
    assert ("QDRANT_URL" in names) == (selection.vector_store == "qdrant")


def test_the_presets_keep_vision_and_plan_their_runners(tmp_path: Path) -> None:
    default = compose(PRESETS["default"], tmp_path / "default")
    remote = compose(PRESETS["remote"], tmp_path / "remote")
    assert default.avatar.vision.enabled and remote.avatar.vision.enabled
    assert len(plan_inference_runners(default.avatar)) == 8
    # Remote inference keeps the voice activity detection speech segments come from.
    assert sorted(plan_inference_runners(remote.avatar)) == [
        "alphaavatar.memory.vdb.lancedb",
        "alphaavatar.persona.vdb.lancedb",
        "alphaavatar.voice.vad.silero",
    ]


def test_remote_inference_plans_no_local_model_nor_its_accelerators() -> None:
    """From uv.lock through the Linux build's own catalog logic to setup's plan."""
    spec = importlib.util.spec_from_file_location("catalog", ROOT / "packaging/linux/catalog.py")
    assert spec is not None and spec.loader is not None
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    keys = catalog.requirement_keys(catalog.Lock(ROOT), ROOT)
    names = sorted({name for closure in keys.values() for name in closure})
    artifact = {"version": "0", "sha256": "0" * 64, "size": 1, "url": None}
    document = {
        "format": 1,
        "version": "0",
        "platform": catalog.PLATFORM,
        "base": sorted({*catalog.base_names(ROOT), *catalog.BASE_MEMBERS}),
        "requirements": {key: sorted(closure) for key, closure in keys.items()},
        "distributions": {name: artifact | {"file": f"{name}.whl"} for name in names},
    }

    def planned(selection: Selection) -> set[str]:
        plan = plan_install(document, requirements(selection), base="base")
        return {item.name for item in plan.artifacts}

    default, remote = planned(PRESETS["default"]), planned(PRESETS["remote"])
    silent = planned(Selection(voice=False, local_models=False))
    assert LOCAL <= default and "onnxruntime" in default
    assert not LOCAL & remote and "onnxruntime" in remote  # Silero VAD only.
    assert not LOCAL & silent and "onnxruntime" not in silent
    for plan in (default, remote, silent):
        # No CUDA library, and only the headless OpenCV.
        assert not {n for n in plan if n.startswith("nvidia-") or n in ("triton", "opencv-python")}
        assert not plan & set(document["base"])
