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
from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin

from pydantic import BaseModel

if TYPE_CHECKING:
    from .cache import PersonaCache


class DetailsBase(BaseModel):
    @classmethod
    def field_descriptions_prompt(cls) -> str:
        """
        Return a formatted string with `field (type): description` for all fields.
        Useful as structured guidance to an LLM.
        """

        def _type_to_str(tp: Any) -> str:
            # No annotation → Any
            if tp is None:
                return "Any"

            origin = get_origin(tp)
            # Non-generic / builtins
            if origin is None:
                if tp is str:
                    return "str"
                if tp is int:
                    return "int"
                if tp is float:
                    return "float"
                if tp is bool:
                    return "bool"
                if tp is Any:
                    return "Any"
                # Fallback to name/str
                return getattr(tp, "__name__", str(tp))

            args = get_args(tp)

            # Containers
            if origin in (list, set):
                inner = _type_to_str(args[0]) if args else "Any"
                return f"{origin.__name__}[{inner}]"
            if origin is tuple:
                if args and args[-1] is Ellipsis:
                    inner = ", ".join(_type_to_str(a) for a in args[:-1]) + ", ..."
                else:
                    inner = ", ".join(_type_to_str(a) for a in args) if args else "Any"
                return f"tuple[{inner}]"
            if origin is dict:
                k = _type_to_str(args[0]) if len(args) > 0 else "Any"
                v = _type_to_str(args[1]) if len(args) > 1 else "Any"
                return f"dict[{k}, {v}]"

            # Unions / Optional
            if origin is Union:
                parts = list(args)
                if type(None) in parts:
                    non_none = [a for a in parts if a is not type(None)]
                    if not non_none:
                        return "Optional[Any]"
                    return "Optional[" + " | ".join(_type_to_str(a) for a in non_none) + "]"
                return " | ".join(_type_to_str(a) for a in parts)

            # Fallback
            return str(origin)

        lines: list[str] = []
        for name, field in cls.model_fields.items():  # Pydantic v2: FieldInfo objects
            tp = getattr(field, "annotation", Any)
            typ_str = _type_to_str(tp)
            desc = field.description or ""
            lines.append(f"{name} ({typ_str}): {desc}")

        return "\n".join(lines)

    def __init_subclass__(cls, **kwargs):
        """
        This hook runs automatically whenever a new subclass of DetailsBase is defined.
        Its purpose here is to enforce that all fields in subclasses are "flat":
          - Allowed: primitive types (str, int, float, bool), lists, dicts, unions, enums, etc.
          - Not allowed: nested Pydantic models (BaseModel or subclasses of BaseModel).

        If a field is detected as a nested BaseModel, a TypeError is raised immediately
        at class definition time. This prevents creation of complex/nested schemas and
        ensures all subclasses of DetailsBase remain flat structures.
        """
        super().__init_subclass__(**kwargs)

        for name, field in cls.model_fields.items():
            outer_type = field.annotation
            origin = get_origin(outer_type)

            if isinstance(outer_type, type) and issubclass(outer_type, BaseModel):
                raise TypeError(
                    f"Field '{name}' in {cls.__name__} is a nested BaseModel, "
                    "which is not allowed. Only flat structures are permitted."
                )

            if origin is not None and issubclass(origin, BaseModel):  # e.g. List[SomeModel]
                raise TypeError(
                    f"Field '{name}' in {cls.__name__} contains a nested BaseModel "
                    "which is not allowed."
                )


class UserProfile(BaseModel):
    details: DetailsBase
    timestamp: dict


class ProfilerBase:
    def __init__(self):
        pass

    @abstractmethod
    async def load(self, *, user_id: str) -> UserProfile: ...

    @abstractmethod
    async def search(self, *, profile: UserProfile): ...

    @abstractmethod
    async def update(self, *, perona: PersonaCache): ...

    @abstractmethod
    async def save(self, *, user_id: str, perona: PersonaCache) -> None: ...
