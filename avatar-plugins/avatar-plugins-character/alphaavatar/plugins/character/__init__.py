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
import os

from alphaavatar.agents import AvatarModule, AvatarPlugin

from .log import logger
from .version import __version__

__all__ = [
    "__version__",
    "bootstrap_inference_runners",
]


class AiriCharacterPlugin(AvatarPlugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)  # type: ignore

    def download_files(self): ...

    def get_plugin(self, character_init_config: dict, *args, **kwargs):
        from .airi_avatar import AiriCharacterSession, AiriConfig

        try:
            avatar_config = AiriConfig(**character_init_config)
            return AiriCharacterSession(avatar_config=avatar_config)
        except Exception as e:
            raise ImportError(
                "The 'Airi' Character plugin is required but failed to initialize.\n"
                "To fix this, install the optional dependency: "
                "`pip install alphaavatar-plugins-character`\n"
                f"Original error: {e}"
            ) from e


def bootstrap_inference_runners() -> None:
    """
    Plugin-owned runner bootstrap.

    Called by AlphaAvatar core after AvatarConfig is parsed.
    """
    character_name = os.getenv("ALPHAAVATAR_CHARACTER_NAME", None)

    if not character_name:
        logger.info("Character runner bootstrap skipped: character plugin is disabled.")
        return

    if character_name == "airi":
        from .airi_avatar import AiriRunner

        AvatarPlugin.register_inference_runner_once(AiriRunner)
        return

    logger.warning(f"Unsupported ALPHAAVATAR_CHARACTER_NAME={character_name!r}")


# Plugin register
AvatarPlugin.register_avatar_plugin(
    AvatarModule.CHARACTER,
    "airi",
    AiriCharacterPlugin(),
)

# Runner bootstrap register
AvatarPlugin.register_inference_runner_bootstrap(
    "alphaavatar.plugins.character",
    bootstrap_inference_runners,
)
