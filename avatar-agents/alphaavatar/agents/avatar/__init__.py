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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .engine import AvatarEngine

__all__ = ["AvatarEngine"]


def __getattr__(name: str) -> Any:
    if name != "AvatarEngine":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .engine import AvatarEngine

    globals()[name] = AvatarEngine
    return AvatarEngine
