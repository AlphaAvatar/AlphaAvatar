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
"""Doctor's fixed samples: what the diagnostic session says, shows and expects back.

The questions are recordings shipped as 16 kHz mono PCM16 WAV (``samples/``, generated
offline by ``scripts/make_doctor_samples.sh``); the picture is drawn here. Each question asks
for a one-word answer, so a reply is judged whole: it must equal one of the task's answers
once case, surrounding space and punctuation are set aside. A longer, negated or hedged reply,
or another number that merely contains the right digit, does not pass. The answer to the
card question depends on the picture alone.
"""

from __future__ import annotations

import io
import re
import wave
from dataclasses import dataclass
from functools import cache
from importlib import resources

import numpy as np

SAMPLE_RATE = 16_000
TRAILING_SILENCE_SEC = 1.5  # Sent as a microphone would, then silence continues until done.
_VOICED_WINDOW_SEC = 0.02
_VOICED_FLOOR = 0.05  # Of the loudest window: quieter windows count as silence.
# A question mark stays: "Green?" is a guess, not an answer.
_EDGES = " \t\r\n.,!;:'\"()[]。，！；：、“”‘’（）"
_WORD = re.compile(r"[\w']+")


def _plain(text: str) -> str:
    return " ".join(text.split()).strip(_EDGES).lower()


@dataclass(frozen=True, slots=True)
class Speech:
    name: str
    pcm: bytes  # 16 kHz mono PCM16, little endian
    voiced_end_sec: float  # Where the last voiced window of the recording ends

    @property
    def duration_sec(self) -> float:
        return len(self.pcm) / 2 / SAMPLE_RATE


@dataclass(frozen=True, slots=True)
class Task:
    name: str
    prompt: str  # What is asked, word for word: the recording says it, or it is typed
    answers: tuple[str, ...]  # The whole answer must be one of these
    transcript_words: tuple[tuple[str, ...], ...] = ()  # One word of each group in the STT final
    speech: str | None = None  # Recording name
    text: str | None = None  # Typed input
    screen: bool = False  # The card picture on a shared screen while the question is asked

    def answered(self, answer: str) -> bool:
        return _plain(answer) in self.answers

    def heard(self, transcript: str) -> bool:
        words = set(_WORD.findall(transcript.lower()))
        return all(words.intersection(group) for group in self.transcript_words)


# The picture arrives as screen-share frames: it has no face, and a camera would make the
# turn wait for visual addressing that a picture of a card cannot give.
VOICE_VISION = Task(
    "voice_vision",
    "What color is the card on my screen? Answer in one word.",
    answers=("green", "绿", "绿色"),
    transcript_words=(("color", "colour"), ("card",)),
    speech="card_question",
    screen=True,
)
VOICE = Task(
    "voice",
    "What is two plus three? Answer with just the number.",
    answers=("5", "five", "五"),
    transcript_words=(("two", "2"), ("three", "3")),
    speech="sum_question",
)
TEXT = Task(
    "text",
    "What is two plus three? Answer with just the number.",
    answers=("5", "five", "五"),
    text="What is two plus three? Answer with just the number.",
)


@cache
def speech(name: str) -> Speech:
    data = resources.files(__package__).joinpath("samples", f"{name}.wav").read_bytes()
    with wave.open(io.BytesIO(data)) as recording:
        if (recording.getnchannels(), recording.getsampwidth(), recording.getframerate()) != (
            1,
            2,
            SAMPLE_RATE,
        ):
            raise ValueError(f"Sample {name} must be 16 kHz mono PCM16")
        pcm = recording.readframes(recording.getnframes())
    return Speech(name, pcm, voiced_end(pcm))


def voiced_end(pcm: bytes) -> float:
    """The end of the last window louder than a fraction of the loudest one, in seconds."""
    window = int(SAMPLE_RATE * _VOICED_WINDOW_SEC)
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    count = samples.size // window
    if not count:
        return 0.0
    rms = np.sqrt(np.mean(samples[: count * window].reshape(count, window) ** 2, axis=1))
    voiced = np.flatnonzero(rms >= rms.max() * _VOICED_FLOOR)
    return float((voiced[-1] + 1) * window / SAMPLE_RATE) if voiced.size else 0.0


def card_picture(width: int = 640, height: int = 360) -> np.ndarray:
    """A green card on a grey desk, as BGR pixels."""
    picture = np.full((height, width, 3), (128, 128, 128), dtype=np.uint8)
    top, left = height // 4, width // 3
    picture[top : height - top, left : width - left] = (255, 255, 255)
    picture[top + 8 : height - top - 8, left + 8 : width - left - 8] = (40, 170, 40)
    return picture
