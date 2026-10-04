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

import json
from dataclasses import dataclass, field
from typing import Any

from alphaavatar.agents.avatar.provider.enums import ModelFinishReason, ModelMessagePhase, ModelRole
from alphaavatar.agents.avatar.provider.errors import (
    ModelIncompleteError,
    ModelProtocolError,
    ModelRequestError,
)
from alphaavatar.agents.avatar.provider.schemas import (
    ModelFunctionCall,
    ModelInputMessage,
    ModelProviderItem,
    ModelRefusalPart,
    ModelTextPart,
)
from alphaavatar.agents.avatar.provider.schemas.stream import (
    ModelItemCompleted,
    ModelItemStarted,
    ModelOutputItem,
    ModelReasoningDelta,
    ModelRefusalDelta,
    ModelResponseCompleted,
    ModelResponseStarted,
    ModelStreamEvent,
    ModelTextDelta,
    ModelToolCallDelta,
)

from ..adapters.responses import BACKEND
from ..usage import normalize_usage
from .config import ResponsesInputConfig


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelProtocolError(message)


def _text(value: Any, *, empty: bool = True) -> str:
    _require(isinstance(value, str) and (empty or bool(value)), "Expected a response string")
    return value


def _index(value: Any) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, "Invalid index")
    return value


def _phase(value: Any) -> ModelMessagePhase | None:
    try:
        return ModelMessagePhase(value) if value is not None else None
    except ValueError as exc:
        raise ModelProtocolError("Unknown assistant message phase") from exc


