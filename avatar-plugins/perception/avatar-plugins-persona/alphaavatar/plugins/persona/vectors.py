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

from dataclasses import dataclass

import numpy as np

from alphaavatar.agents.utils import NumpyOP


@dataclass(slots=True)
class WeightedMean:
    """Unit vectors summed, each weighted by the seconds of audio it is from. Its direction is
    their mean in any order, and a short segment's vector counts for its length only."""

    total: np.ndarray

    @classmethod
    def of(cls, vector: np.ndarray, seconds: float) -> WeightedMean:
        if not seconds > 0:
            raise ValueError(f"A vector's weight must be positive seconds: {seconds}")
        return cls(np.asarray(vector, dtype=np.float64) * seconds)

    @property
    def vector(self) -> np.ndarray:
        return NumpyOP.l2_normalize(self.total).astype(np.float32)

    def add(self, vector: np.ndarray, seconds: float) -> None:
        self.extend(WeightedMean.of(vector, seconds))

    def extend(self, other: WeightedMean) -> None:
        if other.total.shape != self.total.shape:
            raise ValueError(
                f"Identity vector shape mismatch: {self.total.shape} vs {other.total.shape}"
            )
        self.total = self.total + other.total

    def copy(self) -> WeightedMean:
        return WeightedMean(self.total.copy())
