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
"""The segment STT's requests against a transcription endpoint on loopback: their timing,
the connection they keep, and the stream's rest after the final."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time

import openai
import pytest

from alphaavatar.core.media import AudioFrame
from alphaavatar.plugins.voice.stt import openai_segment
from alphaavatar.plugins.voice.stt.openai_segment import OpenAISegmentSTT

ANSWER_AFTER = 0.3  # The endpoint's own time before it answers
FIRST_AFTER = DONE_AFTER = 0.05  # Then to its first event, and from that to the done


def line(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


DELTA = line({"type": "transcript.text.delta", "delta": "Hello"})
DONE = line({"type": "transcript.text.done", "text": "Hello"})
AGAIN = line({"type": "transcript.text.done", "text": "Hello again"})


class Endpoint:
    """A transcription endpoint on one keep-alive connection at a time: each request answered
    after its wait, its events spaced; ``tails`` says, request by request, what follows the
    done: nothing (``end``), a second done, a stall or a connection cut mid-body."""

    def __init__(self, *tails: str) -> None:
        self.tails, self.connections, self.received = list(tails), 0, []

    async def __call__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        while True:
            try:
                head = await reader.readuntil(b"\r\n\r\n")
            except asyncio.IncompleteReadError:  # The client closed the connection.
                break
            size = next(
                int(field.split(b":", 1)[1])
                for field in head.split(b"\r\n")
                if field.lower().startswith(b"content-length:")
            )
            await reader.readexactly(size)
            self.received.append(time.monotonic_ns())
            tail = self.tails.pop(0) if self.tails else "end"
            rest = AGAIN if tail == "again" else b""
            # A stalled or cut body promises more than it sends.
            promised = len(DELTA) + len(DONE) + len(rest) + (0 if tail in ("end", "again") else 64)
            await asyncio.sleep(ANSWER_AFTER)
            writer.write(
                b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
                + f"content-length: {promised}\r\n\r\n".encode()
            )
            for gap, chunk in ((FIRST_AFTER, DELTA), (DONE_AFTER, DONE + rest)):
                await writer.drain()
                await asyncio.sleep(gap)
                writer.write(chunk)
            await writer.drain()
            if tail == "stall":
                await reader.read()  # Until the client gives the connection up
                break
            if tail == "cut":
                break
        writer.close()


async def serve(endpoint: Endpoint, owned_endpoints: set[object]) -> tuple[asyncio.Server, str]:
    server = await asyncio.start_server(endpoint, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    owned_endpoints.add(("127.0.0.1", port))
    return server, f"http://127.0.0.1:{port}/v1"


async def transcribe(stt: OpenAISegmentSTT, *segments: str) -> list[tuple[str, str, str | None]]:
    """Each segment's half second of 16 kHz PCM16, committed back to back; the events until
    the last segment's own: (type, segment, text)."""
    stream = stt.stream(source_id="microphone")
    for segment in segments:
        for _ in range(50):
            assert stream.push_frame(AudioFrame(16_000, 1, 160, bytes(320)), segment_id=segment)
            await asyncio.sleep(0)  # As frames arrive
        assert stream.commit_segment(segment)
    seen = []
    async with asyncio.timeout(10):
        async for event in stream:
            if event.type.name in ("FINAL_TRANSCRIPT", "ERROR"):
                seen.append((event.type.name, event.segment_id, event.text, time.monotonic()))
                if event.segment_id == segments[-1]:
                    break
    await stream.aclose()
    return seen


