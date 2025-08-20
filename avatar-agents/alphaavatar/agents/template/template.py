from .prompts.avatar_system_prompts import AVATAR_SYSTEM_PROMPT


class AvatarPromptTemplate:
    """
    A class to represent the prompt template for the Avatar Agent.
    
    This class encapsulates the prompt template used by the Avatar Agent, allowing for easy
    configuration and management of the prompt structure.
    """

    def __init__(self,):
        ...

    @staticmethod
    def init_system_prompt(
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
    