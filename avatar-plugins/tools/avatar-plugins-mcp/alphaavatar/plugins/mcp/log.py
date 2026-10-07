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
import logging

from .redact import RedactingFilter

logger = logging.getLogger("alphaavatar.plugins.mcp")

# Mask tokens, API keys, passwords, and authorization values in everything MCP logs.
# Third-party loggers that print the full MCP server URL (including its query string,
# e.g. httpx's "HTTP Request: POST <url>" at INFO) are covered too; a logger's filters
# do not apply to its children, so each one is listed explicitly.
_REDACTED_LOGGERS = (
    logger.name,
    "httpx",
    "mcp.client.streamable_http",
    "mcp.client.sse",
)

for _name in _REDACTED_LOGGERS:
    _target = logging.getLogger(_name)
    if not any(isinstance(f, RedactingFilter) for f in _target.filters):
        _target.addFilter(RedactingFilter())