def requests(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [r.msg.fields for r in caplog.records if getattr(r.msg, "name", "") == "stt.request"]


async def test_each_segment_request_is_timed_by_its_queue_connection_and_exchange(
    caplog: pytest.LogCaptureFixture, owned_endpoints: set[object]
) -> None:
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    endpoint = Endpoint()
    server, url = await serve(endpoint, owned_endpoints)
    stt = OpenAISegmentSTT(model="gpt-4o-transcribe", api_key="sk-fictional", base_url=url)
    # Two segments committed back to back: the second waits in the queue for the first.
    seen = await transcribe(stt, "seg-1", "seg-2")
    server.close()
    await server.wait_closed()

    assert [event[:3] for event in seen] == [
        ("FINAL_TRANSCRIPT", "seg-1", "Hello"),
        ("FINAL_TRANSCRIPT", "seg-2", "Hello"),
    ]
    first, second = requests(caplog)
    assert (first["segment_id"], second["segment_id"]) == ("seg-1", "seg-2")
    assert first["outcome"] == second["outcome"] == "final"
    # The first opens the connection (plain HTTP: no TLS); read to its end, the second
    # reuses it, with no connect to time: an unset figure is left out.
    assert endpoint.connections == 1
    assert first["reused"] is False and first["connect_ms"] >= 0 and "tls_ms" not in first
    assert second["reused"] is True and "connect_ms" not in second and "tls_ms" not in second
    for timing in (first, second):
        # The endpoint's wait falls between the audio sent and the answer's headers, and in
        # neither figure counted from those headers: they hold the events' own spacing.
        assert timing["wait_ms"] >= ANSWER_AFTER * 1000 - 5
        assert FIRST_AFTER * 1000 - 5 <= timing["first_event_ms"] < ANSWER_AFTER * 1000
        assert timing["first_event_ms"] + DONE_AFTER * 1000 - 5 <= timing["final_ms"]
        assert timing["final_ms"] < ANSWER_AFTER * 1000
        assert timing["upload_ms"] >= 0
    # The second segment waited in the queue while the first was answered.
    assert first["queue_ms"] < ANSWER_AFTER * 1000 <= second["queue_ms"] + 5


@pytest.mark.parametrize("tail", ["again", "stall", "cut"])
async def test_the_final_goes_out_once_and_the_streams_rest_never_holds_the_next_segment(
    tail: str, caplog: pytest.LogCaptureFixture, owned_endpoints: set[object]
) -> None:
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    endpoint = Endpoint(tail)
    server, url = await serve(endpoint, owned_endpoints)
    stt = OpenAISegmentSTT(model="gpt-4o-transcribe", api_key="sk-fictional", base_url=url)
    seen = await transcribe(stt, "seg-1", "seg-2")
    server.close()
    await server.wait_closed()

    # One final for each, the first done's: a second done is not published, and a tail that
    # stalls or breaks is no error of the segment it follows.
    assert [event[:3] for event in seen] == [
        ("FINAL_TRANSCRIPT", "seg-1", "Hello"),
        ("FINAL_TRANSCRIPT", "seg-2", "Hello"),
    ]
    first, second = requests(caplog)
    assert first["outcome"] == second["outcome"] == "final"
    if tail == "again":  # Read to its end: the connection is kept.
        assert endpoint.connections == 1 and second["reused"] is True
        return
    # The connection whose tail did not end is given up; the next segment opens another,
    # held by the tail no longer than its bound.
    assert endpoint.connections == 2 and second["reused"] is False
    answered = (ANSWER_AFTER + FIRST_AFTER + DONE_AFTER) * 1000
    assert second["queue_ms"] < answered + openai_segment._TAIL_SEC * 1000 + 150
    if tail == "stall":
        # The final went out as it arrived, the bound's length before its request ended.
        logged = next(
            r.created for r in caplog.records if getattr(r.msg, "name", "") == "stt.request"
        )
        final_at = seen[0][3] - time.monotonic() + time.time()
        assert logged - final_at >= openai_segment._TAIL_SEC - 0.05
        assert second["queue_ms"] >= answered + openai_segment._TAIL_SEC * 1000 - 5


async def test_a_request_the_transport_did_not_trace_is_not_counted_as_reused(
    caplog: pytest.LogCaptureFixture, owned_endpoints: set[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    server, url = await serve(Endpoint(), owned_endpoints)
    # A client of the caller's own carries no trace of its connection.
    client = openai.AsyncOpenAI(api_key="sk-fictional", base_url=url, max_retries=0)
    seen = await transcribe(OpenAISegmentSTT(model="gpt-4o-transcribe", client=client), "seg-1")
    await client.close()
    server.close()
    await server.wait_closed()
    assert [event[:2] for event in seen] == [("FINAL_TRANSCRIPT", "seg-1")]

    # A request that failed before the transport took it; one that could not connect.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    owned_endpoints.add(("127.0.0.1", closed))
    refused = OpenAISegmentSTT(
        model="gpt-4o-transcribe", api_key="sk-fictional", base_url=f"http://127.0.0.1:{closed}/v1"
    )
    seen = await transcribe(refused, "seg-2")
    assert [event[:2] for event in seen] == [("ERROR", "seg-2")]

    def unbuilt(self: object, job: object) -> dict:
        raise RuntimeError("request not built")

    monkeypatch.setattr(openai_segment.OpenAISegmentSTTStream, "_request_kwargs", unbuilt)
    seen = await transcribe(refused, "seg-3")
    assert [event[:2] for event in seen] == [("ERROR", "seg-3")]

    own, refusal, unbuilt_request = requests(caplog)
    # Neither untraced request says it reused a connection, nor times one.
    for timing in (own, unbuilt_request):
        assert "reused" not in timing
        assert not timing.keys() & {"connect_ms", "tls_ms", "upload_ms", "wait_ms"}
    assert own["outcome"] == "final" and unbuilt_request["outcome"] == "no_final"
    assert "first_event_ms" not in own and "final_ms" not in own
    # The refused one opened a connection, or tried: it is not counted as reused.
    assert refusal["reused"] is False and refusal["outcome"] == "no_final"
    assert "connect_ms" not in refusal


async def test_the_sdk_prepares_its_transcription_off_the_event_loop_before_any_request(
    caplog: pytest.LogCaptureFixture, owned_endpoints: set[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    endpoint = Endpoint()
    server, url = await serve(endpoint, owned_endpoints)
    prepared: list[tuple[bool, int]] = []
    real = openai_segment._prepare

    def slow(client: openai.AsyncOpenAI) -> None:  # A first import that takes its time
        time.sleep(0.3)
        real(client)
        prepared.append(
            (threading.current_thread() is threading.main_thread(), time.monotonic_ns())
        )

    monkeypatch.setattr(openai_segment, "_prepare", slow)
    ticks: list[float] = []

    async def heartbeat() -> None:
        while True:
            ticks.append(time.monotonic())
            await asyncio.sleep(0.01)

    beating = asyncio.create_task(heartbeat())
    stt = OpenAISegmentSTT(model="gpt-4o-transcribe", api_key="sk-fictional", base_url=url)
    seen = await transcribe(stt, "seg-1")
    beating.cancel()
    server.close()
    await server.wait_closed()

    assert [event[:3] for event in seen] == [("FINAL_TRANSCRIPT", "seg-1", "Hello")]
    # Prepared once, in a thread of its own, the loop running on meanwhile; the request
    # waited for it rather than import on the loop.
    ((on_loop, done_at),) = prepared
    assert not on_loop
    assert max(later - earlier for earlier, later in zip(ticks, ticks[1:], strict=False)) < 0.1
    assert endpoint.received[0] > done_at
    (timing,) = requests(caplog)
    assert timing["queue_ms"] >= 300 - 50
