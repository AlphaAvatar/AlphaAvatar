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

import asyncio
from typing import Any

from livekit import rtc
from livekit.agents import AgentSession

from alphaavatar.agents.log import logger

from .envelopes import InputEnvelope, OutputEnvelope


def _extract_text_from_content(content: Any) -> str:
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()

    text = getattr(content, "text", None)
    if isinstance(text, str):
        return text

    return str(content)


def _extract_reply_text_from_run(run_result: Any) -> str:
    try:
        final_output = run_result.final_output
        if isinstance(final_output, str) and final_output.strip():
            return final_output.strip()
        if final_output is not None:
            text = _extract_text_from_content(final_output)
            if text:
                return text
    except Exception:
        pass

    try:
        for ev in reversed(run_result.events):
            item = getattr(ev, "item", None)
            if item is None:
                continue

            role = getattr(item, "role", None)
            item_type = getattr(item, "type", None)

            if role != "assistant" or item_type != "message":
                continue

            content = getattr(item, "content", None)
            text = _extract_text_from_content(content)
            if text:
                return text
    except Exception:
        pass

    raise RuntimeError("No assistant text found in RunResult")


class InputDispatcher:
    """
    Feed the unified InputEnvelope to the AgentSession and return the OutputEnvelope.
    """

    def __init__(self, *, room: rtc.Room, session: AgentSession) -> None:
        self.room = room
        self.session = session
        self._run_lock = asyncio.Lock()

    async def dispatch_text(self, envelope: InputEnvelope) -> OutputEnvelope:
        async with self._run_lock:
            try:
                run_result = self.session.run(
                    user_input=envelope.text or "",
                )
                await run_result

                reply_text = _extract_reply_text_from_run(run_result)

            except Exception:
                logger.exception("InputDispatcher text run failed")
                reply_text = "Sorry, something went wrong while processing your message."

        return OutputEnvelope(
            channel=envelope.channel,
            user_id=envelope.user_id,
            session_id=envelope.session_id,
            room_name=envelope.room_name,
            correlation_id=envelope.message_id,
            modality="text",
            text=reply_text,
            metadata={"source": "input-dispatcher"},
        )
