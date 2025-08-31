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
    ): ...

    @staticmethod
    def instructions(
        *,
        avatar_introduction: str,
        memory_content: str = DEFAULT_SYSTEM_VALUE,
        user_persona: str = DEFAULT_SYSTEM_VALUE,
        current_time: str = DEFAULT_SYSTEM_VALUE,
    ) -> str:
        """Initialize the system prompt for the Avatar Agent.

        Args:
            avatar_introduction (str): _description_

        Returns:
            str: _description_
        """
        return AVATAR_SYSTEM_PROMPT.format(
            avatar_introduction=avatar_introduction,
            memory_content=memory_content,
            user_persona=user_persona,
            current_time=current_time,
        )
