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

from typing import TYPE_CHECKING, Any

from livekit.agents.llm import ChatItem, ChatMessage

if TYPE_CHECKING:
    from .schema.user_profile import UserProfile


class PersonaPluginsTemplate:
    @staticmethod
    def _render_flat_model(
        data: dict[str, Any],
        *,
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
                    f"{item.get('value', '')} (updated at {item.get('timestamp', '')}) | source from: {item.get('source', '')}"
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
                    f"- {attr}: {rendered} (updated at {value.get('timestamp', '')}) | "
                    f"source from: {value.get('source', '')}"
                )
            elif not skip_empty or str(value).strip():
                lines.append(f"- {attr}: {value}")
        return lines

    @classmethod
    def apply_update_template(cls, chat_context: list[ChatItem]) -> str:
        return "\n\n".join(
            f"### {item.role}:\n{item.text_content or ''}"
            for item in chat_context
            if isinstance(item, ChatMessage) and item.role in {"user", "assistant"}
        )

    @classmethod
    def apply_system_template(
        cls,
        user_profiles: list[UserProfile],
        *,
        list_sep: str = ", ",
        sort_keys: bool = True,
        skip_empty: bool = True,
    ) -> str:
        blocks: list[str] = []
        for profile in user_profiles:
            sections: list[str] = []
            if profile and profile.runtime_state:
                lines = cls._render_flat_model(
                    profile.runtime_state.model_dump(),
                    list_sep=list_sep,
                    sort_keys=sort_keys,
                    skip_empty=skip_empty,
                )
                if lines:
                    sections.append(
                        "### Runtime state\n"
                        "System-observed login/session state. Use subtly; do not mention unless helpful.\n"
                        + "\n".join(lines)
                    )

            if profile and profile.details:
                lines = cls._render_flat_model(
                    profile.details.model_dump(),
                    list_sep=list_sep,
                    sort_keys=sort_keys,
                    skip_empty=skip_empty,
                )
                if lines:
                    sections.append("### User profile details\n" + "\n".join(lines))

            if sections:
                blocks.append("\n\n".join(sections))

        if len(blocks) <= 1:
            return blocks[0] if blocks else ""

        return "\n\n".join(f"User {index}\n{block}" for index, block in enumerate(blocks))
