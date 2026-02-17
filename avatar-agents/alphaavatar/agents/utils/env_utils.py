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
import os
import re
from typing import Any

ENV_PATTERN = re.compile(r"<([A-Z0-9_]+)>")


def resolve_env_placeholders(value: Any) -> Any:
    """
    Recursively resolve <ENV_VAR> placeholders in dict/list/str structures.
    """

    if isinstance(value, str):

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            env_value = os.getenv(var_name)
            if env_value is None:
                raise ValueError(
                    f"Environment variable '{var_name}' is not set but is required in config"
                )
            return env_value

        return ENV_PATTERN.sub(replacer, value)

    elif isinstance(value, dict):
        return {k: resolve_env_placeholders(v) for k, v in value.items()}

    elif isinstance(value, list):
        return [resolve_env_placeholders(v) for v in value]

    else:
        return value
