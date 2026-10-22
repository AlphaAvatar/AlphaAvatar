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

import logging

from alphaavatar.core.log.records import Redactor

logger = logging.getLogger("alphaavatar.plugins.mcp")
_redact = Redactor()


def redact_url(url: str) -> str:
    """Safe display text only; never use this value to make a request."""
    return _redact(url, logger=logger.name)


def redact_text(text: str) -> str:
    """Filter model-facing server descriptions without changing global logging handlers."""
    return _redact(text, logger=logger.name)
