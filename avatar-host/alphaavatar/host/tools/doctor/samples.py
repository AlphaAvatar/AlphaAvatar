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
offline by ``scripts/quality/doctor_samples.py``); the picture is drawn here. A reply is judged
whole: it must equal one of the task's answers once case, surrounding space and punctuation
are set aside, or, for the card, state its color in a short sentence ("The card is green.").
A question, a negation, a hedge, another color, or another number that merely contains the
right digit, does not pass. The answer to the card question depends on the picture alone.

The card question is one sentence, so that what it checks is the picture; the sum question is
two, so that the transcript shows whether a sentence was lost, and where.
"""

from __future__ import annotations

import hashlib
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
_SENTENCE_PAUSE_SEC = 0.15  # A quieter stretch at least this long parts two sentences.
# What makes a stated answer unclear: a negation, or not quite saying it.
_HEDGES = frozenset(
    "not no never isn't isnt maybe perhaps probably possibly might may could guess think "
    "seems looks like unsure either or".split()
)
COLORS = frozenset(
    "red orange yellow green blue purple violet pink brown black white gray grey".split()
)


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

    @property
    def spans(self) -> tuple[tuple[float, float], ...]:
        """Its voiced stretches, in seconds: a sentence each, where pauses part them."""
        return voiced_spans(self.pcm)


@dataclass(frozen=True, slots=True)
class Task:
    name: str
    prompt: str  # What the recording asks, word for word
    answers: tuple[str, ...]  # The whole answer must be one of these, or state ``stated``
    # Each sentence of the prompt, as word groups: one word of each group in the transcript.
    sentences: tuple[tuple[tuple[str, ...], ...], ...]
    speech: str  # Recording name
    screen: bool = False  # The card picture on a shared screen while the question is asked
    covers: str = ""  # What it shows when it passes, in words
    stated: str | None = None  # A short sentence may state this answer, as no rival does
    rivals: frozenset[str] = frozenset()  # The other answers of its kind

    def answered(self, answer: str) -> bool:
        plain = _plain(answer)
        if plain in self.answers:
            return True
        return self.stated is not None and _states(plain, self.stated, self.rivals)

    def heard_sentences(self, transcript: str) -> tuple[bool, ...]:
        """Whether each sentence's words are in the transcript."""
        words = set(_WORD.findall(transcript.lower()))
        return tuple(
            all(words.intersection(group) for group in sentence) for sentence in self.sentences
        )

    def heard(self, transcript: str) -> bool:
        return all(self.heard_sentences(transcript))


def _states(plain: str, value: str, rivals: frozenset[str]) -> bool:
    """A short sentence that states ``value``: no question, negation, hedge or rival."""
    if "?" in plain or len(plain) > 80:
        return False
    words = _WORD.findall(plain)
    if value not in words or any(w in _HEDGES or w.endswith("n't") for w in words):
        return False
    return not (set(words) & (rivals - {value}))


# The picture arrives as screen-share frames: it has no face, and a camera would make the
# turn wait for visual addressing that a picture of a card cannot give.
VOICE_VISION = Task(
    "voice_vision",
    "What color is the card on my screen?",
    answers=("green", "绿", "绿色"),
    sentences=((("color", "colour"), ("card",)),),
    speech="card_question",
    screen=True,
    covers="Speech and screen frames in one model request",
    stated="green",
    rivals=COLORS,
)
VOICE = Task(
    "voice",
    "What is two plus three? Answer with just the number.",
    answers=("5", "five", "五"),
    sentences=((("two", "2"), ("three", "3")), (("answer",), ("number",))),
    speech="sum_question",
    covers="Both sentences transcribed, the sum answered",
)


def identity(name: str) -> str:
    """A recording by name and content, so reports made with different samples tell apart."""
    return f"{name} sha256:{hashlib.sha256(speech(name).pcm).hexdigest()[:12]}"


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


def _voiced(pcm: bytes) -> np.ndarray:
    """Whether each window is louder than a fraction of the loudest one."""
    window = int(SAMPLE_RATE * _VOICED_WINDOW_SEC)
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    count = samples.size // window
    if not count:
        return np.zeros(0, dtype=bool)
    rms = np.sqrt(np.mean(samples[: count * window].reshape(count, window) ** 2, axis=1))
    return rms >= rms.max() * _VOICED_FLOOR


def voiced_spans(pcm: bytes) -> tuple[tuple[float, float], ...]:
    """The voiced stretches, in seconds, parted by pauses of at least a sentence's."""
    voiced = _voiced(pcm)
    spans: list[list[float]] = []
    pause = round(_SENTENCE_PAUSE_SEC / _VOICED_WINDOW_SEC)
    for index in np.flatnonzero(voiced):
        start, end = index * _VOICED_WINDOW_SEC, (index + 1) * _VOICED_WINDOW_SEC
        if spans and index - round(spans[-1][1] / _VOICED_WINDOW_SEC) < pause:
            spans[-1][1] = end
        else:
            spans.append([start, end])
    # A click is no sentence: a stretch shorter than the pause that parts them is left out.
    return tuple(
        (round(float(a), 3), round(float(b), 3)) for a, b in spans if b - a >= _SENTENCE_PAUSE_SEC
    )


def voiced_end(pcm: bytes) -> float:
    """The end of the last window louder than a fraction of the loudest one, in seconds."""
    voiced = np.flatnonzero(_voiced(pcm))
    return float((voiced[-1] + 1) * _VOICED_WINDOW_SEC) if voiced.size else 0.0


def card_picture(width: int = 640, height: int = 360) -> np.ndarray:
    """A green card on a grey desk, as BGR pixels."""
    picture = np.full((height, width, 3), (128, 128, 128), dtype=np.uint8)
    top, left = height // 4, width // 3
    picture[top : height - top, left : width - left] = (255, 255, 255)
    picture[top + 8 : height - top - 8, left + 8 : width - left - 8] = (40, 170, 40)
    return picture
