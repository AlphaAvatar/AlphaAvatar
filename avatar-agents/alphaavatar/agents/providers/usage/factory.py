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
from alphaavatar.agents.providers.schema import ProviderUsage

from .anthropic import AnthropicUsageNormalizer
from .base import UsageNormalizer
from .google import GoogleUsageNormalizer
from .openai import OpenAIUsageNormalizer
from .openrouter import OpenRouterUsageNormalizer


def get_usage_normalizer(provider: str) -> UsageNormalizer:
    provider = provider.lower().strip()

    if provider == "openai":
        return OpenAIUsageNormalizer()

    if provider == "openrouter":
        return OpenRouterUsageNormalizer()

    if provider in {"google", "gemini", "google_genai"}:
        return GoogleUsageNormalizer()

    if provider in {"anthropic", "claude"}:
        return AnthropicUsageNormalizer()

    return OpenAIUsageNormalizer()


def normalize_usage(
    *,
    provider: str,
    raw_response=None,
    raw_usage: dict | None = None,
) -> ProviderUsage:
    normalizer = get_usage_normalizer(provider)

    return normalizer.normalize(
        raw_response=raw_response,
        raw_usage=raw_usage,
    )
