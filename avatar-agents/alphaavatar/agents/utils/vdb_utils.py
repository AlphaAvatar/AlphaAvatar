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


def get_qdrant_client(
    *,
    host: str | None = None,
    port: int | None = None,
    url: str | None = None,
    api_key: str | None = None,
    prefer_grpc: bool = False,
    **kwargs,
):
    """
    Initialize Qdrant client.

    Args:
        host (str, optional): Qdrant server host (remote mode).
        port (int, optional): Qdrant server port (remote mode).
        url (str, optional): Full URL for Qdrant server (remote mode).
        api_key (str, optional): API key for Qdrant server (remote mode).
        prefer_grpc (bool, optional): Prefer gRPC transport in remote mode.
    Returns:
        AsyncQdrantClient: The initialized asynchronous client.
    """
    try:
        from qdrant_client import QdrantClient
    except Exception:
        raise ImportError("Qdrant vector library import error, please install qdrant-client")

    # init param
    api_key = api_key or os.getenv("QDRANT_API_KEY", None)
    url = url or os.getenv("QDRANT_URL", None)

    # init mode
    could_client = api_key and url
    local_client = url or (host and port)

    # init client
    if could_client:
        client = QdrantClient(
            api_key=api_key,
            url=url,
            prefer_grpc=prefer_grpc,
        )
    elif local_client:
        client = QdrantClient(
            url=url if url else None,
            host=host if host else None,
            port=port if port else None,
            prefer_grpc=prefer_grpc,
        )
    else:
        raise ValueError(
            "We currently only support remote/local client creation, please enter a valid host:port or QDRANT_API_KEY and QDRANT_URL."
        )

    return client


def get_embedding_model(*, embedding_model, **kwargs):
    try:
        from langchain_openai import OpenAIEmbeddings
    except Exception:
        raise ImportError(
            "Langchain OpenAIEmbeddings import error, please install langchain_openai"
        )

    embeddings = OpenAIEmbeddings(model=embedding_model)
    return embeddings
