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
"""The segment STT's requests against a transcription endpoint on loopback that answers as
the real one does, an HTTP/1.1 chunked event stream ended by ``data: [DONE]``: their timing,
the connection they keep, and the response's rest after the segment's outcome."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import threading
import time
from unittest import mock

import openai
import pytest

from alphaavatar.agents.configs.plugins.foundation.voice_config import STTConfig
from alphaavatar.core.media import AudioFrame
from alphaavatar.plugins.voice.stt import openai_segment
from alphaavatar.plugins.voice.stt.openai_segment import OpenAISegmentSTT

ANSWER_AFTER = 0.3  # The endpoint's own time before it answers
FIRST_AFTER = DONE_AFTER = 0.05  # Then to its first event, and from that to the done
LATE_END = 0.1  # A body whose end comes after its [DONE], within the tail's bound


def line(event: dict | str) -> bytes:
    return f"data: {event if isinstance(event, str) else json.dumps(event)}\n\n".encode()


def chunk(data: bytes) -> bytes:
    return f"{len(data):x}\r\n".encode() + data + b"\r\n"


DELTA = line({"type": "transcript.text.delta", "delta": "Hello"})
DONE = line({"type": "transcript.text.done", "text": "Hello"})
AGAIN = line({"type": "transcript.text.done", "text": "Hello again"})
FAILED = line({"error": {"message": "the endpoint failed"}})
END = line("[DONE]")
LAST = b"0\r\n\r\n"  # The chunked body's end
STREAM = b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream; charset=utf-8\r\n"
STREAM += b"transfer-encoding: chunked\r\nconnection: keep-alive\r\n\r\n"


class Endpoint:
    """A transcription endpoint, keep-alive: each request answered after its wait, its events
    spaced, as the real one answers; ``answers`` says, request by request, how the answer goes
    on or ends: ``end`` (the default), an event and [DONE] split across chunks, a second done,
    a body end that comes late, never or not at all (a cut), a done whose lines CR alone ends
    and nothing after it, a JSON answer, a stream error, or a [DONE] with no done before it."""

    def __init__(self, *answers: str | dict | list[bytes]) -> None:
        self.answers, self.connections = list(answers), 0
        self.received: list[int] = []
        self.bodies: list[bytes] = []  # Each request's body, as sent
        self.ended: list[float] = []  # When each body's end was sent

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
            self.bodies.append(await reader.readexactly(size))
            self.received.append(time.monotonic_ns())
            answer = self.answers.pop(0) if self.answers else "end"
            await asyncio.sleep(ANSWER_AFTER)
            if answer == "json" or isinstance(answer, dict):  # A whole transcript at once
                body = json.dumps(answer if isinstance(answer, dict) else {"text": "Hello"})
                body = body.encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
                    + f"content-length: {len(body)}\r\n\r\n".encode()
                    + body
                )
                await writer.drain()
                continue
            writer.write(STREAM)
            if isinstance(answer, list):  # The body's bytes as given, chunk by chunk
                for data in answer:
                    await writer.drain()
                    await asyncio.sleep(0.005)
                    writer.write(chunk(data))
                writer.write(LAST)
                await writer.drain()
                self.ended.append(time.monotonic())
                continue
            if answer == "failed":
                writer.write(chunk(FAILED) + chunk(END) + LAST)
                await writer.drain()
                continue
            if answer == "split":  # The events and [DONE] cut mid-way, across chunks
                body = DELTA + DONE + END
                for cut in zip(
                    (0, 9, len(DELTA) + 20, len(body) - 4),
                    (9, len(DELTA) + 20, len(body) - 4, len(body)),
                    strict=True,
                ):
                    await writer.drain()
                    await asyncio.sleep(0.01)
                    writer.write(chunk(body[slice(*cut)]))
            else:
                first = b"" if answer == "unfinished" else DELTA
                done = DONE if first else b""
                if answer == "stall-cr":  # The done's last CR ends its chunk; nothing follows.
                    first, done = first.replace(b"\n", b"\r"), done.replace(b"\n", b"\r")
                for gap, data in ((FIRST_AFTER, first), (DONE_AFTER, done)):
                    await writer.drain()
                    await asyncio.sleep(gap)
                    if data:
                        writer.write(chunk(data))
                if answer != "stall-cr":
                    writer.write(chunk(AGAIN + END if answer == "again" else END))
            await writer.drain()
            if answer in ("stall", "stall-cr"):
                await reader.read()  # Until the client gives the connection up
                break
            if answer == "cut":
                break
            if answer == "late":
                await asyncio.sleep(LATE_END)
            writer.write(LAST)
            await writer.drain()
            self.ended.append(time.monotonic())
        writer.close()


async def serve(endpoint: Endpoint, owned_endpoints: set[object]) -> tuple[asyncio.Server, str]:
    server = await asyncio.start_server(endpoint, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    owned_endpoints.add(("127.0.0.1", port))
    return server, f"http://127.0.0.1:{port}/v1"


async def transcribe(
    stt: OpenAISegmentSTT, *segments: str, then: object = None
) -> list[tuple[str, str, str | None, float]]:
    """Each segment's half second of 16 kHz PCM16, committed back to back; the outcome events
    until the last segment's own: (type, segment, text, when received)."""
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
    if then is not None:
        await then(stream)
    await stream.aclose()
    return seen


