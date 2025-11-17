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
import dataclasses
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, TypeGuard, TypeVar

import yaml
from omegaconf import OmegaConf

from .avatar_config import AvatarConfig
from .avatar_info_config import AvatarInfoConfig
from .plugins.character_plugin_config import VirtualCharacterConfig
from .plugins.livekit_plugin_config import LiveKitPluginConfig
from .plugins.memory_plugin_config import MemoryConfig
from .plugins.persona_plugin_config import PersonaConfig

_CONFIG_CLS = [
    LiveKitPluginConfig,
    AvatarInfoConfig,
    VirtualCharacterConfig,
    MemoryConfig,
    PersonaConfig,
]


class _DataclassInstance(Protocol):
    # Minimal attribute that typeshed uses to recognize dataclasses
    __dataclass_fields__: dict[str, Any]


# A dataclass *instance* type variable
ConfigT = TypeVar("ConfigT", bound=_DataclassInstance)

# The class (constructor) that produces ConfigT
ConfigClassType = type[ConfigT]
# The instance type (for readability / parity with your names)
ConfigClass = ConfigT


def _is_dataclass_type(tp: object) -> TypeGuard[ConfigClassType[Any]]:
    """TypeGuard so Pylance knows `tp` is a dataclass *type*, not just any type."""
    return isinstance(tp, type) and dataclasses.is_dataclass(tp)


def _ensure_mapping(obj: Any) -> dict[str, Any]:
    """Ensure the object is a mapping (dict).
    Raises an error if the top-level object is list/str/None.
    This prevents passing invalid types to dict.update()."""
    if isinstance(obj, Mapping):
        # Normalize keys to str in case they are not strings
        return {str(k): v for k, v in obj.items()}
    raise TypeError("Top-level config must be a mapping (dict), not a list/str/None.")


def read_args() -> dict[str, Any]:
    r"""Get arguments from the command line or a config file.

    Supports:
    - python script.py <cmd> <config.{yaml|yml|json}> [--k=v ...]
    - python script.py <cmd> --k=v ...
    """
    if len(sys.argv) < 2:
        raise ValueError("No arguments provided. Provide a command and config/CLI args.")

    args: dict[str, Any] = {}

    # Case A: user provides a config file
    if len(sys.argv) >= 3 and (sys.argv[2].endswith((".yaml", ".yml", ".json"))):
        config_path = Path(sys.argv[2]).absolute()

        # Load CLI overrides from arguments after the config file
        override_cfg = OmegaConf.from_cli(sys.argv[3:])

        # Load the base config depending on file type
        if config_path.suffix.lower() in {".yaml", ".yml"}:
            base_dict = yaml.safe_load(config_path.read_text())
        else:  # .json
            base_dict = json.loads(config_path.read_text())

        # Merge base config with overrides
        merged = OmegaConf.merge(base_dict, override_cfg)
        container = OmegaConf.to_container(merged, resolve=True)

        # Only accept dict at the top level, reject list/str/None
        args.update(_ensure_mapping(container))

        # Keep only script name and command in sys.argv
        sys.argv = sys.argv[:2]
        return args

    # Case B: no config file, only CLI arguments
    cli_cfg = OmegaConf.from_cli(sys.argv[2:])
    container = OmegaConf.to_container(cli_cfg, resolve=True)
    args.update(_ensure_mapping(container))

    sys.argv = sys.argv[:2]
    return args


def parse_dict(
    dataclass_types: Sequence[ConfigClassType[Any]],
    args: dict[str, Any],
    allow_extra_keys: bool = False,
) -> tuple[ConfigClass, ...]:
    """
    Alternative helper that avoids `argparse`: fill provided dataclass *types* from a dict.

    Args:
        dataclass_types: Sequence of dataclass types to instantiate (in order).
        args: Dict containing config values.
        allow_extra_keys: If False, raise on keys that are not consumed by any dataclass.

    Returns:
        Tuple of instantiated dataclass objects, in the same order as `dataclass_types`.
    """
    unused_keys = set(args.keys())
    outputs: list[ConfigClass] = []

    for dtype in dataclass_types:
        # Runtime+static check: ensure this really is a dataclass type
        if not _is_dataclass_type(dtype):
            raise TypeError(f"Expected a dataclass type, got: {dtype!r}")

        # Collect init-able field names for this dataclass
        keys = {f.name for f in dataclasses.fields(dtype) if f.init}

        # Slice out the matching inputs
        inputs = {k: v for k, v in args.items() if k in keys}
        unused_keys.difference_update(inputs.keys())

        # Instantiate
        obj = dtype(**inputs)  # type: ignore[call-arg]  # (fields() guarantees names)
        outputs.append(obj)  # type: ignore[arg-type]

    if not allow_extra_keys and unused_keys:
        raise ValueError(f"Some keys are not used by the parser: {sorted(unused_keys)}")

    return tuple(outputs)


def get_avatar_args(args: dict[str, Any]) -> AvatarConfig:
    livekit_plugin_config, avatar_info, character_config, memory_config, persona_config = (
        parse_dict(_CONFIG_CLS, args)
    )

    # TODO: post-validation

    avatar_config = AvatarConfig(
        livekit_plugin_config=livekit_plugin_config,
        avatar_info=avatar_info,
        character_config=character_config,
        memory_config=memory_config,
        persona_config=persona_config,
    )

    return avatar_config
