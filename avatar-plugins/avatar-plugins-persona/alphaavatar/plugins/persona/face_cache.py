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
import numpy as np

from alphaavatar.agents.persona import FaceCacheBase, ProfileItemSource, ProfileItemView

from .profiler_details import UserProfileDetails


class FaceCache(FaceCacheBase):
    def __init__(self, *, alpha_age: float = 0.2, alpha_gender: float = 0.2):
        super().__init__()
        self._age: float | None = None
        self._gender_probs: dict[str, float] = {}
        self._alpha_age = float(alpha_age)
        self._alpha_gender = float(alpha_gender)

    @staticmethod
    def _age_to_range(age_years: int) -> str | None:
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

    @staticmethod
    def _normalize_gender(gender: str | int | None) -> str | None:
        if gender is None:
            return None

        if isinstance(gender, int):
            return "male" if gender == 1 else "female"

        value = str(gender).lower().strip()
        if not value:
            return None

        mapping = {
            "m": "male",
            "male": "male",
            "man": "male",
            "1": "male",
            "f": "female",
            "female": "female",
            "woman": "female",
            "0": "female",
        }

        return mapping.get(value)

    def _update_age(self, age: int) -> int:
        age = int(np.clip(age, 0, 100))
        if self._age is None:
            self._age = float(age)
        else:
            self._age = (1.0 - self._alpha_age) * self._age + self._alpha_age * float(age)
        return int(round(self._age))

    def _update_gender(self, gender: str) -> str:
        gender = gender.lower().strip()
        if not gender:
            return gender

        for key in list(self._gender_probs.keys()):
            self._gender_probs[key] *= 1.0 - self._alpha_gender

        self._gender_probs[gender] = self._gender_probs.get(gender, 0.0) + self._alpha_gender

        return max(self._gender_probs.items(), key=lambda x: x[1])[0]

    def update_profile_detail(
        self,
        profile_details: UserProfileDetails | None,
        face_attribute: dict,
        timestamp: str,
    ) -> UserProfileDetails:
        if profile_details is None:
            profile_details = UserProfileDetails(**{})

        age = face_attribute.get("age")
        gender = face_attribute.get("gender")

        if age is not None:
            age_years = self._update_age(int(age))
            age_range = self._age_to_range(age_years)

            if age_range is not None and (
                profile_details.age is None
                or profile_details.age.source in {ProfileItemSource.face, ProfileItemSource.speech}
            ):
                profile_details.age = ProfileItemView(
                    value=age_range,
                    source=ProfileItemSource.face,
                    timestamp=timestamp,
                )

        if gender is not None:
            normalized_gender = self._normalize_gender(gender)

            if normalized_gender is not None:
                gender_value = self._update_gender(normalized_gender)

                if profile_details.gender is None or profile_details.gender.source in {
                    ProfileItemSource.face,
                    ProfileItemSource.speech,
                }:
                    profile_details.gender = ProfileItemView(
                        value=gender_value,
                        source=ProfileItemSource.face,
                        timestamp=timestamp,
                    )

        return profile_details