def requests(caplog: pytest.LogCaptureFixture) -> list[dict]:
    return [r.msg.fields for r in caplog.records if getattr(r.msg, "name", "") == "stt.request"]


def outcomes(seen: list[tuple]) -> list[tuple[str, str, str | None]]:
    return [event[:3] for event in seen]


async def test_each_segment_request_is_timed_by_its_queue_connection_and_exchange(
    caplog: pytest.LogCaptureFixture, owned_endpoints: set[object]
) -> None:
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    endpoint = Endpoint()
    server, url = await serve(endpoint, owned_endpoints)
    stt = OpenAISegmentSTT(model="gpt-4o-transcribe", api_key="sk-fictional", base_url=url)
    # Three segments committed back to back: each waits in the queue for the one before.
    seen = await transcribe(stt, "seg-1", "seg-2", "seg-3")
    server.close()
    await server.wait_closed()

    assert outcomes(seen) == [("FINAL_TRANSCRIPT", f"seg-{n}", "Hello") for n in (1, 2, 3)]
    timings = requests(caplog)
    assert [t["segment_id"] for t in timings] == ["seg-1", "seg-2", "seg-3"]
    assert {t["outcome"] for t in timings} == {"final"}
    # The first opens the connection (plain HTTP: no TLS); each body read to its end past its
    # [DONE], the next two reuse it, with no connect to time: an unset figure is left out.
    assert endpoint.connections == 1
    first, *rest = timings
    assert first["reused"] is False and first["connect_ms"] >= 0 and "tls_ms" not in first
    for timing in rest:
        assert timing["reused"] is True and not timing.keys() & {"connect_ms", "tls_ms"}
    for timing in timings:
        # The endpoint's wait falls between the audio sent and the answer's headers, and in
        # neither figure counted from those headers: they hold the events' own spacing.
        assert timing["wait_ms"] >= ANSWER_AFTER * 1000 - 5
        assert FIRST_AFTER * 1000 - 5 <= timing["first_event_ms"] < ANSWER_AFTER * 1000
        assert timing["first_event_ms"] + DONE_AFTER * 1000 - 5 <= timing["final_ms"]
        assert timing["final_ms"] < ANSWER_AFTER * 1000
        assert timing["upload_ms"] >= 0
    # The second segment waited in the queue while the first was answered.
    assert first["queue_ms"] < ANSWER_AFTER * 1000 <= rest[0]["queue_ms"] + 5


