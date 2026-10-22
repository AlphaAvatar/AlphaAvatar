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

# Fixed-size pixel lettering: 56 columns by five rows, never doubled on wide terminals.
_GLYPHS = {
    "A": ("0110", "1001", "1111", "1001", "1001"),
    "L": ("1000", "1000", "1000", "1000", "1111"),
    "P": ("1110", "1001", "1110", "1000", "1000"),
    "H": ("1001", "1001", "1111", "1001", "1001"),
    "V": ("10001", "10001", "10001", "01010", "00100"),
    "T": ("11111", "00100", "00100", "00100", "00100"),
    "R": ("1110", "1001", "1110", "1010", "1001"),
}
_WORDMARK = "ALPHAAVATAR"
_TAGLINE = "Your Omni real-time assistant. Owned by you."


def _pixels(word: str, row: int, *, unicode: bool) -> str:
    fill = "█" if unicode else "#"
    pixels = "0".join(_GLYPHS[letter][row] for letter in word)
    return "".join(fill if pixel == "1" else " " for pixel in pixels)


def render_banner(
    version: str, *, devmode: bool, color: bool, unicode: bool = True, columns: int = 100
) -> str:
    """Render fixed-size pixels, or compact text for narrow/redirected output."""
    mode = "dev" if devmode else "start"
    detail = f"AlphaAvatar  v{version}  /  {mode}"
    width = sum(len(_GLYPHS[c][0]) for c in _WORDMARK) + len(_WORDMARK) - 1
    lines = []
    if columns >= width + 4:
        for row in range(5):
            left = _pixels("ALPHA", row, unicode=unicode)
            right = _pixels("AVATAR", row, unicode=unicode)
            if color:
                left = f"{BOLD}{BRAND_BLUE}{left}{RESET}"
                right = f"{BOLD}{SIGNAL_CYAN}{right}{RESET}"
            lines.append(f"  {left} {right}")
        lines.append("")
    if color:
        detail = f"{DIM}{detail}{RESET}" if lines else f"{BOLD}{BRAND_BLUE}{detail}{RESET}"
    lines.append(f"  {detail}")
    if columns == 0 or columns >= len(_TAGLINE) + 4:
        lines.append(f"  {DIM}{_TAGLINE}{RESET}" if color else f"  {_TAGLINE}")
    return "\n" + "\n".join(lines) + "\n\n"
