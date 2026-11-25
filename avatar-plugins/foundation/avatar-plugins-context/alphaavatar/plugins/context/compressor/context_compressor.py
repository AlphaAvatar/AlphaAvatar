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
from dataclasses import replace

from alphaavatar.agents.avatar.provider.enums import ModelMediaKind
from alphaavatar.agents.avatar.provider.schemas import (
    ModelFunctionOutput,
    ModelImagePart,
    ModelMediaPart,
    ModelTextPart,
)
from alphaavatar.agents.avatar.provider.schemas.model_input import ModelInputItem, ModelInputMessage

_IMAGE_NOT_REPLAYED = ModelTextPart("<image_not_replayed />")


class ContextCompressor:
    """Project historical items for replay in a model request."""

    def compress(self, history_items: tuple[ModelInputItem, ...]) -> tuple[ModelInputItem, ...]:
        items: list[ModelInputItem] = []
        for item in history_items:
            if isinstance(item, ModelInputMessage | ModelFunctionOutput):
                parts = tuple(
                    _IMAGE_NOT_REPLAYED
                    if isinstance(part, ModelImagePart)
                    or (isinstance(part, ModelMediaPart) and part.kind == ModelMediaKind.IMAGE)
                    else part
                    for part in item.parts
                )
                if any(part is _IMAGE_NOT_REPLAYED for part in parts):
                    item = replace(item, parts=parts)
            items.append(item)
        return tuple(items)
