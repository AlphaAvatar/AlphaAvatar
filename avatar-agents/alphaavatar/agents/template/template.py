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
from .prompts.avatar_system_prompts import AVATAR_SYSTEM_PROMPT

DEFAULT_SYSTEM_VALUE = "NONE"


class AvatarPromptTemplate:
    """
    A class to represent the prompt template for the Avatar Agent.

    This class encapsulates the prompt template used by the Avatar Agent, allowing for easy
    configuration and management of the prompt structure.
    """

    def __init__(
        self,
        # Instruction
        avatar_introduction: str,
        *,
        memory_content: str = DEFAULT_SYSTEM_VALUE,
        user_persona: str = DEFAULT_SYSTEM_VALUE,
        current_time: str = DEFAULT_SYSTEM_VALUE,
    ):
        # Instruction
        self._avatar_introduction = avatar_introduction
        self._memory_content = memory_content
        self._user_persona = user_persona
        self._current_time = current_time

    def instructions(
        self,
        *,
        avatar_introduction: str | None = None,
        memory_content: str | None = None,
        user_persona: str | None = None,
        current_time: str | None = None,
    ) -> str:
        """Initialize the system prompt for the Avatar Agent.

        Args:
            avatar_introduction (str): _description_

        Returns:
            str: _description_
        """
        if avatar_introduction:
            self._avatar_introduction = avatar_introduction

        if memory_content:
            self._memory_content = memory_content

        if user_persona:
            self._user_persona = user_persona

        if current_time:
            self._current_time = current_time

        return AVATAR_SYSTEM_PROMPT.format(
            avatar_introduction=self._avatar_introduction,
            memory_content=self._memory_content,
            user_persona=self._user_persona,
            current_time=self._current_time,
        )
