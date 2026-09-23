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
from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .avatar_runtime import AvatarRuntime
    from .context_runtime import ContextRuntime, InteractionMethod
    from .session_runtime import ParticipantIdentityResolution, ParticipantInfo, SessionRuntime

__all__ = [
    "AvatarRuntime",
    "ContextRuntime",
    "InteractionMethod",
    "ParticipantInfo",
    "ParticipantIdentityResolution",
    "SessionRuntime",
]

_EXPORTS = {
    "AvatarRuntime": ".avatar_runtime",
    "ContextRuntime": ".context_runtime",
    "InteractionMethod": ".context_runtime",
    "ParticipantInfo": ".session_runtime",
    "ParticipantIdentityResolution": ".session_runtime",
    "SessionRuntime": ".session_runtime",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
