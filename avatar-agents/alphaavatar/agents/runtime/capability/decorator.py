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

import inspect
from typing import Any

from pydantic import BaseModel

from .schema import AvatarCapability


def validate_handler(handler: Any, *, bound: bool = True) -> None:
    if not inspect.iscoroutinefunction(handler) or getattr(handler, "__isabstractmethod__", False):
        raise TypeError("Callable capabilities require a concrete async invoke handler")
    parameters = tuple(inspect.signature(handler).parameters.values())
    positional = {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    if len(parameters) != (1 if bound else 2) or any(p.kind not in positional for p in parameters):
        raise TypeError("Expected async invoke(self, request), or an async handler(request)")


def avatar_capability(
    *,
    name: str,
    description: str,
    input_schema: type[BaseModel] | dict[str, Any] | None = None,
):
    capability = AvatarCapability(name, description, input_schema)

    def decorate(cls: type) -> type:
        if not inspect.isclass(cls):
            raise TypeError("avatar_capability decorates classes")
        if capability.callable:
            validate_handler(inspect.getattr_static(cls, "invoke", None), bound=False)

        inherited = tuple(getattr(cls, "capabilities", ()))
        declared = cls.__dict__.get("capabilities", ())
        if any(item.id == capability.id for item in declared):
            raise ValueError(f"Capability already declared on {cls.__name__}: {capability.id}")
        cls.capabilities = (*[item for item in inherited if item.id != capability.id], capability)
        return cls

    return decorate
