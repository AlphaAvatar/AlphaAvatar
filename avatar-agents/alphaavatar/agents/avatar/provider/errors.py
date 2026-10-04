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


class ModelError(Exception):
    """Provider-neutral failure; SDK exceptions must not become application contracts."""


class ModelCapabilityError(ModelError):
    """The selected backend cannot represent the requested operation without data loss."""


class ModelProtocolError(ModelError):
    """Malformed, inconsistent, unsupported, or prematurely terminated response stream."""


class ModelRequestError(ModelError):
    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ModelIncompleteError(ModelError):
    def __init__(self, *, response_id: str, reason: str) -> None:
        super().__init__(f"Model response is incomplete: {reason}")
        self.response_id = response_id
        self.reason = reason


class ModelRefusalError(ModelError):
    """A valid refusal is not a validated structured result."""
