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

from dataclasses import dataclass, field

import numpy as np

from .ops import VectorOps


def _unit(total: np.ndarray) -> np.ndarray:
    vector = VectorOps.norm(total)
    if vector is None:
        raise ValueError("A weighted mean must have a finite, nonzero length")
    return vector.astype(np.float32)


@dataclass(slots=True)
class WeightedMean:
    """Unit vectors summed, each weighted by the seconds of audio it is from. Its direction is
    their mean in any order, and a short segment's vector counts for its length only. The
    normalized mean is kept as each vector is added, not recomputed at every comparison."""

    total: np.ndarray
    vector: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.vector = _unit(self.total)

    @classmethod
    def of(cls, vector: np.ndarray, seconds: float) -> WeightedMean:
        if not seconds > 0:
            raise ValueError(f"A vector's weight must be positive seconds: {seconds}")
        return cls(np.asarray(vector, dtype=np.float64) * seconds)

    def add(self, vector: np.ndarray, seconds: float) -> None:
        self.extend(WeightedMean.of(vector, seconds))

    def extend(self, other: WeightedMean) -> None:
        if other.total.shape != self.total.shape:
            raise ValueError(f"Vector shape mismatch: {self.total.shape} vs {other.total.shape}")
        # A sum without a length is refused before either changes.
        total = self.total + other.total
        self.vector = _unit(total)
        self.total = total

    def copy(self) -> WeightedMean:
        return WeightedMean(self.total.copy())
