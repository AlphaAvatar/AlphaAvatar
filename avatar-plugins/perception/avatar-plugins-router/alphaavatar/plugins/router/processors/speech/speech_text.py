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
from math import ceil

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_ABBREVIATIONS = frozenset(
    ("mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "fig", "no")
)
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


def text_weight(text: str) -> int:
    """A bounded planning budget, not tokens or measured speech duration."""
    return sum(3 if _CJK.match(char) else 1 for char in text)


def segment_target(index: int, maximum: int) -> int:
    """Reset per output: 56, 95, 162, 275, 320 weighted characters by default."""
    if index < 0 or maximum < 1:
        raise ValueError("Invalid speech segment budget")
    return min(maximum, round(56 * 1.7 ** min(index, 16)))


_LIST = re.compile(r"(?m)^[ \t]*(?:[-+*]|\d+[.)]|#{1,6}|>)[ \t]+(?:\[[ xX]\][ \t]+)?")
_ATOMIC = re.compile(
    r"(?:https?://|www\.)[^\s<>]+|[\w.+-]+@[\w.-]+\.\w+|"
    r"(?:[$€£¥]\s*)?[+−-]?\d+(?:[.,:/-]\d+)*(?:[%‰]|\s*(?:kg|km|cm|mm|ms|Hz|MHz|GHz)\b)?|"
    r"[A-Za-z](?:\.[A-Za-z])+\.?"
)
_MARKER = re.compile(r"\\.|`+|\*\*|__|~~|\*|_|\[|\]")
_HONORIFIC = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St)\.[ \t]+", re.IGNORECASE)


def _protected(text: str, *, final: bool) -> list[tuple[int, int]]:
    # The exclusive upper bound is a safe cut only after a construct is complete.
    # This is deliberately a small Markdown recognizer, not a renderer or text rewriter.
    spans = [(m.start(), m.end()) for m in _ATOMIC.finditer(text)]
    spans.extend((m.start(), m.end() + 1) for m in _LIST.finditer(text))
    for match in _HONORIFIC.finditer(text):
        name = re.match(r"[^\W\d_]+(?:['’.-][^\W\d_]+)*", text[match.end() :])
        end = match.end() + name.end() if name is not None else len(text) + 1
        spans.append((match.start(), end))
    active: dict[str, int] = {}
    skip = 0
    for match in _MARKER.finditer(text):
        start, end, marker = match.start(), match.end(), match.group()
        if start < skip or marker.startswith("\\"):
            continue
        if marker.startswith("`"):
            close = text.find(marker, end)
            skip = close + len(marker) if close >= 0 else len(text)
            spans.append((start, skip if close >= 0 else len(text) + 1))
        elif marker == "[":
            close = text.find("]", end)
            if close < 0:
                spans.append((start, len(text) + 1))
                break
            stop = close + 1
            if stop < len(text) and text[stop] == "(":
                depth, stop = 1, stop + 1
                while stop < len(text) and depth:
                    if text[stop] == "\\":
                        stop += 2
                        continue
                    depth += (text[stop] == "(") - (text[stop] == ")")
                    stop += 1
                if depth:
                    stop = len(text) + 1
            elif stop == len(text) and not final:
                stop += 1  # A link destination may arrive in the next delta.
            spans.append((start, stop))
            skip = stop
        elif marker != "]":
            previous = text[start - 1] if start else ""
            following = text[end] if end < len(text) else ""
            if marker in active and previous and not previous.isspace():
                spans.append((active.pop(marker), end))
            elif following and not following.isspace() and not previous.isalnum():
                active[marker] = start
            elif not following and not final and not previous.isalnum():
                active[marker] = start
    spans.extend((start, len(text) + 1) for start in active.values())
    if not final:
        # Retain the unfinished last token, including a decimal point/colon at the edge.
        match = re.search(r"\S+$", text)
        if match is not None and text[-1] not in "!?。！？\n" and not _CJK.match(text[-1]):
            spans.append((match.start(), len(text) + 1))
    return spans


def _sentence_dot(text: str, index: int, *, final: bool) -> bool:
    following = text[index + 1 : index + 2]
    if (not following and not final) or (following and following.isalnum()):
        return False
    prefix = re.search(r"[A-Za-z.]+$", text[:index])
    word = prefix.group() if prefix is not None else ""
    return not (
        word.lower() in _ABBREVIATIONS
        or re.fullmatch(r"(?:[A-Za-z]\.)*[A-Za-z]", word or " ")
        or re.fullmatch(r"[ \t]*\d+", text[text.rfind("\n", 0, index) + 1 : index])
    )


