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
from .cache import PersonaCache
from .identifier import IdentifierBase
from .profiler import ProfilerBase
from .recognizer import RecognizerBase


class PersonaBase:
    def __init__(
        self,
        *,
        profiler: ProfilerBase | None = None,
        identifier: IdentifierBase | None = None,
        recognizer: RecognizerBase | None = None,
        maximum_retrieval_times: int = 3,
    ):
        self._profiler = profiler
        self._identifier = identifier
        self._recognizer = recognizer

        self._maximum_retrieval_times = maximum_retrieval_times

        self._persona_cache: dict[str, PersonaCache] = {}

    def init_persona(self, user_id: str):
        """"""
        pass
