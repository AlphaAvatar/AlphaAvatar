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

import base64
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from alphaavatar.agents.avatar.provider.enums import ModelMediaKind, ModelRole
from alphaavatar.agents.avatar.provider.errors import ModelCapabilityError, ModelProtocolError
from alphaavatar.agents.avatar.provider.schemas import (
    ModelFunctionCall,
    ModelFunctionOutput,
    ModelImagePart,
    ModelInputMessage,
    ModelMediaPart,
    ModelProviderItem,
    ModelRefusalPart,
    ModelRequest,
    ModelTextPart,
    ProviderTaskConfig,
)

from ..llms.config import ResponsesInputConfig
from .schema import output_format, strict_schema

BACKEND = "openai.responses"
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def continuation_scope(client_scope: str, model: str) -> str:
    return hashlib.sha256(f"{client_scope}:{model}".encode()).hexdigest()


def _url(uri: str, *, image: bool) -> str:
    parsed = urlparse(uri)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        if parsed.username or parsed.password:
            raise ModelCapabilityError("Media URLs cannot contain credentials")
        return uri
    if image and uri.startswith("data:image/") and ";base64," in uri:
        return uri
    raise ModelCapabilityError("Media must be inline data or an HTTP(S) URL, not a local path")


def _image_part(part: ModelImagePart, options: ResponsesInputConfig) -> ModelMediaPart:
    from alphaavatar.core.media import PayloadFormat, PayloadFormatUnavailable, PayloadView

    payload = part.observation.payload
    if payload is None:
        raise ModelCapabilityError("Image observation has no media payload")
    try:
        uri = payload.get(PayloadFormat.IMAGE_URI, view=PayloadView.RAW, fallback_to_raw=False)
        return ModelMediaPart(kind=ModelMediaKind.IMAGE, mime_type="image/*", uri=uri)
    except PayloadFormatUnavailable:
        pass
    for kind, mime in (
        (PayloadFormat.IMAGE_JPEG_BYTES, "image/jpeg"),
        (PayloadFormat.IMAGE_PNG_BYTES, "image/png"),
    ):
        try:
            data = payload.get(kind, view=PayloadView.ANNOTATED, fallback_to_raw=True)
            return ModelMediaPart(kind=ModelMediaKind.IMAGE, mime_type=mime, data=data)
        except PayloadFormatUnavailable:
            continue
    try:
        frame = payload.get(
            PayloadFormat.VIDEO_FRAME, view=PayloadView.ANNOTATED, fallback_to_raw=True
        )
    except PayloadFormatUnavailable as exc:
        raise ModelCapabilityError("Image has no supported payload representation") from exc
    from alphaavatar.core.media.codecs.video import encode_video_frame_to_jpeg

    return ModelMediaPart(
        kind=ModelMediaKind.IMAGE,
        mime_type="image/jpeg",
        data=encode_video_frame_to_jpeg(frame, jpeg_quality=options.jpeg_quality),
    )


