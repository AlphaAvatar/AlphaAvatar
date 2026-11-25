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

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, cast

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class AvatarCapability:
    name: str
    description: str
    input_schema: type[BaseModel] | dict[str, Any] | None = None
    _schema_json: str = field(init=False, repr=False)
    _validator: Any = field(init=False, default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Capability name must be a non-empty string")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("Capability description must be a non-empty string")

        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "description", self.description.strip())
        schema = self.input_schema

        if schema is None:
            parameters = {"type": "object", "properties": {}, "additionalProperties": False}
        elif isinstance(schema, type) and issubclass(schema, BaseModel):
            parameters = schema.model_json_schema()
        elif isinstance(schema, dict):
            from jsonschema.validators import validator_for
            from referencing import Registry

            parameters = deepcopy(schema)
            validator_type = validator_for(parameters)
            validator_type.check_schema(parameters)
            validator = validator_type(parameters, registry=Registry())
            object.__setattr__(self, "input_schema", deepcopy(parameters))
            object.__setattr__(self, "_validator", validator)
        else:
            raise TypeError("input_schema must be a BaseModel class, JSON Schema dict, or None")

        object.__setattr__(self, "_schema_json", json.dumps(parameters, allow_nan=False))

    @property
    def id(self) -> str:
        return self.name

    @property
    def callable(self) -> bool:
        return self.input_schema is not None

    @property
    def tool_name(self) -> str:
        name = re.sub(r"[^a-zA-Z0-9_-]+", "_", self.name).strip("_")
        if not name:
            raise ValueError(f"Capability name has no usable tool name: {self.name!r}")
        return (
            name
            if len(name) <= 64
            else f"{name[:47]}_{sha256(self.name.encode()).hexdigest()[:16]}"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return json.loads(self._schema_json)

    @property
    def model_description(self) -> str:
        if self.callable:
            return self.description
        return f"[Description only; do not call this capability.] {self.description}"

    def parse(self, arguments: Mapping[str, Any] | BaseModel | None) -> Any:
        if not self.callable:
            raise TypeError(f"Capability is description-only: {self.id}")
        if isinstance(arguments, BaseModel):
            payload = arguments.model_dump(mode="json", by_alias=True)
        elif arguments is None:
            payload = {}
        elif isinstance(arguments, Mapping):
            payload = deepcopy(dict(arguments))
        else:
            raise TypeError("Capability arguments must be an object")

        if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
            raise TypeError("Capability arguments must be an object with string keys")
        if self._validator is not None:
            self._validator.validate(payload)
            return payload
        return cast(type[BaseModel], self.input_schema).model_validate(payload)
