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
from collections.abc import Mapping
from typing import TypeVar

import numpy as np

T = TypeVar("T")


class NumpyOP:
    @staticmethod
    def to_np(x) -> np.ndarray:
        return np.asarray(x, dtype=np.float32).reshape(-1)

    @staticmethod
    def l2_normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
        return x / (np.linalg.norm(x) + eps)

    @staticmethod
    def best_cosine_match(
        vector: np.ndarray,
        gallery: Mapping[T, np.ndarray],
        threshold: float,
    ) -> T | None:
        if not gallery:
            return None

        ids = list(gallery)
        vector = NumpyOP.l2_normalize(NumpyOP.to_np(vector))
        matrix = np.stack([NumpyOP.l2_normalize(NumpyOP.to_np(gallery[key])) for key in ids])
        scores = matrix @ vector
        index = int(np.argmax(scores))
        return ids[index] if float(scores[index]) >= threshold else None