@pytest.mark.parametrize("answer", ["split", "again", "late", "stall", "stall-cr", "cut"])
async def test_the_final_goes_out_once_and_the_bodys_rest_never_holds_the_next_segment(
    answer: str, caplog: pytest.LogCaptureFixture, owned_endpoints: set[object]
) -> None:
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    endpoint = Endpoint(answer)
    server, url = await serve(endpoint, owned_endpoints)
    stt = OpenAISegmentSTT(model="gpt-4o-transcribe", api_key="sk-fictional", base_url=url)
    seen = await transcribe(stt, "seg-1", "seg-2")
    server.close()
    await server.wait_closed()

    # One final for each, the first done's: a second done is not published, and a body that
    # ends late, never or cut is no error of the segment it follows.
    assert outcomes(seen) == [
        ("FINAL_TRANSCRIPT", "seg-1", "Hello"),
        ("FINAL_TRANSCRIPT", "seg-2", "Hello"),
    ]
    first, second = requests(caplog)
    assert first["outcome"] == second["outcome"] == "final"
    answered = (ANSWER_AFTER + FIRST_AFTER + DONE_AFTER) * 1000
    if answer in ("split", "again", "late"):  # Read to its end within the bound: kept.
        assert endpoint.connections == 1 and second["reused"] is True
        if answer == "late":  # The final did not wait for the body's end.
            assert endpoint.ended[0] - seen[0][3] >= LATE_END - 0.02
        return
    # The connection whose body did not end is given up; the next segment opens another,
    # held by the tail no longer than its bound.
    assert endpoint.connections == 2 and second["reused"] is False
    assert second["queue_ms"] < answered + openai_segment._TAIL_SEC * 1000 + 150
    if answer in ("stall", "stall-cr"):
        # The final went out as it arrived, the bound's length before its request ended.
        assert seen[0][3] - endpoint.received[0] / 1e9 < answered / 1000 + 0.1
        logged = next(
            r.created for r in caplog.records if getattr(r.msg, "name", "") == "stt.request"
        )
        final_at = seen[0][3] - time.monotonic() + time.time()
        assert logged - final_at >= openai_segment._TAIL_SEC - 0.05
        assert second["queue_ms"] >= answered + openai_segment._TAIL_SEC * 1000 - 5


