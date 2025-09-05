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
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Gender(str, Enum):
    male = "male"
    female = "female"
    non_binary = "non-binary"
    prefer_not_say = "prefer_not_say"
    other = "other"


class AgeRange(str, Enum):
    _0_12 = "0-12"
    _13_17 = "13-17"
    _18_24 = "18-24"
    _25_34 = "25-34"
    _35_44 = "35-44"
    _45_54 = "45-54"
    _55_64 = "55-64"
    _65_plus = "65+"


class EducationLevel(str, Enum):
    none = "none"
    high_school = "high_school"
    associate = "associate"
    bachelor = "bachelor"
    master = "master"
    doctorate = "doctorate"
    other = "other"


class MaritalStatus(str, Enum):
    single = "single"
    in_relationship = "in_relationship"
    married = "married"
    divorced = "divorced"
    widowed = "widowed"
    prefer_not_say = "prefer_not_say"
    other = "other"


class LivingSituation(str, Enum):
    alone = "alone"
    with_partner = "with_partner"
    with_family = "with_family"
    with_children = "with_children"
    with_roommates = "with_roommates"
    campus_dorm = "campus_dorm"
    other = "other"


class LanguagePref(BaseModel):
    language: str = Field(..., description="IETF BCP 47 code (e.g., 'zh-CN', 'en-US').")
    proficiency: Literal["native", "fluent", "intermediate", "basic"] | None = Field(
        None, description="Self-reported proficiency."
    )
    preferred: bool | None = Field(None, description="If true, prefer this language for responses.")


class Location(BaseModel):
    country: str | None = Field(None, description="Country name or ISO-3166 alpha-2 code.")
    region: str | None = Field(None, description="State/Province/Region name.")
    city: str | None = Field(None, description="City name.")
    timezone: str | None = Field(None, description="IANA TZ (e.g., 'Asia/Shanghai').")
    is_traveling: bool | None = Field(None, description="Temporarily away from home location.")


class Employment(BaseModel):
    job_title: str | None = Field(None, description="Current role or occupation.")
    industry: str | None = Field(None, description="Industry sector (e.g., 'finance', 'tech').")
    seniority: (
        Literal[
            "intern", "junior", "mid", "senior", "lead", "manager", "director", "vp", "cxo", "owner"
        ]
        | None
    ) = Field(None, description="Career seniority if stated.")
    employer: str | None = Field(None, description="Company or organization.")


class EducationDetails(BaseModel):
    """
    Rich education block so we can capture field(s) of study without breaking existing 'education_level'.
    """

    degree_names: list[str] = Field(
        default_factory=list, description="Degree names (e.g., 'BSc', 'MEng', 'PhD')."
    )
    fields_of_study: list[str] = Field(
        default_factory=list,
        description="Academic majors/disciplines (e.g., 'Computer Science', 'Economics').",
    )
    institution: str | None = Field(None, description="Institution or university name, if stated.")
    graduation_year: int | None = Field(None, description="Graduation year if explicitly stated.")
    current_program: str | None = Field(
        None, description="If currently enrolled, program name (e.g., 'MSc in Data Science')."
    )


class CommunicationStyle(BaseModel):
    tone: (
        list[Literal["formal", "neutral", "friendly", "playful", "direct", "empathetic"]] | None
    ) = Field(default_factory=list, description="Preferred tone(s) for responses.")
    formality: Literal["low", "medium", "high"] | None = Field(
        None, description="Desired level of formality."
    )
    detail_level: Literal["summary", "balanced", "detailed"] | None = Field(
        None, description="Preferred detail level."
    )
    emoji_ok: bool | None = Field(None, description="Comfort with emojis or casual markers.")
    response_length: Literal["short", "medium", "long"] | None = Field(
        None, description="Preferred response length."
    )


class Personality(BaseModel):
    openness: float | None = Field(
        None, ge=0, le=1, description="0–1; openness to new experiences."
    )
    conscientiousness: float | None = Field(
        None, ge=0, le=1, description="0–1; organization/self-discipline."
    )
    extraversion: float | None = Field(
        None, ge=0, le=1, description="0–1; sociability/assertiveness."
    )
    agreeableness: float | None = Field(
        None, ge=0, le=1, description="0–1; cooperativeness/empathy."
    )
    neuroticism: float | None = Field(
        None, ge=0, le=1, description="0–1; emotional volatility (lower is calmer)."
    )
    traits: list[str] = Field(
        default_factory=list,
        description="Key adjectives stated or strongly implied (e.g., 'risk-averse', 'decisive').",
    )


