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


class NumpyOP:
    @staticmethod
    def to_np(x) -> np.ndarray:
        arr = np.asarray(x, dtype=np.float32).reshape(-1)
        return arr

    @staticmethod
    def l2_normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
        n = np.linalg.norm(x) + eps
        return x / n
