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
from pydantic import Field

from alphaavatar.agents.persona import DetailsBase, ProfileItemView


class UserProfileDetails(DetailsBase):
    """
    Fully flattened user profile model.
    All fields are plain types (ProfileItemView, list[ProfileItemView]).
    Field values can be natural language expressions, short phrases, or sentences.
    """

    # Identification & Demographics
    name: ProfileItemView | None = Field(
        None,
        description="Preferred name or nickname, written naturally "
        "(e.g., 'Lily', 'Mike Zhang', 'call me Jay').",
    )
    gender: ProfileItemView | None = Field(
        None,
        description="Gender identity as expressed by the user. Can be a word or phrase "
        "(e.g., 'male', 'female', 'non-binary', 'prefer not to say', 'other: transgender woman').",
    )
    age: ProfileItemView | None = Field(
        None,
        description="If you are specifically asking, please provide an approximate age (e.g., 27 years old), "
        "otherwise, an approximate age range (e.g., 35-45 years old) is acceptable.",
    )
    locale: ProfileItemView | None = Field(
        None,
        description="Preferred language/locale code or description "
        "(e.g., 'zh-CN', 'English (US)', 'Mandarin Chinese').",
    )

    languages: list[ProfileItemView] | None = Field(
        None,
        description="Languages with optional proficiency or preference notes, "
        "written as natural text (e.g., 'English: native, prefer for work', "
        "'Chinese: fluent, okay for casual chats').",
    )

    home_location: ProfileItemView | None = Field(
        None,
        description="Primary/home location as natural text "
        "(e.g., 'Shanghai, China, lives in Pudong District, timezone Asia/Shanghai').",
    )
    current_location: ProfileItemView | None = Field(
        None,
        description="Current or temporary location, can include city/country/timezone "
        "(e.g., 'Currently in San Francisco for work, timezone PST').",
    )

    # Education & Work
    education_level: ProfileItemView | None = Field(
        None,
        description="Highest education level in natural words "
        "(e.g., 'bachelor’s degree', 'completed high school', 'PhD in Physics').",
    )
    education: ProfileItemView | None = Field(
        None,
        description="Detailed education info, free-form "
        "(e.g., 'Graduated from MIT in 2020 with a BSc in Computer Science').",
    )
    employment: ProfileItemView | None = Field(
        None,
        description="Occupation details as natural text "
        "(e.g., 'Senior Software Engineer at Google in the tech industry', "
        "'part-time barista while studying').",
    )

    # Personality & Communication
    personality: ProfileItemView | None = Field(
        None,
        description="Personality description, free-form. Can include traits, scores, or phrases "
        "(e.g., 'Openness: high, enjoys trying new things', "
        "'introverted but friendly', 'empathetic and decisive').",
    )
    communication: ProfileItemView | None = Field(
        None,
        description="Preferred communication style described naturally "
        "(e.g., 'Friendly and casual, okay with emojis', "
        "'formal and concise', 'detailed explanations preferred').",
    )

    # Preferences, Constraints & Context
    preferences: list[ProfileItemView] | None = Field(
        None,
        description="Likes, dislikes, favorite or avoided brands, sensitivities, described freely "
        "(e.g., 'Loves sci-fi movies, dislikes horror, prefers Apple products, avoid political topics').",
    )
    health_diet: ProfileItemView | None = Field(
        None,
        description="Dietary patterns, allergies, accessibility needs, free-form "
        "(e.g., 'Vegetarian, lactose intolerant, needs wheelchair access').",
    )
    family: ProfileItemView | None = Field(
        None,
        description="Family or household situation, described naturally "
        "(e.g., 'Married, 2 kids aged 5 and 8, lives with partner and parents, household size 5').",
    )
    constraints: list[ProfileItemView] | None = Field(
        None,
        description="Other constraints as natural phrases "
        "(e.g., 'cannot work weekends', 'no alcohol due to health reasons').",
    )
    goals: ProfileItemView | None = Field(
        None,
        description="Short- and long-term goals, free-form "
        "(e.g., 'Short-term: learn Python, Long-term: transition into data science').",
    )
    time_prefs: ProfileItemView | None = Field(
        None,
        description="Availability and scheduling preferences "
        "(e.g., 'Available 9am–6pm weekdays, weekends are family time').",
    )
    privacy: ProfileItemView | None = Field(
        None,
        description="Privacy and personalization preferences, natural text "
        "(e.g., 'Prefer minimal data sharing but okay with personalization').",
    )

    # Misc
    notes: ProfileItemView | None = Field(
        None,
        description="Additional context or free-form notes that do not fit other fields "
        "(e.g., 'Currently traveling, so responses might be delayed').",
    )
