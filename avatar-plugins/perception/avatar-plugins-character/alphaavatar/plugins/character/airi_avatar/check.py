# Copyright 2025 AlphaAvatar project
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
import asyncio
import logging
import platform
import re

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# ---- global cache (run once per process) ----
_PREFLIGHT_DONE = False
_PREFLIGHT_ERROR: str | None = None


# ---- helpers -------------------------------------------------------------


def _extract_missing_so(err_text: str) -> str | None:
    """
    Extract missing shared library from typical loader error.
    Example:
      error while loading shared libraries: libatk-1.0.so.0: cannot open ...
    """
    m = re.search(r"error while loading shared libraries:\s+([^\s:]+)", err_text)
    return m.group(1) if m else None


def _detect_linux_family() -> str:
    """
    Best-effort Linux family detection.
    Returns: debian | rhel | alpine | arch | unknown
    """
    try:
        with open("/etc/os-release") as f:
            data = f.read().lower()
    except Exception:
        return "unknown"

    if "alpine" in data:
        return "alpine"
    if any(x in data for x in ("rhel", "centos", "rocky", "alma", "fedora", "anolis", "alinux")):
        return "rhel"
    if any(x in data for x in ("debian", "ubuntu")):
        return "debian"
    if "arch" in data:
        return "arch"
    return "unknown"


def _install_hint_for_linux(family: str) -> str:
    """
    Return human-readable install hints (no sudo execution).
    """
    if family == "debian":
        return (
            "sudo apt update && sudo apt install -y "
            "libatk1.0-0 libatk-bridge2.0-0 "
            "libnss3 libxkbcommon0 libgbm1 libdrm2 "
            "libxcomposite1 libxdamage1 libxfixes3 "
            "libxrandr2 libx11-6 libx11-xcb1 libxcb1 "
            "libpangocairo-1.0-0 libpango-1.0-0 libcairo2 "
            "libgtk-3-0 libasound2 fonts-liberation"
        )

    if family == "rhel":
        return (
            "sudo dnf install -y "
            "atk at-spi2-atk gtk3 pango cairo "
            "libXcomposite libXdamage libXfixes libXrandr "
            "libXcursor libXinerama libxkbcommon libXrender libxcb "
            "mesa-libgbm libdrm nss alsa-lib liberation-fonts"
        )

    if family == "alpine":
        return (
            "sudo apk add "
            "chromium nss freetype harfbuzz ca-certificates "
            "ttf-freefont libstdc++ gtk+3.0 atk at-spi2-atk "
            "pango cairo mesa-gbm alsa-lib"
        )

    if family == "arch":
        return (
            "sudo pacman -S --needed "
            "chromium nss atk gtk3 pango cairo "
            "libxcomposite libxdamage libxfixes libxrandr "
            "libxkbcommon mesa libdrm alsa-lib"
        )

    return (
        "Please install Playwright Chromium system dependencies for your Linux distribution.\n"
        "See: https://playwright.dev/docs/ci#linux"
    )


# ---- public API ----------------------------------------------------------


async def chromium_preflight_check(timeout_s: float = 10.0) -> None:
    """
    Preflight check for Playwright Chromium (headless).
    - Runs once per process
    - Raises RuntimeError with actionable hints on failure
    """
    global _PREFLIGHT_DONE, _PREFLIGHT_ERROR

    if _PREFLIGHT_DONE:
        if _PREFLIGHT_ERROR:
            raise RuntimeError(_PREFLIGHT_ERROR)
        return

    _PREFLIGHT_DONE = True

    try:

        async def _probe():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                await browser.close()

        await asyncio.wait_for(_probe(), timeout=timeout_s)
        logger.info("[AIRI] Chromium preflight OK (headless launch succeeded).")
        _PREFLIGHT_ERROR = None

    except Exception as e:
        os_info = platform.platform()
        msg = str(e)
        missing_so = _extract_missing_so(msg)
        family = _detect_linux_family()
        install_hint = _install_hint_for_linux(family)

        lines = [
            "[AIRI] Chromium preflight FAILED: headless Chromium cannot start.",
            f"OS: {os_info}",
            f"Detected Linux family: {family}",
        ]

        if missing_so:
            lines.append(f"Missing shared library detected: {missing_so}")

        lines.extend(
            [
                "",
                "To fix this, install required system dependencies, for example:",
                f"  {install_hint}",
                "",
                "Then ensure Playwright browsers are installed:",
                "  python -m playwright install chromium",
                "",
                f"Original error: {e!r}",
            ]
        )

        friendly = "\n".join(lines)
        _PREFLIGHT_ERROR = friendly
        logger.error(friendly)
        raise RuntimeError(friendly) from e
