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
import hashlib
import uuid
from urllib.parse import parse_qsl, urlencode, urlparse

from slugify import slugify

from .enum import SessionType


def get_user_id():
    return uuid.uuid4().hex


def get_session_id(session_type: SessionType) -> str:
    return f"{session_type.value}-{uuid.uuid4().hex}"


def normalize_url(url: str) -> str:
    """
    Normalize URL to ensure stable hashing.
    - Remove fragment (#...)
    - Sort query parameters
    """

    parsed = urlparse(url)

    # Sort query parameters to make URL order-insensitive
    query = urlencode(sorted(parse_qsl(parsed.query)))

    return parsed._replace(
        fragment="",
        query=query,
    ).geturl()


def url_to_filename_id(url: str, hash_len: int = 6) -> str:
    """
    Convert a URL to a filesystem-safe filename id.

    Strategy:
    - Use domain + path as human-readable slug
    - Append short hash for uniqueness
    """

    normalized_url = normalize_url(url)

    parsed = urlparse(normalized_url)

    # Build readable part: domain + path
    readable_part = f"{parsed.netloc}{parsed.path}"

    slug = slugify(
        readable_part,
        lowercase=True,
        separator="-",
    )

    # Short hash for uniqueness
    hash_id = hashlib.sha1(normalized_url.encode("utf-8")).hexdigest()[:hash_len]

    return f"{slug}-{hash_id}"
