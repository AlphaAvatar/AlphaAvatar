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
from enum import StrEnum
from typing import Any, get_args, get_origin

import numpy as np
from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from alphaavatar.agents.utils import NumpyOP


class ProfileItemSource(StrEnum):
    chat = "chat"
    speech = "speech"
    visual = "visual"


class ProfileItemView(BaseModel):
    value: str
    source: ProfileItemSource
    timestamp: str


class DetailsBase(BaseModel):
    @classmethod
    def field_descriptions_prompt(cls) -> str:
        """
        Return a formatted string with `field (type): description` for all fields,
        where the type is constrained to `ProfileItemView` or `list[ProfileItemView]`.
        This keeps the prompt focused on the only two allowed shapes.
        """

        def _type_label(tp: Any) -> str:
            if tp is ProfileItemView:
                return "String"
            origin = get_origin(tp)
            if origin in (list, list):
                args = get_args(tp) or ()
                if len(args) == 1 and args[0] is ProfileItemView:
                    return "list[String]"
            # Fallback for unexpected annotations (should not happen due to __init_subclass__)
            return "Unsupported"

        lines: list[str] = []
        for name, field in cls.model_fields.items():  # Pydantic v2 FieldInfo
            ann = getattr(field, "annotation", Any)
            typ_str = _type_label(ann)
            desc = field.description or ""
            lines.append(f"{name} ({typ_str}): {desc}")

        return "\n".join(lines)

    def __init_subclass__(cls, **kwargs):
        """
        Enforce that every field annotation in subclasses is either:
          - ProfileItemView
          - list[ProfileItemView] (also accepts typing.List[ProfileItemView])

        If any field does not match the allowed shapes, raise TypeError at class
        definition time to fail fast.
        """
        super().__init_subclass__(**kwargs)

        def _is_itemview_or_list(tp: Any) -> bool:
            if tp is ProfileItemView:
                return True
            origin = get_origin(tp)
            if origin in (list, list):
                args = get_args(tp) or ()
                return len(args) == 1 and args[0] is ProfileItemView
            return False

        for name, field in cls.model_fields.items():
            ann = getattr(field, "annotation", None)
            if not _is_itemview_or_list(ann):
                raise TypeError(
                    f"{cls.__name__}.{name} must be annotated as ProfileItemView or list[ProfileItemView], "
                    f"got {ann!r}."
                )


class UserProfile(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    details: "DetailsBase | None" = None
    speaker_vector: np.ndarray | None = None

    @field_validator("speaker_vector", mode="before")
    @classmethod
    def _coerce_and_validate_vec(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            v = NumpyOP.l2_normalize(NumpyOP.to_np(v))
        elif isinstance(v, np.ndarray):
            if v.dtype != np.float32:
                v = v.astype(np.float32, copy=False)
        else:
            raise TypeError("speaker_vector must be a 1D numpy array or list of floats.")
        if v.ndim != 1:
            raise ValueError("speaker_vector must be a 1-dimensional array.")
        return v

    # Optional: make JSON export friendly
    @field_serializer("speaker_vector")
    def _serialize_vec(self, v: np.ndarray | None):
        return None if v is None else v.tolist()
