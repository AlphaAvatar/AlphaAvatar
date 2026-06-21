# Copyright 2025 AlphaAvatar project
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
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from omegaconf import OmegaConf

from .avatar_config import AvatarConfig


def _ensure_mapping(obj: Any) -> dict[str, Any]:
    if isinstance(obj, Mapping):
        return {str(k): v for k, v in obj.items()}

    raise TypeError("Top-level config must be a mapping (dict), not a list/str/None.")


def _load_config_file(config_path: Path) -> dict[str, Any]:
    suffix = config_path.suffix.lower()

    if suffix in {".yaml", ".yml"}:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    elif suffix == ".json":
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported config file type: {config_path}")

    return _ensure_mapping(loaded)


def read_args() -> dict[str, Any]:
    if len(sys.argv) < 2:
        raise ValueError("No arguments provided. Provide a command and config/CLI args.")

    if len(sys.argv) >= 3 and sys.argv[2].lower().endswith((".yaml", ".yml", ".json")):
        config_path = Path(sys.argv[2]).absolute()

        base_dict = _load_config_file(config_path)
        override_cfg = OmegaConf.from_cli(sys.argv[3:])

        merged = OmegaConf.merge(base_dict, override_cfg)
        container = OmegaConf.to_container(merged, resolve=True)

        sys.argv = sys.argv[:2]
        return _ensure_mapping(container)

    cli_cfg = OmegaConf.from_cli(sys.argv[2:])
    container = OmegaConf.to_container(cli_cfg, resolve=True)

    sys.argv = sys.argv[:2]
    return _ensure_mapping(container)


def get_avatar_args(args: dict[str, Any]) -> AvatarConfig:
    return AvatarConfig.model_validate(args)
