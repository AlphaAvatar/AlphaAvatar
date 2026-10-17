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

# Five-by-seven pixels; only the letters in the wordmark are needed, not a font dependency.
_GLYPHS = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
}
_WORDMARK = "ALPHAAVATAR"
_TAGLINE = "Your real-time AI assistant. Owned by you."


def _pixels(word: str, row: int, *, scale: int, unicode: bool) -> str:
    fill = "█" if unicode else "#"
    pixels = "0".join(_GLYPHS[letter][row] for letter in word)
    return "".join((fill if pixel == "1" else " ") * scale for pixel in pixels)


def render_banner(
    version: str, *, devmode: bool, color: bool, unicode: bool = True, columns: int = 100
) -> str:
    """Render once before logs; columns=0 selects compact redirected output."""
    mode = "dev" if devmode else "start"
    detail = f"AlphaAvatar  v{version}  /  {mode}"
    width = len(_WORDMARK) * 6 - 1
    lines = []
    if columns >= width + 4:
        scale = 2 if columns >= width * 2 + 4 else 1
        for row in range(7):
            left = _pixels("ALPHA", row, scale=scale, unicode=unicode)
            right = _pixels("AVATAR", row, scale=scale, unicode=unicode)
            if color:
                left = f"{BOLD}{BRAND_BLUE}{left}{RESET}"
                right = f"{BOLD}{SIGNAL_CYAN}{right}{RESET}"
            lines.append(f"  {left}{' ' * scale}{right}")
        lines.append("")
    if color:
        detail = f"{DIM}{detail}{RESET}" if lines else f"{BOLD}{BRAND_BLUE}{detail}{RESET}"
    lines.append(f"  {detail}")
    if columns == 0 or columns >= len(_TAGLINE) + 4:
        tagline = f"{DIM}{_TAGLINE}{RESET}" if color else _TAGLINE
        lines.append(f"  {tagline}")
    return "\n" + "\n".join(lines) + "\n\n"
