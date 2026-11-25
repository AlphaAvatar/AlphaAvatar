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
import numpy as np


class VectorOps:
    @staticmethod
    def as_vector(x) -> np.ndarray:
        """A sequence of numbers as one flat float32 vector."""
        return np.asarray(x, dtype=np.float32).reshape(-1)

    @staticmethod
    def norm(vector: np.ndarray) -> np.ndarray | None:
        """The vector at unit length, or None when its length is not finite (a value of it is not,
        or their squares overflow) or zero; what None means, an error or a skipped input, is the
        caller's."""
        length = float(np.linalg.norm(vector))
        if not np.isfinite(length) or length <= 0:
            return None
        return vector / length

    @staticmethod
    def merge(current: np.ndarray | None, vector: np.ndarray, beta: float) -> np.ndarray:
        """``beta`` of the current vector and the rest of the new one, at unit length; without a
        current vector, the new one at unit length."""
        if current is not None:
            if current.shape != vector.shape:
                raise ValueError(f"Vector shape mismatch: {current.shape} vs {vector.shape}")
            vector = beta * current + (1 - beta) * vector
        merged = VectorOps.norm(vector)
        if merged is None:
            raise ValueError("A merged vector must have a finite, nonzero length")
        return merged
