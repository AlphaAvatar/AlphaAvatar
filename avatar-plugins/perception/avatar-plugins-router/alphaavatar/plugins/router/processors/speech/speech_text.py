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

import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_ABBREVIATIONS = frozenset(("mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc"))
_CLOSERS = frozenset("\"'”’）)]}")
_SENTENCE = frozenset(".!?。！？\n")
_CLAUSE = frozenset(",;:，；：、—")


def _clusters(text: str) -> tuple[str, ...]:
    # Keep combining marks, emoji modifiers, ZWJ sequences and flag pairs together.
    out: list[str] = []
    for char in text:
        mark = unicodedata.category(char).startswith("M") or "\U0001f3fb" <= char <= "\U0001f3ff"
        flag = "\U0001f1e6" <= char <= "\U0001f1ff"
        if out and (
            mark
            or char == "\u200d"
            or out[-1].endswith("\u200d")
            or (flag and len(out[-1]) == 1 and "\U0001f1e6" <= out[-1] <= "\U0001f1ff")
        ):
            out[-1] += char
        else:
            out.append(char)
    return tuple(out)


def speech_units(text: str) -> tuple[str, ...]:
    """Lossless word/CJK units, not a linguistic tokenizer or measured word timestamps."""
    tokens: list[str] = []
    word = ""
    clusters = _clusters(text)
    for index, cluster in enumerate(clusters):
        if (
            word
            and word[-1].isdigit()
            and cluster in (".", ",", ":")
            and index + 1 < len(clusters)
            and clusters[index + 1][0].isdigit()
        ):
            word += cluster
            continue
        latin = cluster[0].isalnum() and not _CJK.match(cluster)
        if latin or (word and cluster in ("'", "’", "-", "_")):
            word += cluster
            continue
        if word:
            tokens.append(word)
            word = ""
        tokens.append(cluster)
    if word:
        tokens.append(word)
    units: list[str] = []
    spaces = ""
    for token in tokens:
        if token.isspace():
            spaces += token
        elif units and not spaces and all(unicodedata.category(c)[0] in "PM" for c in token):
            units[-1] += token
        else:
            units.append(spaces + token)
            spaces = ""
    if spaces:
        if units:
            units[-1] += spaces
        else:
            units.append(spaces)
    return tuple(units)


def chunk_end(text: str, *, minimum: int, maximum: int, flush: bool, final: bool = False) -> int:
    """Prefer sentences, then clauses, then complete words; only the hard limit splits tokens."""
    if not text:
        return 0

    # Bound expected speech, not just code points: CJK characters are not English letters.
    used = 0
    for index, char in enumerate(text[:maximum]):
        cost = 3 if _CJK.match(char) else 1
        if used + cost > maximum:
            maximum = max(1, index)
            break
        used += cost

    minimum = min(minimum, maximum)
    limit = min(len(text), maximum)
    sentence = 0
    for index, char in enumerate(text[:limit]):
        if char not in _SENTENCE:
            continue

        if char == ".":
            prefix = text[:index].rsplit(maxsplit=1)[-1] if text[:index].strip() else ""
            # Decimals, domains, initialisms and common honorifics are not sentence cuts.
            if (
                (index + 1 < len(text) and text[index + 1].isalnum())
                or prefix.lower().strip("(\"'") in _ABBREVIATIONS
                or re.fullmatch(r"(?:[A-Za-z]\.)*[A-Za-z]", prefix)
            ):
                continue

        end = index + 1
        while end < limit and (text[end] in _CLOSERS or text[end].isspace()):
            end += 1
        if text[:end].strip() and end >= minimum:
            sentence = end
            break

    if sentence:
        return sentence
    if len(text) < maximum and not flush:
        return 0
    if flush and len(text) <= maximum:
        if not final and text[-1].isalnum() and not _CJK.match(text[-1]):
            match = re.search(r"\S+$", text)
            return match.start() if match is not None else 0
        return len(text)

    # Prefer a natural clause near the budget, not every early comma.
    clause = 0
    for index, char in enumerate(text[:limit]):
        if index + 1 < minimum or char not in _CLAUSE:
            continue
        if char in ",:" and index and index + 1 < len(text):
            if text[index - 1].isdigit() and text[index + 1].isdigit():
                continue
            if char == ":" and text[index + 1] == "/":
                continue
        clause = index + 1
    if clause:
        return clause

    end = 0
    for unit in speech_units(text):
        if end + len(unit) > maximum:
            break
        end += len(unit)
    if end >= minimum:
        return end

    # Unbroken input is still bounded. Never cut through the supported Unicode clusters.
    end = 0
    for cluster in _clusters(text):
        if end + len(cluster) > maximum:
            break
        end += len(cluster)
    if not end:
        raise ValueError("A speech text cluster exceeds the segment limit")
    return end


@dataclass(frozen=True, slots=True)
class SpeechTiming:
    units: tuple[str, ...]
    cumulative: tuple[float, ...]

    @classmethod
    def create(cls, text: str) -> SpeechTiming:
        units = speech_units(text)
        cumulative: list[float] = []
        total = 0.0
        for unit in units:
            # CJK characters usually carry more speech than one Latin character.
            weight = sum(3.0 if _CJK.match(c) else 1.0 for c in unit if c.isalnum())
            total += max(1.0, weight)
            cumulative.append(total)
        return cls(units, tuple(cumulative))

    def count(self, ratio: float) -> int:
        if not self.units or ratio <= 0:
            return 0
        if ratio >= 1:
            return len(self.units)
        return bisect_right(self.cumulative, self.cumulative[-1] * ratio + 1e-9)

    def ratio(self, count: int) -> float:
        return self.cumulative[count - 1] / self.cumulative[-1] if count else 0.0
