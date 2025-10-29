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
def get_qdrant_client(
    *,
    host: str | None = None,
    port: int | None = None,
    path: str = "/tmp/alphaavatar_qdrant_persona",
    url: str | None = None,
    api_key: str | None = None,
    on_disk: bool = False,
    prefer_grpc: bool = False,
    **kwargs,
):
    """
    Initialize Qdrant client.

    Args:
        host (str, optional): Qdrant server host (remote mode).
        port (int, optional): Qdrant server port (remote mode).
        path (str, optional): Local Qdrant DB path (local mode).
        url (str, optional): Full URL for Qdrant server (remote mode).
        api_key (str, optional): API key for Qdrant server (remote mode).
        on_disk (bool, optional): Keep local data directory if exists. Defaults to False.
        prefer_grpc (bool, optional): Prefer gRPC transport in remote mode.
    Returns:
        AsyncQdrantClient: The initialized asynchronous client.
    """
    try:
        from qdrant_client import QdrantClient
    except Exception:
        raise ImportError("Qdrant vector library import error, please install qdrant-client")

    is_remote = bool(url) or bool(api_key) or (host and port)

    if is_remote:
        # Remote synchronous client (HTTP 或 gRPC，取决于 prefer_grpc)
        client = QdrantClient(
            url=url if url else None,
            host=host if host else None,
            port=port if port else None,
            api_key=api_key if api_key else None,
            prefer_grpc=prefer_grpc,
        )
    else:
        # Local (embedded) synchronous client；本地模式不使用 gRPC
        # if os.path.exists(path) and not on_disk and os.path.isdir(path):
        #     shutil.rmtree(path)
        # client = QdrantClient(
        #     path=path,
        #     prefer_grpc=False,
        # )
        raise ValueError(
            "We currently only support remote client creation, please enter a valid host:port or api key."
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
