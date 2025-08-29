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
from alphaavatar.agents.memory import MemoryType

from .prompts.avatar_memory_prompts import (
    MEMORY_CONVERSATION_RETRIEVAL_PROMPT,
    MEMORY_TOOLS_RETRIEVAL_PROMPT,
)
from .prompts.avatar_system_prompts import AVATAR_SYSTEM_PROMPT


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
    def init_instructions(
        *,
        avatar_introduction: str,
    ) -> str:
        """Initialize the system prompt for the Avatar Agent.

        Args:
            avatar_introduction (str): _description_

        Returns:
            str: _description_
        """
        return AVATAR_SYSTEM_PROMPT.format(
            avatar_introduction=avatar_introduction,
            memory_content="{memory_content}",
            user_profile="{user_profile}",
        )

    @staticmethod
    def get_memory_retrieval_prompt(
        *,
        memory_type: MemoryType,
    ) -> str:
        """Initialize the system prompt for the Avatar Agent.

        Args:
            avatar_introduction (str): _description_

        Returns:
            str: _description_
        """
        if memory_type == MemoryType.CONVERSATION:
            return MEMORY_CONVERSATION_RETRIEVAL_PROMPT
        elif memory_type == MemoryType.TOOLS:
            return MEMORY_TOOLS_RETRIEVAL_PROMPT
        else:
            raise NotImplementedError
