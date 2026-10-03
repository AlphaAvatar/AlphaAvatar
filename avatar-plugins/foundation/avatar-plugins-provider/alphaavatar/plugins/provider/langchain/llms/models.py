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
from __future__ import annotations

import os
from typing import Any

import httpx

from alphaavatar.agents.avatar.provider.schemas import ProviderTaskConfig

from ..resources import ModelResources

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OWNED_FIELDS = {
    "client",
    "async_client",
    "root_client",
    "root_async_client",
    "http_client",
    "http_async_client",
    "provider_http_client",
    "provider_http_async_client",
}


def _build_common_kwargs(config: ProviderTaskConfig) -> dict[str, Any]:
    extra = dict(config.extra)
    if fields := _OWNED_FIELDS.intersection(extra):
        raise ValueError(f"Provider owns client fields: {', '.join(sorted(fields))}")
    if extra.get("reuse_last_container"):
        raise ValueError("Shared task models cannot retain an Anthropic conversation container")
    return {
        "model": config.model,
        "temperature": config.temperature,
        "timeout": config.timeout,
        **extra,
    }


def _api_key(kwargs: dict[str, Any], default_env: str, *, required: bool = True) -> str | None:
    env_name = kwargs.pop("api_key_env", default_env)
    key = kwargs.pop("api_key", None) or os.getenv(env_name)
    if required and not key:
        raise RuntimeError(f"Environment variable {env_name!r} is required")
    return key


def _http_clients(
    resources: ModelResources, *, proxy: str | None = None
) -> tuple[httpx.Client, httpx.AsyncClient]:
    client = httpx.Client(proxy=proxy)
    resources.add_sync(client.close)
    async_client = httpx.AsyncClient(proxy=proxy)
    resources.add_async(async_client.aclose)
    return client, async_client


def _create_openai_llm(config: ProviderTaskConfig, resources: ModelResources) -> Any:
    from langchain_openai import ChatOpenAI

    kwargs = _build_common_kwargs(config)
    openrouter = config.provider.strip().lower() == "openrouter"
    key = _api_key(kwargs, "OPENROUTER_API_KEY" if openrouter else "OPENAI_API_KEY")
    if openrouter:
        kwargs.setdefault("base_url", OPENROUTER_BASE_URL)
    # Supplying transports bypasses LangChain's default cache. Handle its proxy explicitly.
    proxy = kwargs.pop("openai_proxy", None) or os.getenv("OPENAI_PROXY") or None
    client, async_client = _http_clients(resources, proxy=proxy)
    return ChatOpenAI(
        api_key=key, http_client=client, http_async_client=async_client, openai_proxy="", **kwargs
    )


def _create_anthropic_llm(config: ProviderTaskConfig, resources: ModelResources) -> Any:
    from .anthropic import OwnedChatAnthropic

    kwargs = _build_common_kwargs(config)
    key = _api_key(kwargs, "ANTHROPIC_API_KEY")
    proxy = kwargs.pop("anthropic_proxy", None) or os.getenv("ANTHROPIC_PROXY") or None
    client, async_client = _http_clients(resources, proxy=proxy)
    model = OwnedChatAnthropic(
        api_key=key, provider_http_client=client, provider_http_async_client=async_client, **kwargs
    )
    # Materialize cached SDK facades in the initialization thread, not on the media loop.
    _ = model._client, model._async_client
    return model


def _create_google_llm(config: ProviderTaskConfig, resources: ModelResources) -> Any:
    from langchain_google_genai import ChatGoogleGenerativeAI

    kwargs = _build_common_kwargs(config)
    key = _api_key(kwargs, "GOOGLE_API_KEY", required=False)
    if key:
        kwargs["api_key"] = key
    model = ChatGoogleGenerativeAI(**kwargs)
    client = model.client
    if client is None:
        raise RuntimeError("Google provider did not initialize a client")
    resources.add_sync(client.close)
    resources.add_async(client.aio.aclose)

    def detach_client() -> None:
        # Prevent the LangChain destructor from scheduling a second, unmanaged async close.
        model.client = None

    resources.add_sync(detach_client)
    return model


def create_llm_model(config: ProviderTaskConfig, resources: ModelResources) -> Any:
    """Blocking construction only; the owner runs this in a tracked initialization task."""
    provider = config.provider.strip().lower()
    if provider in {"openai", "openrouter"}:
        return _create_openai_llm(config, resources)
    if provider in {"google", "gemini", "google_genai"}:
        return _create_google_llm(config, resources)
    if provider in {"anthropic", "claude"}:
        return _create_anthropic_llm(config, resources)
    raise ValueError(f"Unsupported LLM provider: {config.provider!r}")
