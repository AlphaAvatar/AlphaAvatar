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
"""Vector arithmetic of identity matching: a checked unit vector, the merge into a stored vector
and the mean weighted by seconds."""

from __future__ import annotations

import numpy as np
import pytest

from alphaavatar.agents.utils.vector import VectorOps, WeightedMean


def unit(*values: float) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def test_norm_gives_a_unit_vector_only_for_a_finite_nonzero_length() -> None:
    raw = np.asarray([3.0, 4.0], dtype=np.float32)
    assert VectorOps.norm(raw) == pytest.approx([0.6, 0.8])
    assert raw.tolist() == [3.0, 4.0]  # The input is left as it was.

    # No length, a value that is not finite, and finite values whose squares overflow.
    for invalid in ([0.0, 0.0], [np.nan, 1.0], [-np.inf, 1.0], [3e38, 3e38]):
        assert VectorOps.norm(np.asarray(invalid, dtype=np.float32)) is None


def test_a_merge_keeps_beta_of_the_current_vector() -> None:
    current, new = unit(1, 0), unit(0, 1)
    assert VectorOps.merge(None, new * 2, 0.95) == pytest.approx(new)
    assert VectorOps.merge(current, new, 0.95) == pytest.approx(unit(0.95, 0.05))
    with pytest.raises(ValueError, match="shape mismatch"):
        VectorOps.merge(current, unit(1, 0, 0), 0.95)

    # A result without a finite, nonzero length is an error, never a zero or NaN vector.
    for base, invalid in ((None, [0.0, 0.0]), (current, [np.nan, 1.0])):
        with pytest.raises(ValueError, match="finite, nonzero length"):
            VectorOps.merge(base, np.asarray(invalid, dtype=np.float32), 0.95)


def test_a_weighted_mean_counts_each_vector_by_its_seconds_in_any_order() -> None:
    first, second, third = unit(1, 0), unit(0, 1), unit(1, 1)
    forward = WeightedMean.of(first, 0.5)
    forward.add(second, 3.0)
    forward.add(third, 1.0)
    backward = WeightedMean.of(third, 1.0)
    backward.extend(WeightedMean.of(second, 3.0))
    backward.add(first, 0.5)

    # The kept mean is current after every addition, whichever way it came.
    expected = unit(*(0.5 * first + 3.0 * second + 1.0 * third))
    assert forward.vector == pytest.approx(expected)
    assert backward.vector == pytest.approx(expected)


def test_a_copy_of_a_weighted_mean_grows_on_its_own() -> None:
    mean = WeightedMean.of(unit(1, 0), 3.0)
    copy = mean.copy()
    copy.add(unit(0, 1), 3.0)
    assert mean.vector == pytest.approx(unit(1, 0))
    assert copy.vector == pytest.approx(unit(1, 1))


def test_a_weighted_mean_without_a_length_is_refused_and_the_mean_stays() -> None:
    with pytest.raises(ValueError, match="finite, nonzero length"):
        WeightedMean.of(np.zeros(2, dtype=np.float32), 1.0)

    mean = WeightedMean.of(unit(1, 0), 1.0)
    with pytest.raises(ValueError, match="finite, nonzero length"):
        mean.add(-unit(1, 0), 1.0)
    assert mean.total.tolist() == [1.0, 0.0]
    assert mean.vector == pytest.approx(unit(1, 0))


def test_a_weight_is_positive_seconds_and_shapes_agree() -> None:
    for seconds in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError, match="positive seconds"):
            WeightedMean.of(unit(1, 0), seconds)
    with pytest.raises(ValueError, match="shape mismatch"):
        WeightedMean.of(unit(1, 0), 1.0).add(unit(1, 0, 0), 1.0)
