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
import os

from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig


def _create_openai_embedding(config: ProviderTaskConfig):
    try:
        from langchain_openai import OpenAIEmbeddings
    except Exception as e:
        raise ImportError(
            "OpenAI embedding provider requires langchain_openai. "
            "Please install it with: pip install langchain-openai"
        ) from e

    kwargs = dict(config.extra or {})
    # Explicitly, as the LLMs read theirs: unset, the client would fall back to OPENAI_API_KEY.
    env_name = kwargs.pop("api_key_env", "OPENAI_API_KEY")
    key = kwargs.pop("api_key", None) or os.getenv(env_name)
    if not key:
        raise RuntimeError(f"Environment variable {env_name!r} is required")

    return OpenAIEmbeddings(model=config.model, api_key=key, **kwargs)


def _create_google_embedding(config: ProviderTaskConfig):
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except Exception as e:
        raise ImportError(
            "Google embedding provider requires langchain_google_genai. "
            "Please install it with: pip install langchain-google-genai"
        ) from e

    kwargs = dict(config.extra or {})

    return GoogleGenerativeAIEmbeddings(model=config.model, **kwargs)


def create_embedding_model(config: ProviderTaskConfig):
    provider = config.provider.lower().strip()

    if provider == "openai":
        return _create_openai_embedding(config)

    if provider in {"google", "gemini", "google_genai"}:
        return _create_google_embedding(config)

    raise ValueError(f"Unsupported embedding provider: {config.provider}")
