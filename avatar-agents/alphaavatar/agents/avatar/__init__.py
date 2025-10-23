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
from .context.template import MemoryPluginsTemplate, PersonaPluginsTemplate
from .engine import AvatarEngine

__all__ = ["MemoryPluginsTemplate", "PersonaPluginsTemplate", "AvatarEngine"]


# if AvatarEngine.lookup_conversation_memory.__doc__:
#     AvatarEngine.lookup_conversation_memory.__doc__ = (
#         AvatarEngine.lookup_conversation_memory.__doc__.format(
#             memory_prompt=AvatarPromptTemplate.get_memory_retrieval_prompt(
#                 memory_type=MemoryType.CONVERSATION
#             )
#         )
#     )


# if AvatarEngine.lookup_tools_memory.__doc__:
#     AvatarEngine.lookup_tools_memory.__doc__ = AvatarEngine.lookup_tools_memory.__doc__.format(
#         memory_prompt=AvatarPromptTemplate.get_memory_retrieval_prompt(memory_type=MemoryType.TOOLS)
#     )