class HealthDiet(BaseModel):
    dietary: list[str] = Field(
        default_factory=list, description="Diet patterns/restrictions (e.g., vegetarian, halal)."
    )
    allergies: list[str] = Field(default_factory=list, description="Food/substance allergies.")
    accessibility_needs: list[str] = Field(
        default_factory=list, description="Accessibility needs (e.g., wheelchair access)."
    )


class Preferences(BaseModel):
    interests: list[str] = Field(
        default_factory=list, description="Likes (topics, genres, activities, categories)."
    )
    dislikes: list[str] = Field(
        default_factory=list, description="Avoid list (topics, genres, items)."
    )
    brands: list[str] = Field(
        default_factory=list,
        description="Favorite or avoided brands (prefix with '-' to mark avoidance).",
    )
    content_sensitivities: list[str] = Field(
        default_factory=list, description="Topics to handle carefully (e.g., horror)."
    )


class Goals(BaseModel):
    short_term: list[str] = Field(default_factory=list, description="Goals within ~3 months.")
    long_term: list[str] = Field(default_factory=list, description="Goals beyond ~3 months.")


class TimePreferences(BaseModel):
    working_hours: str | None = Field(
        None, description="Typical availability window (e.g., '09:30-18:30')."
    )
    weekend_ok: bool | None = Field(None, description="Whether weekend contact is acceptable.")


class PrivacyPrefs(BaseModel):
    data_sharing: Literal["minimal", "standard", "broad"] | None = Field(
        None, description="Acceptable level of personal data sharing."
    )
    pii_redaction: bool | None = Field(None, description="Prefer PII to be redacted in outputs.")
    personalization: Literal["off", "light", "full"] | None = Field(
        None, description="Desired personalization level."
    )


class FamilyStatus(BaseModel):
    """
    Family/household context for better personalization and scheduling.
    Only populate when the user explicitly states the info.
    """

    marital_status: MaritalStatus | None = Field(
        None, description="Marital/relationship status if explicitly stated."
    )
    living_situation: LivingSituation | None = Field(
        None, description="Current living arrangement (e.g., with family, alone)."
    )
    household_size: int | None = Field(
        None, description="Total number of people living in the household (including user)."
    )
    children_count: int | None = Field(None, description="Number of children if stated.")
    children_ages: list[str] = Field(
        default_factory=list,
        description="Children ages or age ranges (e.g., '0-3', '4-6', 'teen').",
    )
    caregiving_responsibilities: list[str] = Field(
        default_factory=list, description="Care duties (e.g., eldercare, infant care)."
    )
    household_income_range: str | None = Field(
        None, description="Optional income band if explicitly provided by the user."
    )


class UserProfile(BaseModel):
    # Identification & Demographics
    name: str | None = Field(None, description="Preferred name or nickname.")
    gender: Gender | None = Field(None, description="Gender identity if explicitly stated.")
    age: int | None = Field(None, description="Approximate age in years if explicitly stated.")
    age_range: AgeRange | None = Field(
        None, description="Age bracket if only a rough range is given."
    )
    locale: str | None = Field(
        None, description="Preferred language/locale code (e.g., 'zh-CN', 'en-US')."
    )
    languages: list[LanguagePref] = Field(
        default_factory=list, description="Languages and preferences."
    )
    home_location: Location | None = Field(None, description="Primary/home location.")
    current_location: Location | None = Field(None, description="Current or temporary location.")

    # Education & Work
    education_level: EducationLevel | None = Field(
        None, description="Highest education level if mentioned."
    )
    education: EducationDetails | None = Field(
        None, description="Detailed education info, including fields of study."
    )
    employment: Employment | None = Field(
        None, description="Occupation details including industry and seniority."
    )

    # Personality & Communication
    personality: Personality | None = Field(
        None, description="Personality signals (Big Five + key traits)."
    )
    communication: CommunicationStyle | None = Field(
        None, description="How the user prefers to communicate."
    )

    # Preferences, Constraints & Context
    preferences: Preferences | None = Field(
        None, description="Likes, dislikes, brands, sensitivities."
    )
    health_diet: HealthDiet | None = Field(None, description="Diet/allergies/accessibility.")
    family: FamilyStatus | None = Field(None, description="Family and household context.")
    constraints: list[str] = Field(
        default_factory=list, description="Other hard constraints (time/legal/policy/ethical)."
    )
    goals: Goals | None = Field(None, description="Short- and long-term goals.")
    time_prefs: TimePreferences | None = Field(
        None, description="Availability and scheduling preferences."
    )
    privacy: PrivacyPrefs | None = Field(
        None, description="Privacy and personalization preferences."
    )

    # Misc
    notes: str | None = Field(
        None, description="Additional context that does not fit other fields."
    )
