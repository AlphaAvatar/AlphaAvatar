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


LAYOUT = "alphaavatar_embedding_space"  # The record collection's one vector, named as its mark.
PAGE = 256  # Records read at a time.


def claim_space(client, collection: str, space, *, setting: str, ensure) -> None:
    """Open ``collection`` for vectors of ``space``, as ``space.claim`` checks and records it.

    The record is a collection beside it, ``<collection>__embedding``, as a collection keeps no
    metadata of its own: created with one vector named ``LAYOUT``, a mark it has from its
    creation on, and a point per Host recording, its ID this opening's own, so a Host never
    overwrites another's record, nor takes one back but its own; every page of it is read. One
    made before marks, its single record at point 0, is read as decided and never written;
    anything else of the name is refused, and nothing is written to it or beside it.
    """
    from uuid import uuid4

    from qdrant_client.models import Distance, PointIdsList, PointStruct, VectorParams

    from .space import PENDING, EmbeddingSpaceError, claim, is_record, not_a_record

    record = f"{collection}__embedding"
    label = f"Qdrant collection {collection!r}"
    own = str(uuid4())  # The point this opening records, if it records one.

    def layout() -> str | None:
        vectors = client.get_collection(record).config.params.vectors
        if isinstance(vectors, dict):
            params = vectors.get(LAYOUT)
            marked = set(vectors) == {LAYOUT} and params.size == 1
            return "marked" if marked and params.distance == Distance.DOT else None
        earlier = vectors.size == 1 and vectors.distance == Distance.DOT
        return "earlier" if earlier else None

    def records() -> list[dict]:
        if not client.collection_exists(record):
            return []
        kind = layout()
        points, offset = [], None
        while True:  # To the last page: however many Hosts recorded, none is left unread.
            page, offset = client.scroll(record, limit=PAGE, offset=offset, with_payload=True)
            points += page
            if offset is None:
                break

        found = [dict(point.payload or {}) for point in points]
        if kind == "marked":
            ours = all(is_record(item, store=collection, marked=True) for item in found)
        elif kind == "earlier":
            ours = [point.id for point in points] == [0]
            ours = ours and is_record(found[0], store=collection, marked=False)
        else:
            ours = False
        if not ours:
            raise EmbeddingSpaceError(not_a_record(f"Qdrant collection {record!r}", label))
        return found

    def write(found: dict) -> None:
        point = PointStruct(id=own, vector={LAYOUT: [1.0]}, payload=found)
        client.upsert(record, points=[point], wait=True)

    def register(found: dict) -> None:
        if not client.collection_exists(record):
            params = {LAYOUT: VectorParams(size=1, distance=Distance.DOT)}
            try:
                client.create_collection(collection_name=record, vectors_config=params)
            except Exception:
                if not client.collection_exists(record):
                    raise  # Not made meanwhile by another Host: a failure of its own.
        if layout() != "marked":
            raise EmbeddingSpaceError(not_a_record(f"Qdrant collection {record!r}", label))
        write(found | {PENDING: True})

    def withdraw(found: dict) -> None:
        # Called only before its deciding is asked (``space.claim``): its own, still pending.
        client.delete(record, points_selector=PointIdsList(points=[own]), wait=True)

    def size() -> int | None:
        vectors = client.get_collection(collection).config.params.vectors
        return getattr(vectors, "size", None)  # Named vectors: none told.

    claim(
        collection,
        space,
        label=label,
        setting=setting,
        exists=lambda: client.collection_exists(collection),
        size=size,
        count=lambda: client.count(collection, exact=True).count,
        records=records,
        register=register,
        confirm=write,
        withdraw=withdraw,
        ensure=ensure,
    )
