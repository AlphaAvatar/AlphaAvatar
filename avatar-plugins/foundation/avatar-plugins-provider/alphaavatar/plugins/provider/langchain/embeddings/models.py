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
from alphaavatar.agents.utils import credential


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
    key = kwargs.pop("api_key", None) or credential(env_name)
    if not key:
        raise RuntimeError(f"Environment variable {env_name!r} is required")

    return OpenAIEmbeddings(model=config.model, api_key=key, **kwargs)


def _vertex(kwargs: dict) -> bool:
    """Whether the Google SDK authenticates through Vertex AI, as it decides itself: its
    ``vertexai`` setting, else GOOGLE_GENAI_USE_VERTEXAI, else a project or credentials given.
    Vertex AI takes its own credentials (ADC) and needs no API key."""
    from pydantic import TypeAdapter, ValidationError

    # Its own setting first, parsed as the SDK's ``bool | None`` field parses it: "false",
    # "0", "no" or "off", as an interpolated setting gives them, are False.
    try:
        vertexai = TypeAdapter(bool | None).validate_python(kwargs.get("vertexai"))
    except ValidationError:
        return True  # Not a flag: the SDK refuses it, by its own name, before any key is read.
    if vertexai is not None:
        return vertexai

    chosen = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower()
    if chosen in ("true", "1", "yes", "false", "0", "no"):
        return chosen in ("true", "1", "yes")

    return kwargs.get("project") is not None or kwargs.get("credentials") is not None


def _create_google_embedding(config: ProviderTaskConfig):
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except Exception as e:
        raise ImportError(
            "Google embedding provider requires langchain_google_genai. "
            "Please install it with: pip install langchain-google-genai"
        ) from e

    kwargs = dict(config.extra or {})
    # An API key as the LLMs read theirs: given, or from the environment, .env or stored, a
    # blank one none; GEMINI_API_KEY too, as the SDK reads it, unless another variable is named.
    env_name = kwargs.pop("api_key_env", "GOOGLE_API_KEY")
    key = kwargs.pop("api_key", None) or kwargs.pop("google_api_key", None) or credential(env_name)
    if key is None and env_name == "GOOGLE_API_KEY":
        key = credential("GEMINI_API_KEY")
    if key is not None:
        kwargs["api_key"] = key
    elif not _vertex(kwargs):
        # The Gemini Developer API needs one; Vertex AI authenticates as the SDK does.
        raise RuntimeError(f"Environment variable {env_name!r} is required")

    return GoogleGenerativeAIEmbeddings(model=config.model, **kwargs)


def create_embedding_model(config: ProviderTaskConfig):
    provider = config.provider.lower().strip()

    if provider == "openai":
        return _create_openai_embedding(config)

    if provider in {"google", "gemini", "google_genai"}:
        return _create_google_embedding(config)

    raise ValueError(f"Unsupported embedding provider: {config.provider}")
