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
"""The segment STT's request timing, against a transcription endpoint on loopback."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from alphaavatar.core.media import AudioFrame
from alphaavatar.plugins.voice.stt.openai_segment import OpenAISegmentSTT

ANSWER_AFTER = 0.2  # The endpoint's own time before it answers


async def endpoint(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """A transcription endpoint on one keep-alive connection: each request answered, after
    its wait, with a streamed final."""
    lines = [
        {"type": "transcript.text.delta", "delta": "Hello"},
        {"type": "transcript.text.done", "text": "Hello"},
    ]
    body = "".join(f"data: {json.dumps(line)}\n\n" for line in lines).encode()
    while True:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError:  # The client closed the connection.
            writer.close()
            return
        size = next(
            int(line.split(b":", 1)[1])
            for line in head.split(b"\r\n")
            if line.lower().startswith(b"content-length:")
        )
        await reader.readexactly(size)
        await asyncio.sleep(ANSWER_AFTER)
        writer.write(
            b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
            + f"content-length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()


async def test_each_segment_request_is_timed_by_its_queue_connection_and_exchange(
    caplog: pytest.LogCaptureFixture, owned_endpoints: set[object]
) -> None:
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    server = await asyncio.start_server(endpoint, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    owned_endpoints.add(("127.0.0.1", port))
    stt = OpenAISegmentSTT(
        model="gpt-4o-transcribe", api_key="sk-fictional", base_url=f"http://127.0.0.1:{port}/v1"
    )
    stream = stt.stream(source_id="microphone")
    # Two segments committed back to back: the second waits in the queue for the first.
    for segment in ("seg-1", "seg-2"):
        for _ in range(50):  # Half a second of 16 kHz PCM16, as it arrives
            assert stream.push_frame(AudioFrame(16_000, 1, 160, bytes(320)), segment_id=segment)
            await asyncio.sleep(0)
        assert stream.commit_segment(segment)
    finals = []
    async with asyncio.timeout(10):
        async for event in stream:
            if event.type.name == "FINAL_TRANSCRIPT":
                finals.append(event.segment_id)
                if len(finals) == 2:
                    break
    await stream.aclose()
    server.close()
    await server.wait_closed()

    first, second = (
        r.msg.fields for r in caplog.records if getattr(r.msg, "name", "") == "stt.request"
    )
    assert (first["segment_id"], second["segment_id"]) == ("seg-1", "seg-2") == tuple(finals)
    assert first["outcome"] == second["outcome"] == "final"
    # The first opens the connection (plain HTTP: no TLS). A request that opens one times
    # its connect; one that reuses a connection has none to time: an unset figure is left out.
    assert first["reused"] is False and first["connect_ms"] >= 0
    for timing in (first, second):
        assert timing["reused"] is ("connect_ms" not in timing) and "tls_ms" not in timing
        # The endpoint's wait falls between the body sent and the answer's headers.
        assert timing["wait_ms"] >= ANSWER_AFTER * 1000 - 5
        assert timing["upload_ms"] >= 0 and timing["final_ms"] >= timing["first_event_ms"] >= 0
    # The second segment waited in the queue while the first was answered.
    assert first["queue_ms"] < ANSWER_AFTER * 1000 <= second["queue_ms"] + 5
