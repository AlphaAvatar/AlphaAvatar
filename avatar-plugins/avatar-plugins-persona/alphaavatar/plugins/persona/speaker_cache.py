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

from alphaavatar.agents.persona import ProfileItemSource, ProfileItemView, SpeakerCacheBase

from .profiler_details import UserProfileDetails


class SpeakerCache(SpeakerCacheBase):
    def __init__(self, *, alpha_age: float = 0.2, alpha_gender: float = 0.2):
        super().__init__()
        self._logits_age: np.ndarray | None = None  # shape [1,1]
        self._logits_gender: np.ndarray | None = None  # shape [1,3]
        self._alpha_age = float(alpha_age)
        self._alpha_gender = float(alpha_gender)
        self._gender_labels = ["female", "male", "child"]  # consistent with model output order

    @staticmethod
    def _ema(prev: np.ndarray | None, new: np.ndarray, alpha: float) -> np.ndarray:
        """
        Compute Exponential Moving Average (EMA).

        Args:
            prev (np.ndarray | None): Previous state. If None, returns the new observation directly.
            new (np.ndarray): New observation array.
            alpha (float): Smoothing factor between 0 and 1.

        Returns:
            np.ndarray: Updated EMA result.
        """
        if prev is None:
            return new.astype(np.float32, copy=True)
        return (1.0 - alpha) * prev.astype(np.float32) + alpha * new.astype(np.float32)

    @staticmethod
    def _softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
        """Numerically stable softmax function."""
        x_max = np.max(x, axis=axis, keepdims=True)
        e = np.exp(x - x_max)
        return e / np.sum(e, axis=axis, keepdims=True)

    @staticmethod
    def _age_to_range(age_years: int) -> str | None:
        """Map integer age to a coarse age bucket."""
        bins = [
            (0, 5),
            (6, 12),
            (13, 17),
            (18, 24),
            (25, 34),
            (35, 44),
            (45, 54),
            (55, 64),
            (65, 100),
        ]
        for lo, hi in bins:
            if lo <= age_years <= hi:
                return f"{lo}-{hi} years old"
        return None

    def update_profile_detail(
        self,
        profile_details: UserProfileDetails | None,
        speaker_attribute: dict[str, np.ndarray],
        timestamp: str,
    ) -> UserProfileDetails:
        """
        Update and smooth speaker attributes, and derive age range and gender.

        Args:
            profile_details (UserProfileDetails | None): Optional user profile object.
            speaker_attribute (dict): Contains the latest speaker model output:
                {
                    "hidden_states": np.ndarray [1, 1024],  # pooled transformer layer
                    "logits_age":    np.ndarray [1, 1],     # normalized 0–1 age score
                    "logits_gender": np.ndarray [1, 3],     # logits for [female, male, child]
                }

        Process:
            1. Apply Exponential Moving Average (EMA) to 'logits_age' and 'logits_gender'.
            2. Convert smoothed age logits (0–1) to approximate years (0–100),
               then map to a predefined age range.
            3. Convert smoothed gender logits to probabilities using softmax,
               and select the most probable label.
        """
        if profile_details is None:
            profile_details = UserProfileDetails(**{})

        # Retrieve current model outputs
        obs_age: np.ndarray | None = speaker_attribute.get("logits_age")
        obs_gender: np.ndarray | None = speaker_attribute.get("logits_gender")

        if obs_age is None or obs_gender is None:
            raise ValueError(
                "speaker_attribute must contain both 'logits_age' and 'logits_gender'."
            )

        # 1) Exponential moving average update
        self._logits_age = self._ema(self._logits_age, obs_age, self._alpha_age)
        self._logits_gender = self._ema(self._logits_gender, obs_gender, self._alpha_gender)

        # 2) Map smoothed age (0–1) to [0,100] years
        age_score = float(np.clip(self._logits_age.squeeze(), 0.0, 1.0))
        age_years = int(round(age_score * 100.0))
        age_range = self._age_to_range(age_years)
        if age_range is not None and (
            profile_details.age is None
            or (
                profile_details.age.source == ProfileItemSource.speech
                and profile_details.age != age_range
            )
        ):
            profile_details.age = ProfileItemView(
                value=age_range, source=ProfileItemSource.speech, timestamp=timestamp
            )

        # 3) Compute gender probabilities and select top label
        probs = self._softmax(self._logits_gender, axis=-1).squeeze()
        idx = int(np.argmax(probs))
        gender = self._gender_labels[idx]
        if profile_details.gender is None or profile_details.gender.value != gender:
            profile_details.gender = ProfileItemView(
                value=gender, source=ProfileItemSource.speech, timestamp=timestamp
            )

        return profile_details
