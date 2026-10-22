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

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from alphaavatar.agents.avatar.provider.errors import ModelCapabilityError


def strict_schema(schema: Mapping[str, Any], *, complete_objects: bool = False) -> dict[str, Any]:
    """Tools are checked without changing meaning; output models use closed, total objects."""
    result = deepcopy(dict(schema))
    Draft202012Validator.check_schema(result)
    if result.get("type") != "object":
        raise ModelCapabilityError("Strict Responses schemas require an object root")

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            raise ModelCapabilityError("Boolean/non-object schema nodes are not supported")
        if {"allOf", "oneOf", "not", "if", "then", "else", "patternProperties"} & node.keys():
            raise ModelCapabilityError("Responses strict schema contains unsupported composition")
        if complete_objects:
            node.pop("default", None)
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties", {})
            if not isinstance(properties, dict):
                raise ModelCapabilityError("Object properties must be a mapping")
            if complete_objects:
                if node.get("additionalProperties") not in (None, False):
                    raise ModelCapabilityError(
                        "Unbounded dictionaries need an explicit output schema"
                    )
                node["additionalProperties"] = False
                node["required"] = list(properties)
            if node.get("additionalProperties") is not False:
                raise ModelCapabilityError("Strict tool objects require additionalProperties=false")
            if set(node.get("required", [])) != set(properties):
                raise ModelCapabilityError(
                    "Strict tools require every property; use nullable fields"
                )
        for key in ("properties", "$defs", "definitions"):
            for child in node.get(key, {}).values():
                visit(child)
        if "items" in node:
            visit(node["items"])
        for child in node.get("anyOf", []):
            visit(child)

    visit(result)
    return result


def output_format(schema: type[BaseModel]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "alphaavatar_output",
        "strict": True,
        "schema": strict_schema(schema.model_json_schema(), complete_objects=True),
    }