class ResponsesAdapter:
    """Pure request-local encoder. The caller runs media encoding off the event loop."""

    def __init__(
        self, config: ProviderTaskConfig, options: ResponsesInputConfig, scope: str
    ) -> None:
        self._config = config
        self._options = options
        self._scope = scope
        self._inline_bytes = 0

    def _part(self, part: Any) -> dict[str, Any]:
        if isinstance(part, ModelTextPart):
            return {"type": "input_text", "text": part.text}
        if isinstance(part, ModelImagePart):
            part = _image_part(part, self._options)
        if not isinstance(part, ModelMediaPart) or part.kind not in {
            ModelMediaKind.IMAGE,
            ModelMediaKind.FILE,
        }:
            raise ModelCapabilityError(f"Responses input cannot encode {type(part).__name__}")
        image = part.kind == ModelMediaKind.IMAGE
        if part.data is not None:
            self._inline_bytes += len(part.data)
            self._check_size()
            encoded = base64.b64encode(part.data).decode("ascii")
            value = f"data:{part.mime_type};base64,{encoded}"
        else:
            value = _url(part.uri or "", image=image)
            if value.startswith("data:"):
                self._inline_bytes += len(value) * 3 // 4
                self._check_size()
        if image:
            return {"type": "input_image", "image_url": value, "detail": self._options.image_detail}
        if part.data is not None:
            if not part.filename:
                raise ModelCapabilityError("Inline file input requires a filename")
            return {"type": "input_file", "file_data": value, "filename": part.filename}
        return {"type": "input_file", "file_url": value}

    def _check_size(self) -> None:
        if self._inline_bytes > self._options.max_inline_bytes:
            raise ModelCapabilityError("Inline media exceeds the configured request limit")

    def _message(self, item: ModelInputMessage) -> dict[str, Any]:
        if item.role == ModelRole.ASSISTANT:
            if item.metadata.get("provider_backend") != BACKEND:
                if any(not isinstance(p, ModelTextPart) or p.annotations for p in item.parts):
                    raise ModelCapabilityError(
                        "Non-native assistant media/annotations need an adapter"
                    )
                value = {"role": "assistant", "content": item.text or ""}
                if item.phase is not None:
                    value["phase"] = item.phase.value
                return value
            content = []
            for part in item.parts:
                if isinstance(part, ModelTextPart):
                    content.append(
                        {
                            "type": "output_text",
                            "text": part.text,
                            "annotations": [dict(value) for value in part.annotations],
                        }
                    )
                elif isinstance(part, ModelRefusalPart):
                    content.append({"type": "refusal", "refusal": part.text})
                else:
                    raise ModelCapabilityError(
                        "Responses assistant history requires text or refusal"
                    )
            value = {
                "type": "message",
                "id": item.id,
                "role": "assistant",
                "status": "incomplete" if item.interrupted else "completed",
                "content": content,
            }
            if item.phase is not None:
                value["phase"] = item.phase.value
            return value
        if item.phase is not None:
            raise ModelCapabilityError("Only assistant messages can have a response phase")
        if item.role not in {ModelRole.SYSTEM, ModelRole.DEVELOPER, ModelRole.USER}:
            raise ModelCapabilityError(f"Unsupported message role: {item.role!r}")
        if item.role != ModelRole.USER and any(
            not isinstance(p, ModelTextPart) for p in item.parts
        ):
            raise ModelCapabilityError("System/developer instructions must be textual")
        return {"role": item.role.value, "content": [self._part(part) for part in item.parts]}

    def _item(self, item: Any) -> dict[str, Any]:
        if isinstance(item, ModelInputMessage):
            return self._message(item)
        if isinstance(item, ModelFunctionCall):
            value = {
                "type": "function_call",
                "call_id": item.call_id,
                "name": item.name,
                "arguments": item.arguments,
            }
            if item.metadata.get("provider_backend") == BACKEND:
                value["id"] = item.id
            return value
        if isinstance(item, ModelFunctionOutput):
            # Responses has no is_error flag; retain failure information in the actual payload.
            parts = [self._part(part) for part in item.parts]
            if item.is_error:
                parts.insert(0, {"type": "input_text", "text": "Tool execution failed."})
            output = (
                "\n".join(part["text"] for part in parts)
                if all(part["type"] == "input_text" for part in parts)
                else parts
            )
            return {"type": "function_call_output", "call_id": item.call_id, "output": output}
        if isinstance(item, ModelProviderItem):
            if item.backend != BACKEND or item.scope != self._scope:
                raise ModelCapabilityError(
                    "Provider continuation belongs to a different model/client"
                )
            value = json.loads(item.payload_json)
            if value.get("type") != "reasoning" or value.get("id") != item.id:
                raise ModelProtocolError("Unsupported continuation item")
            return value
        raise ModelCapabilityError(f"Responses cannot encode input item {type(item).__name__}")

    def encode(self, request: ModelRequest) -> dict[str, Any]:
        if request.input.realtime is not None:
            raise ModelCapabilityError("Responses is not a native realtime audio/video transport")
        if len({item.id for item in request.input.items}) != len(request.input.items):
            raise ModelProtocolError("Input contains duplicate item identities")
        self._inline_bytes = 0
        tools = []
        names = set()
        for tool in request.tools:
            if not _TOOL_NAME.fullmatch(tool.name) or tool.name in names:
                raise ModelCapabilityError("Tool names must be unique Responses function names")
            names.add(tool.name)
            schema = strict_schema(tool.parameters) if tool.strict else dict(tool.parameters)
            tools.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema,
                    "strict": tool.strict,
                }
            )
        value: dict[str, Any] = {
            "model": self._config.model,
            "input": [self._item(item) for item in request.input.items],
            "store": False,
            "stream": True,
            "include": ["reasoning.encrypted_content"],
            "truncation": "disabled",
            "tool_choice": request.tool_choice,
            "parallel_tool_calls": request.parallel_tool_calls,
        }
        if tools:
            value["tools"] = tools
        options = request.options
        temperature = (
            options.temperature
            if "temperature" in options.model_fields_set
            else self._config.temperature
        )
        if temperature is not None:
            value["temperature"] = temperature
        if options.max_output_tokens is not None:
            value["max_output_tokens"] = options.max_output_tokens
        if options.reasoning_effort is not None:
            value["reasoning"] = {"effort": options.reasoning_effort}
        if request.output_schema is not None:
            value["text"] = {"format": output_format(request.output_schema)}
        # Local metadata (user IDs, paths, trace destinations) never goes to the vendor.
        return value
