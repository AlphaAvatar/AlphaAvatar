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
"""Google embeddings authenticate as the locked SDK does: an API key read as every provider's
is, or Vertex AI with its own credentials and no key. The SDK's client is replaced, so nothing
reaches Google."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from unittest import mock

import pytest

from alphaavatar.agents.configs.plugins.foundation.provider_config import ProviderTaskConfig
from alphaavatar.plugins.provider.langchain.embeddings.models import create_embedding_model

KEY = "google-fictional-0042"


class Client:
    """The SDK's client, recording how it was made."""

    made: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        Client.made.append(kwargs)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    import langchain_google_genai.embeddings as sdk

    Client.made = []
    monkeypatch.setattr(sdk, "Client", Client)
    # Restored before the isolation guard compares the process environment.
    with mock.patch.dict(os.environ):
        for name in UNSET:
            os.environ.pop(name, None)
        yield Client.made


UNSET = ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "MY_GOOGLE_KEY")


def embedding(**extra: Any):
    config = {"kind": "embedding", "provider": "google", "model": "text-embedding-004"}
    return create_embedding_model(ProviderTaskConfig.model_validate(config | {"extra": extra}))


def test_an_api_key_is_read_as_every_providers_is(client: list[dict[str, Any]]) -> None:
    os.environ["GOOGLE_API_KEY"] = KEY
    embedding()
    # A variable of one's own, the default unset; then the key given in the settings.
    del os.environ["GOOGLE_API_KEY"]
    os.environ["MY_GOOGLE_KEY"] = "mine-fictional"
    embedding(api_key_env="MY_GOOGLE_KEY")
    embedding(api_key="given-fictional")
    # GEMINI_API_KEY, as the SDK reads it, while no other variable is named.
    os.environ["GEMINI_API_KEY"] = "gemini-fictional"
    embedding()
    assert [made["api_key"] for made in client] == [
        KEY,
        "mine-fictional",
        "given-fictional",
        "gemini-fictional",
    ]
    assert not any(made.get("vertexai") for made in client)


@pytest.mark.parametrize("value", ["", " \t"], ids=["empty", "blank"])
def test_an_empty_or_blank_key_is_none_and_the_api_needs_one(
    value: str, client: list[dict[str, Any]]
) -> None:
    os.environ["GOOGLE_API_KEY"] = value
    with pytest.raises(RuntimeError, match="'GOOGLE_API_KEY' is required"):
        embedding()
    os.environ["MY_GOOGLE_KEY"] = value
    with pytest.raises(RuntimeError, match="'MY_GOOGLE_KEY' is required"):
        embedding(api_key_env="MY_GOOGLE_KEY")
    assert client == []  # Refused before any client exists.


@pytest.mark.parametrize(
    ("extra", "switch"),
    [
        ({"vertexai": True, "project": "your-project"}, None),
        ({"project": "your-project", "location": "us-central1"}, None),
        ({"project": "your-project"}, "true"),
    ],
    ids=["vertexai", "a project", "the environment's switch"],
)
def test_vertex_ai_authenticates_with_its_own_credentials_and_no_api_key(
    extra: dict[str, Any], switch: str | None, client: list[dict[str, Any]]
) -> None:
    if switch is not None:
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = switch
    embedding(**extra)
    (made,) = client
    assert made["vertexai"] is True and made["project"] == "your-project"
    assert "api_key" not in made
    # The environment's switch off sends it to the API, which needs a key.
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
    if "vertexai" not in extra:
        with pytest.raises(RuntimeError, match="'GOOGLE_API_KEY' is required"):
            embedding(**extra)
