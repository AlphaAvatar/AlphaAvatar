import json
import os
import sys
from pathlib import Path
from typing import Any, Optional, Union

import yaml
from omegaconf import OmegaConf


def read_args(args: Optional[Union[dict[str, Any], list[str]]] = None) -> Union[dict[str, Any], list[str]]:
    r"""Get arguments from the command line or a config file."""
    if args is not None:
        return args

    if sys.argv[1].endswith(".yaml") or sys.argv[1].endswith(".yml"):
        override_config = OmegaConf.from_cli(sys.argv[2:])
        dict_config = yaml.safe_load(Path(sys.argv[1]).absolute().read_text())
        return OmegaConf.to_container(OmegaConf.merge(dict_config, override_config))
    elif sys.argv[1].endswith(".json"):
        override_config = OmegaConf.from_cli(sys.argv[2:])
        dict_config = json.loads(Path(sys.argv[1]).absolute().read_text())
        return OmegaConf.to_container(OmegaConf.merge(dict_config, override_config))
    else:
        return sys.argv[1:]
