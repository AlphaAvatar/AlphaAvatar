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
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..enums import MCPOp, MCPOutputMode

MCP_TOOL_CATEGORIES = ("read", "write", "unknown")
MCP_TOP_K_RANGE = (1, 50)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate MCP argument key")
        result[key] = value
    return result


def _number(value: str) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError("MCP arguments must be finite")
    return number


def _constant(value: str) -> Any:
    raise ValueError("MCP arguments must be finite")


def parse_params(value: str) -> dict[str, dict[str, Any]]:
    result = json.loads(
        value, object_pairs_hook=_object, parse_float=_number, parse_constant=_constant
    )
    if not isinstance(result, dict) or not result:
        raise ValueError("MCP params_json must be a nonempty tool-id to arguments object")
    if any(not key.strip() or not isinstance(args, dict) for key, args in result.items()):
        raise ValueError("MCP tool IDs must be nonempty and each argument value must be an object")
    return result


class MCPRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    op: MCPOp
    query: str | None = Field(default=None, min_length=1)
    params_json: str | None = Field(default=None, min_length=1, max_length=65_536)
    top_k: int = Field(default=8, strict=True, ge=1, le=50)
    server_keys: list[str] | None = Field(default=None, min_length=1)
    categories: list[Literal["read", "write", "unknown"]] | None = Field(default=None, min_length=1)
    output_mode: MCPOutputMode = MCPOutputMode.RAW

    @model_validator(mode="after")
    def validate_operation(self) -> MCPRequest:
        if self.server_keys is not None and any(not key.strip() for key in self.server_keys):
            raise ValueError("MCP server keys must be nonempty")
        if self.op == MCPOp.TOOL_SEARCH and not self.query:
            raise ValueError("MCP tool_search requires a nonempty query")
        if self.op == MCPOp.TOOL_CALL:
            if not self.params_json:
                raise ValueError("MCP tool_call requires params_json")
            try:
                parse_params(self.params_json)
            except (ValueError, RecursionError) as exc:
                raise ValueError("Invalid MCP params_json") from exc
        return self
