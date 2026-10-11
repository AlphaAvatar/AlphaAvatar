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

from math import isfinite


def identifier(value: object, name: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if type(value) is not str or not value or value != value.strip() or len(value) > 2048:
        raise ValueError(f"{name} must be a bounded nonempty identity")


def boolean(value: object, name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be bool")


def counter(value: object, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def time_range(start: float | None, end: float | None) -> None:
    for value in (start, end):
        if value is not None and (
            type(value) not in (int, float) or not isfinite(value) or value < 0
        ):
            raise ValueError("Output times must be finite and nonnegative")
    if start is not None and end is not None and end < start:
        raise ValueError("Output end cannot precede start")


def identities(values: tuple[str, ...], name: str, *, required: bool = False) -> None:
    if type(values) is not tuple or len(values) > 1024 or (required and not values):
        raise ValueError(f"{name} must be a bounded identity tuple")
    for value in values:
        identifier(value, name)
    if len(set(values)) != len(values):
        raise ValueError(f"{name} cannot contain duplicates")
