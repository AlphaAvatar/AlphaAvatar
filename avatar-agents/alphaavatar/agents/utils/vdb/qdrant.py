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
def get_client(
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

    # init mode
    could_client = api_key and url
    local_client = url or (host and port)

    # init client
    if could_client:
        client = QdrantClient(api_key=api_key, url=url, prefer_grpc=prefer_grpc)
    elif local_client:
        client = QdrantClient(
            url=url if url else None,
            host=host if host else None,
            port=port if port else None,
            api_key=api_key,
            prefer_grpc=prefer_grpc,
        )
    else:
        raise ValueError(
            "We currently only support remote/local client creation, please enter a valid host:port or QDRANT_API_KEY and QDRANT_URL."
        )

    return client


def claim_space(client, collection: str, space, *, setting: str, ensure) -> None:
    """Open ``collection`` for vectors of ``space``, as ``space.claim`` checks and records it:
    the record one point of a collection beside it, ``<collection>__embedding``, as a
    collection keeps no metadata of its own."""
    from qdrant_client.models import Distance, PointStruct, VectorParams

    from .space import claim

    record = f"{collection}__embedding"

    def read():
        if not client.collection_exists(record):
            return None
        found = client.retrieve(record, ids=[0], with_payload=True)
        return dict(found[0].payload) if found else None

    def write(found) -> None:
        if not client.collection_exists(record):
            params = VectorParams(size=1, distance=Distance.DOT)
            client.create_collection(collection_name=record, vectors_config=params)
        client.upsert(record, points=[PointStruct(id=0, vector=[1.0], payload=found)])

    def size() -> int | None:
        vectors = client.get_collection(collection).config.params.vectors
        return getattr(vectors, "size", None)  # Named vectors: none told.

    claim(
        collection,
        space,
        label=f"Qdrant collection {collection!r}",
        setting=setting,
        exists=lambda: client.collection_exists(collection),
        ensure=ensure,
        read=read,
        write=write,
        count=lambda: client.count(collection, exact=True).count,
        size=size,
    )
