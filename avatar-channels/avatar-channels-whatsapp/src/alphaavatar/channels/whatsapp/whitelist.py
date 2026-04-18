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
from pathlib import Path

from .log import logger


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def normalize_whatsapp_jid(jid: str) -> str:
    base = (jid or "").split("@", 1)[0]
    return _normalize_phone(base)


def is_group_jid(jid: str) -> bool:
    return (jid or "").endswith("@g.us")


def whitelist_enabled() -> bool:
    return os.getenv("WHATSAPP_WHITELIST_ENABLED", "false").lower() == "true"


def whitelist_file() -> str:
    return os.getenv("WHATSAPP_WHITELIST_FILE", "").strip()


def load_whitelist() -> set[str]:
    path_str = whitelist_file()
    if not path_str:
        logger.warning("WHATSAPP_WHITELIST_FILE is empty")
        return set()

    path = Path(path_str)
    if not path.exists():
        logger.warning("Whitelist file not found: %s", path)
        return set()

    values: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        norm = _normalize_phone(line.strip())
        if norm:
            values.add(norm)

    return values


def is_allowed_sender(jid: str) -> bool:
    if not whitelist_enabled():
        return True

    # Default group rejection - groups are not supported at all regardless of whitelist
    if is_group_jid(jid):
        return False

    normalized = normalize_whatsapp_jid(jid)
    whitelist = load_whitelist()
    return normalized in whitelist
