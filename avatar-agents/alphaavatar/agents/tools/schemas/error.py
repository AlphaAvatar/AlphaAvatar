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
from ..enums import ToolErrorCode


class ToolError(RuntimeError):
    """An intentional, model-safe tool failure; never an SDK exception."""

    def __init__(
        self, message: str, *, code: ToolErrorCode = ToolErrorCode.EXECUTION_FAILED
    ) -> None:
        super().__init__(message)
        self.code = code
