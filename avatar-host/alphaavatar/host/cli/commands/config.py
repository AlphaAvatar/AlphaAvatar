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
"""Configuration commands: no Host, runner, model, client, workspace or log socket."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

from alphaavatar.core.log.diagnostics import format_error


def _load(path: str, overrides: Sequence[str]):
    from alphaavatar.agents.env import init_env
    from alphaavatar.host.configs.loader import check_application_paths, load_application

    init_env()  # The same .env the start command reads for <ENV_VAR> placeholders.
    config = load_application(path, overrides)
    check_application_paths(config)
    return config


def _failed(error: Exception, *, as_json: bool) -> int:
    from alphaavatar.host.configs.view import describe_error

    if as_json:
        print(json.dumps({"valid": False, "error": describe_error(error)}, indent=2))
    else:
        print(f"Configuration is invalid:\n{format_error(error)}", file=sys.stderr)
    return 2


def check(path: str, overrides: Sequence[str], *, as_json: bool) -> int:
    try:
        config = _load(path, overrides)
    except Exception as error:
        return _failed(error, as_json=as_json)
    summary = {
        "avatar_id": config.avatar.avatar.id,
        "home": str(config.paths.root),
        "workspace": str(config.workspace.root),
    }
    if as_json:
        print(json.dumps({"valid": True, **summary}, indent=2, ensure_ascii=False))
    else:
        print("Configuration is valid.")
        print("\n".join(f"  {key}: {value}" for key, value in summary.items()))
    return 0


def show(path: str, overrides: Sequence[str], *, as_json: bool) -> int:
    try:
        from alphaavatar.host.configs.view import describe_application

        view = describe_application(_load(path, overrides))
    except Exception as error:
        return _failed(error, as_json=as_json)
    if as_json:
        print(json.dumps(view, indent=2, ensure_ascii=False))
    else:
        import yaml

        print(yaml.safe_dump(view, sort_keys=False, allow_unicode=True), end="")
    return 0


def init(path: str, *, avatar_id: str) -> int:
    from alphaavatar.host.configs.template import REQUIRED_ENVIRONMENT, write_template

    try:
        target = write_template(path, avatar_id=avatar_id)
    except FileExistsError:
        print(f"Refusing to overwrite an existing file: {path}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"Cannot create the configuration:\n{format_error(error)}", file=sys.stderr)
        return 2
    print(f"Created {target}")
    print("Set these in the environment or .env (never in the file):")
    print("\n".join(f"  {name:<50} {use}" for name, use in REQUIRED_ENVIRONMENT))
    print(f"Then run: alphaavatar check {path}")
    return 0