def decode_item(raw: dict[str, Any], *, scope: str) -> ModelOutputItem:
    kind, identity = raw.get("type"), _text(raw.get("id"), empty=False)
    _require(raw.get("status") in {None, "completed"}, "Output item is not complete")
    if kind == "message":
        _require(raw.get("role") == "assistant", "Only assistant output messages are supported")
        _require(isinstance(raw.get("content"), list), "Output message has no content array")
        parts = []
        for part in raw["content"]:
            if part.get("type") == "output_text":
                annotations = part.get("annotations", [])
                _require(isinstance(annotations, list), "Invalid text annotations")
                _require(all(isinstance(a, dict) for a in annotations), "Invalid text annotation")
                parts.append(ModelTextPart(_text(part.get("text")), tuple(annotations)))
            elif part.get("type") == "refusal":
                parts.append(ModelRefusalPart(_text(part.get("refusal"))))
            else:
                raise ModelProtocolError("Unsupported Responses output content part")
        return ModelInputMessage(
            id=identity,
            role=ModelRole.ASSISTANT,
            parts=tuple(parts),
            phase=_phase(raw.get("phase")),
            metadata={"provider_backend": BACKEND},
        )
    if kind == "function_call":
        _require(not raw.get("namespace"), "Namespaced function calls are not enabled")
        _require(
            (raw.get("caller") or {}).get("type", "direct") == "direct",
            "Program calls are not enabled",
        )
        return ModelFunctionCall(
            id=identity,
            call_id=_text(raw.get("call_id"), empty=False),
            name=_text(raw.get("name"), empty=False),
            arguments=_text(raw.get("arguments")),
            metadata={"provider_backend": BACKEND},
        )
    if kind == "reasoning":
        # Stateless continuation must not substitute a visible summary for the opaque state.
        _text(raw.get("encrypted_content"), empty=False)
        return ModelProviderItem(
            id=identity,
            backend=BACKEND,
            scope=scope,
            payload_json=json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
    raise ModelProtocolError(f"Unsupported Responses output item type: {kind!r}")


@dataclass(slots=True)
class _Item:
    raw: dict[str, Any]
    chunks: dict[tuple[str, int], list[str]] = field(default_factory=dict)
    done_parts: set[tuple[str, int]] = field(default_factory=set)
    declared_parts: dict[int, str] = field(default_factory=dict)
    annotations: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    complete: ModelOutputItem | None = None
    finished: bool = False


class ResponsesDecoder:
    """One response, one ordered event stream. Never treats a missing terminal as success."""

    def __init__(self, *, request_id: str, scope: str, options: ResponsesInputConfig) -> None:
        self.request_id = request_id
        self.response_id: str | None = None
        self.completed: ModelResponseCompleted | None = None
        self.raw_response: dict[str, Any] | None = None
        self._scope = scope
        self._options = options
        self._sequence = -1
        self._chars = 0
        self._snapshot_chars = 0
        self._items: dict[int, _Item] = {}
        self._ids: set[str] = set()

    def _identity(self) -> dict[str, str]:
        if self.response_id is None:
            raise ModelProtocolError("Response output arrived before response.created")
        return {"request_id": self.request_id, "response_id": self.response_id}

    def _item(self, event: dict[str, Any]) -> tuple[int, _Item]:
        index = _index(event.get("output_index"))
        _require(index in self._items, "Output event arrived before item registration")
        item = self._items[index]
        _require(not item.finished, "Output arrived after item completion")
        if "item_id" in event:
            _require(event["item_id"] == item.raw["id"], "Output item identity mismatch")
        return index, item

    def _append(self, item: _Item, key: tuple[str, int], delta: str) -> None:
        _require(key not in item.done_parts, "Delta arrived after content completion")
        self._chars += len(delta)
        _require(
            self._chars <= self._options.max_output_chars, "Response exceeds local output limit"
        )
        item.chunks.setdefault(key, []).append(delta)

    @staticmethod
    def _check_text(item: _Item, key: tuple[str, int], value: str) -> None:
        _require(
            "".join(item.chunks.get(key, [])) == value, "Stream text/argument snapshot mismatch"
        )

    def _complete_item(self, event: dict[str, Any]) -> ModelItemCompleted | None:
        index, item = self._item(event)
        raw = event["item"]
        self._snapshot_chars += len(json.dumps(raw, ensure_ascii=False))
        _require(
            self._snapshot_chars <= self._options.max_output_chars,
            "Response item snapshots are too large",
        )
        _require(raw.get("id") == item.raw["id"], "Completed item ID mismatch")
        _require(raw.get("type") == item.raw["type"], "Completed item type mismatch")
        kind = raw["type"]
        if kind == "message":
            prior = item.raw.get("phase")
            _require(
                prior is None or prior == raw.get("phase"), "Assistant phase changed mid-message"
            )
            parts = raw.get("content", [])
            _require(
                set(item.declared_parts) == set(range(len(parts))), "Content indices have gaps"
            )
            for i, part in enumerate(parts):
                part_kind = part.get("type")
                _require(item.declared_parts[i] == part_kind, "Content type changed")
                value = part.get("text") if part_kind == "output_text" else part.get("refusal")
                self._check_text(item, (part_kind, i), _text(value))
                emitted = item.annotations.get(i, [])
                _require(not emitted or emitted == part.get("annotations"), "Annotations changed")
        elif kind == "function_call":
            _require(raw.get("call_id") == item.raw.get("call_id"), "Tool call identity changed")
            _require(raw.get("name") == item.raw.get("name"), "Tool name changed")
            self._check_text(item, ("arguments", 0), _text(raw.get("arguments")))
        elif kind == "reasoning":
            summary = raw.get("summary", [])
            for (part_kind, i), chunks in item.chunks.items():
                _require(
                    part_kind == "summary" and i < len(summary), "Reasoning summary index changed"
                )
                _require("".join(chunks) == summary[i].get("text"), "Reasoning summary changed")
        item.finished = True
        if raw.get("status") == "incomplete":
            # Wait for response.incomplete; never release a partial tool call as executable.
            return None
        item.complete = decode_item(raw, scope=self._scope)
        return ModelItemCompleted(**self._identity(), output_index=index, item=item.complete)

    def feed(self, event: dict[str, Any]) -> tuple[ModelStreamEvent, ...]:
        _require(self.completed is None, "Event arrived after terminal response")
        seq = _index(event.get("sequence_number"))
        _require(seq > self._sequence, "Responses event sequence regressed or repeated")
        self._sequence = seq
        kind = event.get("type")
        if kind == "response.created":
            _require(self.response_id is None, "Duplicate response.created")
            self.response_id = _text(event["response"].get("id"), empty=False)
            return (ModelResponseStarted(**self._identity()),)
        if kind == "error":
            code = str(event.get("code") or "response_failed")
            raise ModelRequestError(
                "OpenAI response failed",
                code=code,
                retryable=code in {"server_error", "rate_limit_exceeded"},
            )
        self._identity()
        if event.get("response_id") is not None:
            _require(event["response_id"] == self.response_id, "Response identity changed")
        if kind in {"response.in_progress", "response.queued"}:
            _require(event["response"].get("id") == self.response_id, "Response identity changed")
            return ()
        if kind in {"response.failed", "response.incomplete"}:
            response = event.get("response", {})
            if response:
                _require(
                    response.get("id") == self.response_id, "Terminal response identity changed"
                )
            if kind == "response.incomplete":
                reason = (response.get("incomplete_details") or {}).get("reason", "unknown")
                raise ModelIncompleteError(response_id=self.response_id, reason=str(reason))
            code = (response.get("error") or event).get("code", "response_failed")
            raise ModelRequestError(
                "OpenAI response failed",
                code=str(code),
                retryable=code in {"server_error", "rate_limit_exceeded"},
            )
        if kind == "response.output_item.added":
            index = _index(event.get("output_index"))
            raw = dict(event["item"])
            identity = _text(raw.get("id"), empty=False)
            _require(
                index not in self._items and identity not in self._ids, "Duplicate output item"
            )
            _require(index < self._options.max_output_items, "Too many output items")
            _require(
                raw.get("type") in {"message", "function_call", "reasoning"},
                "Unsupported output item",
            )
            self._ids.add(identity)
            item = self._items[index] = _Item(raw)
            events = [
                ModelItemStarted(
                    **self._identity(),
                    item_id=identity,
                    output_index=index,
                    kind=raw["type"],
                    phase=_phase(raw.get("phase")),
                )
            ]
            if raw["type"] == "function_call":
                initial = _text(raw.get("arguments", ""))
                self._append(item, ("arguments", 0), initial)
                events.append(
                    ModelToolCallDelta(
                        **self._identity(),
                        item_id=identity,
                        output_index=index,
                        call_id=_text(raw.get("call_id"), empty=False),
                        name=_text(raw.get("name"), empty=False),
                        arguments=initial,
                    )
                )
            return tuple(events)
        if kind == "response.output_item.done":
            complete = self._complete_item(event)
            return (complete,) if complete is not None else ()
        if kind == "response.completed":
            response = event["response"]
            _require(response.get("id") == self.response_id, "Final response identity mismatch")
            _require(response.get("status") == "completed", "Invalid successful terminal status")
            raw_items = response.get("output", [])
            _require(
                set(self._items) == set(range(len(raw_items))), "Output item indices have gaps"
            )
            items = tuple(decode_item(raw, scope=self._scope) for raw in raw_items)
            for i, value in enumerate(items):
                _require(
                    self._items[i].complete == value, "Terminal output differs from completed items"
                )
            calls = [item.call_id for item in items if isinstance(item, ModelFunctionCall)]
            _require(len(calls) == len(set(calls)), "Duplicate function call identities")
            self.raw_response = response
            self.completed = ModelResponseCompleted(
                **self._identity(),
                items=items,
                finish_reason=ModelFinishReason.TOOL_CALLS if calls else ModelFinishReason.STOP,
                usage=normalize_usage(response.get("usage")),
            )
            return (self.completed,)
        index, item = self._item(event)
        content_index = _index(event.get("summary_index", event.get("content_index", 0)))
        if kind in {"response.content_part.added", "response.reasoning_summary_part.added"}:
            part = event["part"]
            part_kind = part.get("type")
            if kind == "response.content_part.added":
                _require(item.raw["type"] == "message", "Content belongs to a non-message")
                _require(part_kind in {"output_text", "refusal"}, "Unsupported output content")
                _require(content_index not in item.declared_parts, "Repeated content index")
                item.declared_parts[content_index] = part_kind
            else:
                _require(item.raw["type"] == "reasoning", "Summary belongs to a non-reasoning item")
                _require(part_kind == "summary_text", "Unsupported reasoning summary")
            _require(
                not part.get("text") and not part.get("refusal"), "Initial content must be empty"
            )
            return ()
        variants = {
            "response.output_text": ("output_text", ModelTextDelta, "text"),
            "response.refusal": ("refusal", ModelRefusalDelta, "refusal"),
            "response.reasoning_summary_text": ("summary", ModelReasoningDelta, "text"),
        }
        prefix, _, action = str(kind).rpartition(".")
        if prefix in variants and action in {"delta", "done"}:
            part_kind, event_class, field_name = variants[prefix]
            _require(
                item.raw["type"] == "reasoning"
                if part_kind == "summary"
                else item.declared_parts.get(content_index) == part_kind,
                "Delta content type mismatch",
            )
            key = (part_kind, content_index)
            if action == "done":
                _require(key not in item.done_parts, "Duplicate content terminal")
                self._check_text(item, key, _text(event.get(field_name)))
                item.done_parts.add(key)
                return ()
            delta = _text(event.get("delta"))
            self._append(item, key, delta)
            return (
                event_class(
                    **self._identity(),
                    item_id=item.raw["id"],
                    output_index=index,
                    content_index=content_index,
                    text=delta,
                    phase=_phase(item.raw.get("phase")),
                ),
            )
        if kind in {
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
        }:
            _require(item.raw["type"] == "function_call", "Arguments belong to a non-tool item")
            key = ("arguments", 0)
            if kind.endswith(".done"):
                _require(key not in item.done_parts, "Duplicate tool arguments terminal")
                self._check_text(item, key, _text(event.get("arguments")))
                item.done_parts.add(key)
                return ()
            delta = _text(event.get("delta"))
            self._append(item, key, delta)
            return (
                ModelToolCallDelta(
                    **self._identity(),
                    item_id=item.raw["id"],
                    output_index=index,
                    call_id=item.raw["call_id"],
                    name=item.raw["name"],
                    arguments=delta,
                ),
            )
        if kind == "response.output_text.annotation.added":
            _require(
                item.declared_parts.get(content_index) == "output_text", "Annotation is not text"
            )
            annotations = item.annotations.setdefault(content_index, [])
            _require(
                _index(event.get("annotation_index")) == len(annotations), "Annotation index gap"
            )
            _require(isinstance(event.get("annotation"), dict), "Invalid annotation")
            annotations.append(dict(event["annotation"]))
            return ()
        if kind in {"response.content_part.done", "response.reasoning_summary_part.done"}:
            part = event["part"]
            part_kind = "summary" if "summary" in kind else part.get("type")
            value = part.get("refusal") if part_kind == "refusal" else part.get("text")
            self._check_text(item, (part_kind, content_index), _text(value))
            return ()
        raise ModelProtocolError(f"Unsupported Responses event type: {kind!r}")

    def finish(self) -> ModelResponseCompleted:
        if self.completed is None:
            raise ModelProtocolError("Responses stream ended without response.completed")
        return self.completed
