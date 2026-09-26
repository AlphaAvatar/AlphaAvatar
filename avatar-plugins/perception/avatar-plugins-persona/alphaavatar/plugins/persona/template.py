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

from datetime import datetime
from typing import Any

from alphaavatar.agents.persona.schemas import UserProfile, UserRuntimeState
from alphaavatar.agents.utils.time import format_datetime_for_timezone
from alphaavatar.core.turn import TurnSnapshot


class PersonaPluginsTemplate:
    @staticmethod
    def _render_profile_updated_at(value: Any, timezone: str | None) -> str:
        if not isinstance(value, datetime):
            return str(value or "")
        return format_datetime_for_timezone(value, timezone)

    @staticmethod
    def _render_flat_model(
        data: dict[str, Any],
        *,
        timezone: str | None = None,
        list_sep: str = ", ",
        sort_keys: bool = True,
        skip_empty: bool = True,
    ) -> list[str]:
        lines: list[str] = []
        for attr in sorted(data) if sort_keys else data:
            value = data[attr]
            if value is None:
                continue
            if isinstance(value, list):
                values = [
                    (
                        f"{item.get('value', '')} "
                        f"(updated at {PersonaPluginsTemplate._render_profile_updated_at(item.get('updated_at'), timezone)}) "
                        f"| source from: {item.get('source', '')}"
                    )
                    for item in value
                    if isinstance(item, dict)
                ]
                if values:
                    lines.append(f"- {attr}: {list_sep.join(values)}")
            elif isinstance(value, dict):
                rendered = value.get("value", "")
                if skip_empty and (rendered is None or str(rendered).strip() == ""):
                    continue
                lines.append(
                    f"- {attr}: {rendered} "
                    f"(updated at {PersonaPluginsTemplate._render_profile_updated_at(value.get('updated_at'), timezone)}) | "
                    f"source from: {value.get('source', '')}"
                )
            elif not skip_empty or str(value).strip():
                lines.append(f"- {attr}: {value}")
        return lines

    @classmethod
    def _render_runtime_state(
        cls,
        state: UserRuntimeState,
    ) -> list[str]:
        data = state.model_dump()

        current_login_at = data.pop("current_login_at", None)
        last_login_at = data.pop("last_login_at", None)

        lines = cls._render_flat_model(data)

        if current_login_at is not None:
            lines.append(
                "- current_login_at: "
                + format_datetime_for_timezone(
                    current_login_at,
                    state.current_timezone,
                )
            )

        if last_login_at is not None:
            lines.append(
                "- last_login_at: "
                + format_datetime_for_timezone(
                    last_login_at,
                    state.last_timezone,
                )
            )

        return lines

    @classmethod
    def apply_update_template(cls, turns: list[TurnSnapshot]) -> str:
        return "\n\n".join(
            f"### user:\n{turn.text}" for turn in turns if turn.text and turn.text.strip()
        )

    @classmethod
    def apply_provider_template(
        cls,
        user_profiles: dict[str, UserProfile],
        *,
        list_sep: str = ", ",
        sort_keys: bool = True,
        skip_empty: bool = True,
    ) -> str:
        blocks: list[str] = []
        for uid, profile in user_profiles.items():
            sections: list[str] = []
            timezone = (
                profile.runtime_state.current_timezone
                if profile and profile.runtime_state
                else None
            )

            if profile and profile.runtime_state:
                lines = cls._render_runtime_state(profile.runtime_state)
                if lines:
                    sections.append(
                        "### Runtime state\n"
                        "System-observed login/session state. Use subtly; do not mention unless helpful.\n"
                        + "\n".join(lines)
                    )

            if profile and profile.details:
                lines = cls._render_flat_model(
                    profile.details.model_dump(),
                    timezone=timezone,
                    list_sep=list_sep,
                    sort_keys=sort_keys,
                    skip_empty=skip_empty,
                )
                if lines:
                    sections.append("### User profile details\n" + "\n".join(lines))

            if sections:
                blocks.append(f"## User {uid}\n" + "\n\n".join(sections))

        return "\n\n".join(blocks)
