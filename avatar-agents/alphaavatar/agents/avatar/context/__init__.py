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
"""Context contracts import independently of Engine, RTC and provider SDKs."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import ModelContextSource
    from .context_manager import AvatarContext, AvatarContextManager
    from .context_status import AvatarContextStatus, extract_answer_text
    from .query import SnapshotContextSource

_EXPORTS = {
    "AvatarContext": ".context_manager",
    "AvatarContextManager": ".context_manager",
    "AvatarContextStatus": ".context_status",
    "extract_answer_text": ".context_status",
    "ModelContextSource": ".base",
    "SnapshotContextSource": ".query",
}
__all__ = [
    "AvatarContext",
    "AvatarContextManager",
    "AvatarContextStatus",
    "extract_answer_text",
    "ModelContextSource",
    "SnapshotContextSource",
]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value