@dataclass(frozen=True, slots=True)
class _Boundary:
    end: int
    weight: int
    rank: int  # sentence/list item, clause, word/CJK unit


def _boundaries(text: str, *, maximum: int, final: bool) -> tuple[list[_Boundary], int, int]:
    spans = _protected(text, final=final)
    weights = [0]
    for char in text:
        weights.append(weights[-1] + (3 if _CJK.match(char) else 1))
    limit = bisect_right(weights, maximum) - 1
    cluster_ends, position = set(), 0
    for cluster in _clusters(text):
        position += len(cluster)
        cluster_ends.add(position)

    def safe(end: int) -> bool:
        return (
            end <= limit
            and end in cluster_ends
            and not any(start < end < stop for start, stop in spans)
            and any(char.isalnum() for char in text[:end])
        )

    candidates: dict[int, _Boundary] = {}
    for index, char in enumerate(text[:limit]):
        rank = None
        if char in _SENTENCE and (char != "." or _sentence_dot(text, index, final=final)):
            rank = 0
        elif char in _CLAUSE:
            previous, following = text[index - 1 : index], text[index + 1 : index + 2]
            if not (
                char in ",:" and previous.isdigit() and (not following or following.isdigit())
            ) and not (char == ":" and following == "/"):
                rank = 1
        elif char.isspace() or _CJK.match(char):
            rank = 2
        if rank is None:
            continue
        end = index + 1
        if rank < 2:
            while end < len(text) and text[end] in _CLOSERS:
                end += 1
            # Closing emphasis belongs with the completed phrase, never the next request.
            while end < len(text) and text[end] in "*_~":
                end += 1
        while end < len(text) and text[end].isspace():
            end += 1
        if safe(end):
            old = candidates.get(end)
            if old is None or rank < old.rank:
                candidates[end] = _Boundary(end, weights[end], rank)
    return list(candidates.values()), limit, weights[-1]


def chunk_end(
    text: str,
    *,
    minimum: int,
    maximum: int,
    flush: bool,
    final: bool = False,
    target: int | None = None,
    eager: bool = True,
) -> int:
    """Choose a stable, lossless prefix; hard limits take precedence over formatting.

    `final` means this buffer contains ALL remaining text, not merely an ended producer.
    A flush may release a safe prefix but never makes an ambiguous decimal a sentence.
    """
    if not 1 <= minimum <= maximum or (target is not None and not 1 <= target <= maximum):
        raise ValueError("Invalid speech text limits")
    if not text:
        return 0
    target = maximum if target is None else target
    candidates, limit, total = _boundaries(text, maximum=maximum, final=final)
    if final and total <= maximum:
        return len(text)

    ready = flush or total >= target
    lower = minimum if eager or flush else max(minimum, target // 2)
    upper = min(maximum, target + max(24, ceil(target * 0.35)))
    usable = [point for point in candidates if lower <= point.weight <= upper]
    if not ready:
        usable = [point for point in usable if eager and point.rank == 0]
    if not flush and total < maximum:
        usable = [point for point in usable if point.rank < 2]
    if usable:
        selected = min(usable, key=lambda point: (point.rank, abs(point.weight - target)))
        # Avoid manufacturing a small final tail when it can be kept with this segment.
        if final and total - selected.weight < max(minimum, 48):
            earlier = [p for p in usable if total - p.weight >= max(minimum, 48)]
            if earlier:
                selected = min(earlier, key=lambda point: (point.rank, abs(point.weight - target)))
        return selected.end
    if not flush and total < maximum:
        return 0
    if candidates:
        # Underflow/flush may use a short complete phrase rather than stall indefinitely.
        return min(candidates, key=lambda point: (point.rank, abs(point.weight - target))).end
    if total < maximum:
        return 0

    # Pathological unbroken text still has a finite bound. Do not bisect a Unicode cluster.
    end = 0
    for cluster in _clusters(text[: limit + 16]):
        if end + len(cluster) > limit:
            break
        end += len(cluster)
    if not end:
        raise ValueError("A speech text cluster exceeds the segment limit")
    # At a provisional edge, hold the last cluster until lookahead or finality confirms it.
    if end == len(text) and not final:
        return 0
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