async def test_a_close_that_hangs_is_bounded_with_the_tail_and_the_next_segment_goes_on(
    caplog: pytest.LogCaptureFixture, owned_endpoints: set[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    server, url = await serve(Endpoint("stall"), owned_endpoints)
    real = openai._response.AsyncAPIResponse.close
    stuck: list[int] = []

    async def hangs(self: openai._response.AsyncAPIResponse) -> None:
        stuck[:] = stuck or [id(self)]
        if id(self) in stuck:
            await asyncio.sleep(30)  # The first response will not close, however asked.
        await real(self)

    monkeypatch.setattr(openai._response.AsyncAPIResponse, "close", hangs)
    stt = OpenAISegmentSTT(model="gpt-4o-transcribe", api_key="sk-fictional", base_url=url)
    seen = await transcribe(stt, "seg-1", "seg-2")
    server.close()
    await server.wait_closed()

    assert outcomes(seen) == [
        ("FINAL_TRANSCRIPT", "seg-1", "Hello"),
        ("FINAL_TRANSCRIPT", "seg-2", "Hello"),
    ]
    first, second = requests(caplog)
    # The stalled body and the close that hung share one bound: the second segment waited
    # for the first's answer and that bound, no more.
    answered = (ANSWER_AFTER + FIRST_AFTER + DONE_AFTER) * 1000
    assert second["queue_ms"] < answered + openai_segment._TAIL_SEC * 1000 + 150
    assert first["outcome"] == second["outcome"] == "final"


async def test_closing_the_stream_in_a_tail_cancels_it_and_releases_its_connection(
    owned_endpoints: set[object],
) -> None:
    endpoint = Endpoint("stall")
    server, url = await serve(endpoint, owned_endpoints)
    stt = OpenAISegmentSTT(model="gpt-4o-transcribe", api_key="sk-fictional", base_url=url)
    closed: list[float] = []

    async def close_in_the_tail(stream: object) -> None:
        await asyncio.sleep(0.05)  # The final is out; the body has not ended.
        began = time.monotonic()
        async with asyncio.timeout(2):  # A cancellation swallowed would hold the close.
            await stream.aclose()
        closed.append(time.monotonic() - began)

    seen = await transcribe(stt, "seg-1", then=close_in_the_tail)
    server.close()
    async with asyncio.timeout(2):  # The endpoint saw its connection closed.
        await server.wait_closed()
    assert outcomes(seen) == [("FINAL_TRANSCRIPT", "seg-1", "Hello")]
    # The cancellation reached the request, whose response was closed: not left to its bound.
    assert closed[0] < openai_segment._TAIL_SEC


NULL_DONE = line({"type": "transcript.text.done", "text": None})
# The real endpoint's line ends in another form: CR alone, a BOM before them, and a Chinese
# final whose UTF-8 bytes are cut between chunks.
CHINESE = "data: " + json.dumps(
    {"type": "transcript.text.done", "text": "你好"}, ensure_ascii=False
)
CR_STREAM = [
    "\ufeff".encode(),
    CHINESE.encode()[:-7],  # Within the UTF-8 of 你
    CHINESE.encode()[-7:] + b"\r\rdata: [DONE]\r\r",
]


@pytest.mark.parametrize(
    ("answer", "expected", "kept", "logged"),
    [
        ("json", ("FINAL_TRANSCRIPT", "Hello", None), True, "final"),  # whisper-1: no stream
        (CR_STREAM, ("FINAL_TRANSCRIPT", "你好", None), True, "final"),
        ("unfinished", ("ERROR", "", "missing_final"), True, "missing_final"),
        # A final without text is an invalid one, and logged as such: no final time.
        ([DELTA, NULL_DONE + END], ("ERROR", "", "invalid_final"), True, "invalid_final"),
        ({"text": None}, ("ERROR", "", "invalid_final"), True, "invalid_final"),
        # A stream error ends the request there, its body unread: that connection goes.
        ("failed", ("ERROR", "", "provider_error"), False, "no_final"),
    ],
    ids=["json", "cr-bom-utf8", "unfinished", "null-final", "json-null-final", "failed"],
)
async def test_each_answer_settles_its_segment_once_and_the_next_goes_on(
    answer: str | dict | list[bytes],
    expected: tuple,
    kept: bool,
    logged: str,
    caplog: pytest.LogCaptureFixture,
    owned_endpoints: set[object],
) -> None:
    caplog.set_level(logging.DEBUG, logger="alphaavatar")
    endpoint = Endpoint(answer)
    server, url = await serve(endpoint, owned_endpoints)
    stt = OpenAISegmentSTT(model="gpt-4o-transcribe", api_key="sk-fictional", base_url=url)
    stream = stt.stream(source_id="microphone")
    for segment in ("seg-1", "seg-2"):
        for _ in range(50):
            stream.push_frame(AudioFrame(16_000, 1, 160, bytes(320)), segment_id=segment)
            await asyncio.sleep(0)
        stream.commit_segment(segment)
    seen = []
    async with asyncio.timeout(10):
        async for event in stream:
            if event.type.name in ("FINAL_TRANSCRIPT", "ERROR"):
                seen.append((event.type.name, event.segment_id, event.text, event.reason_code))
                if event.segment_id == "seg-2":
                    break
    await stream.aclose()
    server.close()
    await server.wait_closed()

    kind, text, reason = expected
    assert [(e[0], e[1]) for e in seen] == [(kind, "seg-1"), ("FINAL_TRANSCRIPT", "seg-2")]
    assert (seen[0][2], seen[0][3]) == (text, reason)
    # Read to its end, the answer kept its connection for the next segment.
    assert (endpoint.connections, requests(caplog)[1]["reused"]) == (2 - kept, kept)
    # The request's log says what its consumer got: a final time for a valid final alone.
    first = requests(caplog)[0]
    assert first["outcome"] == logged
    assert ("final_ms" in first) is (logged == "final")
    # A first event when the endpoint sent one before its outcome: none before a bare [DONE].
    if logged in ("final", "invalid_final"):
        assert first["first_event_ms"] >= 0
    if logged == "missing_final":
        assert "first_event_ms" not in first


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
        on_loop = threading.current_thread() is threading.main_thread()
        prepared.append((on_loop, time.monotonic_ns()))

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

    assert outcomes(seen) == [("FINAL_TRANSCRIPT", "seg-1", "Hello")]
    # Prepared once, in a thread of its own, the loop running on meanwhile; the request
    # waited for it rather than import on the loop.
    ((on_loop, done_at),) = prepared
    assert not on_loop
    assert max(later - earlier for earlier, later in zip(ticks, ticks[1:], strict=False)) < 0.1
    assert endpoint.received[0] > done_at
    (timing,) = requests(caplog)
    assert timing["queue_ms"] >= 300 - 50


@pytest.mark.parametrize(
    ("language", "prompt", "carried"),
    [
        ("zh", "Keep every sentence.", {"language": "zh", "prompt": "Keep every sentence."}),
        ("auto", None, {}),  # Detection is what the model does unasked: nothing is sent.
        (None, None, {}),
    ],
)
async def test_the_configured_language_and_prompt_are_what_the_request_carries(
    language: str | None, prompt: str | None, carried: dict, owned_endpoints: set[object]
) -> None:
    endpoint = Endpoint()
    server, url = await serve(endpoint, owned_endpoints)
    settings = STTConfig(
        plugin="openai_segment",
        model="gpt-4o-transcribe",
        language=language,
        prompt=prompt,
        base_url=url,
    )
    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fictional"}):
        seen = await transcribe(settings.get_plugin(), "seg-1")
    server.close()
    await server.wait_closed()

    assert outcomes(seen) == [("FINAL_TRANSCRIPT", "seg-1", "Hello")]
    # The form fields the endpoint got, the audio file apart.
    form = dict(re.findall(rb'name="([^"]+)"\r\n\r\n(.*?)\r\n--', endpoint.bodies[0], re.S))
    form = {name.decode(): value.decode() for name, value in form.items()}
    assert {k: v for k, v in form.items() if k in ("language", "prompt")} == carried
    assert (form["model"], form["stream"]) == ("gpt-4o-transcribe", "true")


def test_a_setting_its_stt_does_not_take_is_refused_before_it_is_built() -> None:
    realtime = STTConfig(plugin="openai_realtime", model="gpt-realtime-whisper", prompt="Hi.")
    with pytest.raises(ValueError, match="voice.stt.prompt: .*'openai_realtime' does not take"):
        realtime.get_plugin()
    segment = STTConfig(plugin="openai_segment", model="gpt-4o-transcribe", delay="high")
    with pytest.raises(ValueError, match="voice.stt.delay: .*'openai_segment' does not take"):
        segment.get_plugin()


async def events(*chunks: str) -> list[str]:
    async def text():
        for piece in chunks:
            yield piece

    return [data async for data in openai_segment._sse(text())]


@pytest.mark.parametrize(
    ("chunks", "found"),
    [
        (["data: a\n\n", "data: b\n\n"], ["a", "b"]),
        (["data: a\r\n\r\ndata: b\r\n\r\n"], ["a", "b"]),
        (["data: a\r\rdata: b\r\r"], ["a", "b"]),
        # A CR at a chunk's end, its LF at the next one's start: one line end, not two.
        (['data: {"x":\r', "\ndata: 1}\r", "\n\r", "\n"], ['{"x":\n1}']),
        (["data: a\r", "", "\ndata: b\r", "", "\n\r"], ["a\nb"]),
        (['data: {"x":\n', "data: 1}\n\n"], ['{"x":\n1}']),
        ([": keep-alive\n", "event: message\nid: 7\nretry: 10\ndata:a\n\n"], ["a"]),
        (["\ufeffdata: a\n\n"], ["a"]),
        # The body's end closes the event it holds, without its blank line.
        (["data: a\n\ndata: [DONE]"], ["a", "[DONE]"]),
        (["data: a\n\ndata: [DONE]\r"], ["a", "[DONE]"]),
        # A line separator inside a JSON string is no line end of the stream's.
        (['data: {"text": "x\u2028y\x85z"}\n\n'], ['{"text": "x\u2028y\x85z"}']),
    ],
    ids=[
        "lf",
        "crlf",
        "cr",
        "crlf-across-chunks",
        "crlf-across-an-empty-chunk",
        "data-lines",
        "comments-fields",
        "bom",
        "end",
        "end-cr",
        "u2028",
    ],
)
async def test_server_sent_events_are_read_at_each_line_end_the_stream_may_use(
    chunks: list[str], found: list[str]
) -> None:
    assert await events(*chunks) == found
