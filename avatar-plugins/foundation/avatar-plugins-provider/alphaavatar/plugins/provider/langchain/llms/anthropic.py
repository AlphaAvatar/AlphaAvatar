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
from functools import cached_property
from typing import Any

import anthropic
from langchain_anthropic import ChatAnthropic
from pydantic import Field


class OwnedChatAnthropic(ChatAnthropic):
    """Avoid LangChain's process-cached transports; the wrapper owns both supplied clients."""

    provider_http_client: Any = Field(exclude=True)
    provider_http_async_client: Any = Field(exclude=True)

    @cached_property
    def _client(self) -> anthropic.Client:
        return anthropic.Client(**self._client_params, http_client=self.provider_http_client)

    @cached_property
    def _async_client(self) -> anthropic.AsyncClient:
        return anthropic.AsyncClient(
            **self._client_params, http_client=self.provider_http_async_client
        )
