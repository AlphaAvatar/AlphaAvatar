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
from typing import Any

from alphaavatar.agents.providers.schema import ProviderTaskConfig

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _copy_extra(config: ProviderTaskConfig) -> dict[str, Any]:
    return dict(config.extra or {})


def _get_env_value(*, env_name: str, required: bool = True) -> str | None:
    value = os.getenv(env_name)
    if required and not value:
        raise RuntimeError(f"Environment variable '{env_name}' is required.")
    return value


def _build_common_kwargs(config: ProviderTaskConfig) -> dict[str, Any]:
    extra = _copy_extra(config)

    kwargs: dict[str, Any] = {
        "model": config.model,
        "temperature": config.temperature,
    }

    if config.timeout is not None:
        kwargs["timeout"] = config.timeout

    kwargs.update(extra)
    return kwargs


def _create_openai_llm(config: ProviderTaskConfig):
    try:
        from langchain_openai import ChatOpenAI
    except Exception as e:
        raise ImportError(
            "OpenAI LLM provider requires langchain_openai. "
            "Please install it with: pip install langchain-openai"
        ) from e

    kwargs = _build_common_kwargs(config)

    api_key_env = kwargs.pop("api_key_env", "OPENAI_API_KEY")
    api_key = kwargs.pop("api_key", None) or _get_env_value(env_name=api_key_env)

    return ChatOpenAI(
        api_key=api_key,
        **kwargs,
    )


def _create_openrouter_llm(config: ProviderTaskConfig):
    try:
        from langchain_openai import ChatOpenAI
    except Exception as e:
        raise ImportError(
            "OpenRouter LLM provider uses the OpenAI-compatible LangChain client. "
            "Please install it with: pip install langchain-openai"
        ) from e

    kwargs = _build_common_kwargs(config)

    api_key_env = kwargs.pop("api_key_env", "OPENROUTER_API_KEY")
    api_key = kwargs.pop("api_key", None) or _get_env_value(env_name=api_key_env)

    base_url = kwargs.pop("base_url", OPENROUTER_BASE_URL)

    # Optional OpenRouter metadata headers.
    # Example:
    # extra:
    #   default_headers:
    #     HTTP-Referer: "https://alphaavatar.ai"
    #     X-Title: "AlphaAvatar"
    default_headers = kwargs.pop("default_headers", None)

    if default_headers is not None:
        kwargs["default_headers"] = default_headers

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        **kwargs,
    )


def _create_google_llm(config: ProviderTaskConfig):
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except Exception as e:
        raise ImportError(
            "Google Gemini LLM provider requires langchain_google_genai. "
            "Please install it with: pip install langchain-google-genai"
        ) from e

    kwargs = _build_common_kwargs(config)

    api_key_env = kwargs.pop("api_key_env", "GOOGLE_API_KEY")
    api_key = kwargs.pop("api_key", None) or os.getenv(api_key_env)

    # ChatGoogleGenerativeAI can read GOOGLE_API_KEY from env by default.
    # Only pass api_key if explicitly available.
    if api_key:
        kwargs["api_key"] = api_key

    return ChatGoogleGenerativeAI(**kwargs)


def _create_anthropic_llm(config: ProviderTaskConfig):
    try:
        from langchain_anthropic import ChatAnthropic
    except Exception as e:
        raise ImportError(
            "Anthropic LLM provider requires langchain_anthropic. "
            "Please install it with: pip install langchain-anthropic"
        ) from e

    kwargs = _build_common_kwargs(config)

    api_key_env = kwargs.pop("api_key_env", "ANTHROPIC_API_KEY")
    api_key = kwargs.pop("api_key", None) or os.getenv(api_key_env)

    # ChatAnthropic can read ANTHROPIC_API_KEY from env by default.
    # Only pass api_key if explicitly available.
    if api_key:
        kwargs["api_key"] = api_key

    return ChatAnthropic(**kwargs)


def create_llm_model(config: ProviderTaskConfig):
    provider = config.provider.lower().strip()

    if provider == "openai":
        return _create_openai_llm(config)

    if provider == "openrouter":
        return _create_openrouter_llm(config)

    if provider in {"google", "gemini", "google_genai"}:
        return _create_google_llm(config)

    if provider in {"anthropic", "claude"}:
        return _create_anthropic_llm(config)

    raise ValueError(f"Unsupported LLM provider: {config.provider}")
