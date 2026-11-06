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
import hashlib
import os
import re
from typing import Any
from urllib.parse import urlsplit

ENV_PATTERN = re.compile(r"<([A-Z0-9_]+)>")
SERVER_KEY = "ALPHAAVATAR_SERVER_KEY_"


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


def server_key(url: str) -> str:
    """The variable `alphaavatar setup` stores a server of one's own's key in, named after that
    endpoint: a default port and a trailing ``/`` are the same endpoint, another path is not."""
    parts = urlsplit(url)
    port = parts.port or {"http": 80, "https": 443}[parts.scheme]
    endpoint = f"{parts.scheme}://[{parts.hostname}]:{port}{parts.path.rstrip('/')}"
    return SERVER_KEY + hashlib.sha256(endpoint.encode()).hexdigest()[:12].upper()


def check_server_key(api_key_env: Any, base_url: Any) -> None:
    """A key variable named after a server is read for that server alone: a client reading
    ``api_key_env`` sends its key to ``base_url``, which must be the URL it is named after.
    Variables of other names are one's own to point anywhere."""
    if not (isinstance(api_key_env, str) and api_key_env.startswith(SERVER_KEY)):
        return

    try:
        serves = isinstance(base_url, str) and server_key(base_url) == api_key_env
    except (KeyError, ValueError):  # Not an http(s) URL, or no valid port: no endpoint.
        serves = False
    if not serves:
        # The URL is not repeated: it may embed credentials.
        raise ValueError(
            f"api_key_env {api_key_env} holds the key of the server it is named after, which "
            "base_url is not: run `alphaavatar setup` for this server, or name a variable of "
            "your own"
        )
