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

from .format import BOLD, BRAND_BLUE, DIM, RESET, SIGNAL_CYAN


def render_banner(version: str, *, devmode: bool, color: bool, unicode: bool = True) -> str:
    mark = "α" if unicode else "a"
    wordmark = f"  {mark}  AlphaAvatar"
    mode = "dev" if devmode else "start"
    detail = f"  v{version}  /  {mode}"
    tagline = "  Your real-time AI assistant. Owned by you."
    if color:
        wordmark = f"  {BRAND_BLUE}{mark}{RESET}  {BOLD}AlphaAvatar{RESET}"
        detail = f"{DIM}{detail}{RESET}"
        tagline = f"{SIGNAL_CYAN}{tagline}{RESET}"
    return f"\n{wordmark}\n{detail}\n{tagline}\n\n"
