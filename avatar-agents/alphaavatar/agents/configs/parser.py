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
from pathlib import Path
from typing import Any, NewType

import yaml
from omegaconf import OmegaConf

from .avatar_config import AvatarConfig
from .avatar_info_config import AvatarInfoConfig
from .livekit_plugin_config import LiveKitPluginConfig
from .memory_plugin_config import MemoryConfig

DataClass = NewType("DataClass", Any)
DataClassType = NewType("DataClassType", Any)


_CONFIG_CLS = [AvatarInfoConfig, LiveKitPluginConfig, MemoryConfig]


def read_args(
    args: dict[str, Any] | list[str] | None = None,
) -> dict[str, Any] | list[str]:
    r"""Get arguments from the command line or a config file."""
    if args is not None:
        return args

    if len(sys.argv) >= 2:
        args = {}
        if sys.argv[2].endswith(".yaml") or sys.argv[2].endswith(".yml"):
            override_config = OmegaConf.from_cli(sys.argv[3:])
            dict_config = yaml.safe_load(Path(sys.argv[2]).absolute().read_text())
            args.update(OmegaConf.to_container(OmegaConf.merge(dict_config, override_config)))
        elif sys.argv[2].endswith(".json"):
            override_config = OmegaConf.from_cli(sys.argv[3:])
            dict_config = json.loads(Path(sys.argv[2]).absolute().read_text())
            args.update(OmegaConf.to_container(OmegaConf.merge(dict_config, override_config)))
        else:
            dict_config = OmegaConf.from_cli(sys.argv[2:])
            args.update(OmegaConf.to_container(dict_config))

        sys.argv = sys.argv[:2]  # Keep only the script name and first argument
        return args
    else:
        raise ValueError(
            "No arguments provided. Please provide a config file or command line arguments."
        )


def parse_dict(
    dataclass_types: list[DataClassType], args: dict[str, Any], allow_extra_keys: bool = False
) -> tuple[DataClass, ...]:
    """
    Alternative helper method that does not use `argparse` at all, instead uses a dict and populating the dataclass
    types.

    Args:
        args (`dict`):
            dict containing config values
        allow_extra_keys (`bool`, *optional*, defaults to `False`):
            Defaults to False. If False, will raise an exception if the dict contains keys that are not parsed.

    Returns:
        Tuple consisting of:

            - the dataclass instances in the same order as they were passed to the initializer.
    """
    unused_keys = set(args.keys())
    outputs = []
    for dtype in dataclass_types:
        keys = {f.name for f in dataclasses.fields(dtype) if f.init}
        inputs = {k: v for k, v in args.items() if k in keys}
        unused_keys.difference_update(inputs.keys())
        obj = dtype(**inputs)
        outputs.append(obj)
    if not allow_extra_keys and unused_keys:
        raise ValueError(f"Some keys are not used by the HfArgumentParser: {sorted(unused_keys)}")
    return tuple(outputs)


def get_avatar_args(args: dict[str, Any] | list[str] | None = None) -> AvatarConfig:
    avatar_info, livekit_plugin_config, memory_config = parse_dict(_CONFIG_CLS, args)

    # TODO: post-validation

    avatar_config = AvatarConfig(
        avatar_info=avatar_info,
        livekit_plugin_config=livekit_plugin_config,
        memory_config=memory_config,
    )

    return avatar_config
