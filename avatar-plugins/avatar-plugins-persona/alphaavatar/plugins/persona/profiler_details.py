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

    All fields are plain types:
    - ProfileItemView
    - list[ProfileItemView]

    Field values can be natural language expressions, short phrases, or sentences.

    This schema is designed for a personal assistant:
    - user identity and communication
    - contact and availability
    - important people and relationships
    - work, projects, responsibilities
    - preferences, constraints, goals, and assistant behavior preferences
    """

    # Identification & Demographics
    name: ProfileItemView | None = Field(
        None,
        description=(
            "Preferred name or nickname, written naturally "
            "(e.g., 'Lily', 'Mike Zhang', 'call me Jay')."
        ),
    )
    gender: ProfileItemView | None = Field(
        None,
        description=(
            "Gender identity as expressed by the user. Can be a word or phrase "
            "(e.g., 'male', 'female', 'non-binary', 'prefer not to say', "
            "'other: transgender woman'). Do NOT infer."
        ),
    )
    age: ProfileItemView | None = Field(
        None,
        description=(
            "Age or approximate age range only when explicitly stated or strongly implied. "
            "Use natural wording (e.g., '27 years old', 'around 35-45 years old'). "
            "Do NOT infer from appearance, voice, or unsupported context."
        ),
    )
    locale: ProfileItemView | None = Field(
        None,
        description=(
            "Preferred language/locale code or description "
            "(e.g., 'zh-CN', 'English (US)', 'Mandarin Chinese')."
        ),
    )
    languages: list[ProfileItemView] | None = Field(
        None,
        description=(
            "Languages with optional proficiency or preference notes, written as natural text "
            "(e.g., 'English: native, prefer for work', "
            "'Chinese: fluent, okay for casual chats')."
        ),
    )

    # Contact & Communication
    emails: list[ProfileItemView] | None = Field(
        None,
        description=(
            "Email addresses explicitly provided by the user or obtained from a trusted "
            "user-authorized source. Can include optional context such as personal, work, "
            "backup, or preferred contact email "
            "(e.g., 'lily@example.com, personal email', 'mike@company.com, work email'). "
            "Do NOT infer or invent email addresses."
        ),
    )
    phone_numbers: list[ProfileItemView] | None = Field(
        None,
        description=(
            "Phone numbers explicitly provided by the user or obtained from a trusted "
            "user-authorized source. Can include optional context such as mobile, work, "
            "WhatsApp, emergency, or preferred contact number "
            "(e.g., '+1 415 123 4567, mobile', '+86 138 0000 0000, WhatsApp'). "
            "Do NOT infer or invent phone numbers."
        ),
    )
    preferred_contact_methods: list[ProfileItemView] | None = Field(
        None,
        description=(
            "Preferred contact methods and usage context, explicitly stated by the user "
            "(e.g., 'prefers email for work updates', 'WhatsApp for urgent matters', "
            "'do not call unless urgent', 'text me before calling'). Do NOT infer."
        ),
    )
    communication: ProfileItemView | None = Field(
        None,
        description=(
            "Preferred communication style described naturally "
            "(e.g., 'Friendly and casual, okay with emojis', "
            "'formal and concise', 'detailed explanations preferred')."
        ),
    )
    assistant_preferences: list[ProfileItemView] | None = Field(
        None,
        description=(
            "How the user wants the assistant to help, including preferred level of initiative, "
            "detail, reminders, autonomy, and follow-up style "
            "(e.g., 'prefers step-by-step code changes', 'wants direct answers first', "
            "'likes proactive suggestions after implementation', "
            "'does not want repeated confirmations')."
        ),
    )

    # Location & Availability
    home_location: ProfileItemView | None = Field(
        None,
        description=(
            "Primary/home location as natural text "
            "(e.g., 'Shanghai, China, lives in Pudong District, timezone Asia/Shanghai'). "
            "Do NOT infer exact address."
        ),
    )
    current_location: ProfileItemView | None = Field(
        None,
        description=(
            "Current or temporary location, can include city/country/timezone "
            "(e.g., 'Currently in San Francisco for work, timezone America/Los_Angeles'). "
            "Do NOT infer exact location unless explicitly stated."
        ),
    )
    availability: ProfileItemView | None = Field(
        None,
        description=(
            "User availability, working hours, preferred meeting times, timezone habits, "
            "and do-not-disturb rules "
            "(e.g., 'usually works 9am-6pm weekdays', "
            "'do not schedule calls before 10am', 'weekends are family time')."
        ),
    )

    # People & Relationships
    family: ProfileItemView | None = Field(
        None,
        description=(
            "Family or household situation, described naturally "
            "(e.g., 'Married, 2 kids aged 5 and 8', "
            "'lives with partner and parents, household size 5'). "
            "Only record what the user explicitly states or clearly authorizes."
        ),
    )
    important_people: list[ProfileItemView] | None = Field(
        None,
        description=(
            "Important people related to the user, such as family members, close friends, "
            "colleagues, assistants, managers, collaborators, doctors, teachers, or service providers. "
            "Include relationship and useful context when stated "
            "(e.g., 'Alice is my wife', 'David is my manager at work', "
            "'Tom helps me with car maintenance'). Do NOT infer relationships."
        ),
    )

    # Education & Work
    education_level: ProfileItemView | None = Field(
        None,
        description=(
            "Highest education level in natural words "
            "(e.g., 'bachelor’s degree', 'completed high school', 'PhD in Physics')."
        ),
    )
    education: ProfileItemView | None = Field(
        None,
        description=(
            "Detailed education info, free-form "
            "(e.g., 'Graduated from MIT in 2020 with a BSc in Computer Science')."
        ),
    )
    employment: ProfileItemView | None = Field(
        None,
        description=(
            "Occupation details as natural text "
            "(e.g., 'Senior Software Engineer at Google in the tech industry', "
            "'part-time barista while studying')."
        ),
    )
    responsibilities: list[ProfileItemView] | None = Field(
        None,
        description=(
            "Recurring responsibilities, roles, or areas the user is responsible for "
            "(e.g., 'manages AlphaAvatar development', 'responsible for weekly team reports', "
            "'tracks family travel plans', 'maintains personal investment notes')."
        ),
    )
    projects: list[ProfileItemView] | None = Field(
        None,
        description=(
            "Active or long-term projects the user is working on, with short context when available "
            "(e.g., 'AlphaAvatar open-source assistant framework', "
            "'personal website redesign', 'preparing a research paper')."
        ),
    )

    # Personality & Decision Style
    personality: ProfileItemView | None = Field(
        None,
        description=(
            "Personality description, free-form. Can include traits, scores, or phrases "
            "(e.g., 'Openness: high, enjoys trying new things', "
            "'introverted but friendly', 'empathetic and decisive')."
        ),
    )
    decision_preferences: ProfileItemView | None = Field(
        None,
        description=(
            "How the user prefers decisions, recommendations, and tradeoffs to be presented "
            "(e.g., 'prefers concise rankings', 'wants pros and cons before recommendations', "
            "'cares most about long-term value', 'prefers practical implementation advice')."
        ),
    )

    # Preferences, Constraints & Context
    preferences: list[ProfileItemView] | None = Field(
        None,
        description=(
            "Likes, dislikes, favorite or avoided brands, sensitivities, and general preferences, "
            "described freely "
            "(e.g., 'Loves sci-fi movies', 'dislikes horror', "
            "'prefers Apple products', 'avoid political topics')."
        ),
    )
    health_diet: ProfileItemView | None = Field(
        None,
        description=(
            "Dietary patterns, allergies, accessibility needs, or health-related preferences "
            "only when explicitly provided by the user "
            "(e.g., 'Vegetarian', 'lactose intolerant', 'needs wheelchair access'). "
            "Do NOT infer medical conditions."
        ),
    )
    constraints: list[ProfileItemView] | None = Field(
        None,
        description=(
            "Other constraints as natural phrases "
            "(e.g., 'cannot work weekends', 'no alcohol due to health reasons', "
            "'limited budget for this project')."
        ),
    )
    goals: ProfileItemView | None = Field(
        None,
        description=(
            "Short- and long-term goals, free-form "
            "(e.g., 'Short-term: learn Python, Long-term: transition into data science')."
        ),
    )
    privacy: ProfileItemView | None = Field(
        None,
        description=(
            "Privacy and personalization preferences, natural text "
            "(e.g., 'Prefer minimal data sharing but okay with personalization', "
            "'do not store sensitive information unless explicitly requested')."
        ),
    )
    resources: list[ProfileItemView] | None = Field(
        None,
        description=(
            "User-owned or user-managed resources useful for assistance, such as domains, "
            "servers, repositories, devices, vehicles, tools, or workspaces "
            "(e.g., 'owns alphaavatar.ai', 'uses a Mac mini for local testing', "
            "'maintains the AlphaAvatar GitHub repo'). "
            "Do NOT include secrets, passwords, API keys, private tokens, or credentials."
        ),
    )

    # Misc
    notes: ProfileItemView | None = Field(
        None,
        description=(
            "Additional context or free-form notes that do not fit other fields "
            "(e.g., 'Currently traveling, so responses might be delayed')."
        ),
    )
