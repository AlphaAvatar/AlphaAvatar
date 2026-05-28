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

import random
from importlib import resources
from typing import Any

from alphaavatar.agents.status import StatusEvent, StatusRendererBase

from .log import logger

_TEMPLATE_PACKAGE = "alphaavatar.plugins.status"
_TEMPLATE_DIR_NAME = "templates"


class DefaultStatusRenderer(StatusRendererBase):
    """
    File-based status renderer.

    Template filename format:
        {type}.{source}.{stage}.txt

    Examples:
        zh/tool_start.deepresearch.search.txt
        zh/tool_error.deepresearch.default.txt
        zh/tool_start.default.default.txt

    Each file can contain multiple templates, one per line.
    Empty lines and lines starting with "#" are ignored.
    """

    def __init__(self) -> None:
        self._templates: dict[str, dict[tuple[str, str, str], list[str]]] = {}
        self._load_templates()

    async def render(self, event: StatusEvent) -> str | None:
        if event.message:
            return self._normalize_message(event.type, event.message)

        language = self._detect_language(event)
        template = self._select_template(event, language=language)

        if template:
            return self._normalize_message(event.type, template)

        return None

    def _load_templates(self) -> None:
        """
        Load all templates at startup.

        Layout:
            templates/
                en/
                    tool_start.deepresearch.search.txt
                zh/
                    tool_start.deepresearch.search.txt
        """
        try:
            template_root = resources.files(_TEMPLATE_PACKAGE).joinpath(_TEMPLATE_DIR_NAME)
        except Exception as e:
            logger.warning("Failed to load templates: %s", e)
            return

        if not template_root.is_dir():
            return

        for lang_dir in template_root.iterdir():
            if not lang_dir.is_dir():
                continue

            language = lang_dir.name
            self._templates.setdefault(language, {})

            for file in lang_dir.iterdir():
                if not file.is_file():
                    continue

                if not file.name.endswith(".txt"):
                    continue

                key = self._parse_template_filename(file.name)
                if key is None:
                    continue

                templates = self._read_template_file(file)
                if not templates:
                    continue

                self._templates[language][key] = templates

        logger.info("Loaded status templates successfully!")

    def _parse_template_filename(self, filename: str) -> tuple[str, str, str] | None:
        stem = filename.removesuffix(".txt")
        parts = stem.split(".")

        if len(parts) != 3:
            return None

        status_type, source, stage = parts
        if not status_type or not source or not stage:
            return None

        return status_type, source, stage

    def _read_template_file(self, file: Any) -> list[str]:
        try:
            content = file.read_text(encoding="utf-8")
        except Exception:
            return []

        templates: list[str] = []

        for line in content.splitlines():
            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            templates.append(line)

        return templates

    def _select_template(self, event: StatusEvent, *, language: str) -> str | None:
        language = self._normalize_language(language)

        candidates = self._candidate_keys(event)

        for lang in self._language_fallbacks(language):
            lang_templates = self._templates.get(lang)
            if not lang_templates:
                continue

            for key in candidates:
                templates = lang_templates.get(key)
                if templates:
                    return random.choice(templates)

        return None

    def _candidate_keys(self, event: StatusEvent) -> list[tuple[str, str, str]]:
        status_type = self._to_value(event.type)
        source = self._to_value(event.source)
        stage = self._to_value(event.stage) or "default"

        return [
            # Exact: tool_start.deepresearch.search
            (status_type, source, stage),
            # Source-level fallback: tool_start.deepresearch.default
            (status_type, source, "default"),
            # Type-level fallback: tool_start.default.default
            (status_type, "default", "default"),
        ]

    def _normalize_message(self, status_type: str, message: str) -> str | None:
        message = message.strip()
        if not message:
            return None

        return message

    def _detect_language(self, event: StatusEvent) -> str:
        candidates: list[str] = []

        if event.message:
            candidates.append(event.message)

        query = event.metadata.get("query")
        if isinstance(query, str):
            candidates.append(query)

        text = "\n".join(candidates)

        if self._contains_cjk(text):
            return "zh"

        return "en"

    def _contains_cjk(self, text: str) -> bool:
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff":
                return True
        return False

    def _normalize_language(self, language: str) -> str:
        language = (language or "en").lower()

        if language.startswith("zh"):
            return "zh"

        if language.startswith("en"):
            return "en"

        return language

    def _language_fallbacks(self, language: str) -> list[str]:
        if language == "en":
            return ["en"]

        return [language, "en"]

    def _to_value(self, value: Any) -> str:
        if value is None:
            return ""

        return getattr(value, "value", str(value))
