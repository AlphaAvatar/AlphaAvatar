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
import base64
import io
import wave
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import quoteattr

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
)

from alphaavatar.agents.providers.schema import (
    ModelAudioPart,
    ModelImagePart,
    ModelInput,
    ModelInputMessage,
    ModelRole,
    ModelTemporalPart,
    ModelTextPart,
    ProviderTaskConfig,
)
from alphaavatar.core.env import (
    EnvObservation,
    ObservationKind,
    PerceptionSourceRef,
)
from alphaavatar.core.media import (
    AudioFrame,
    PayloadFormat,
    PayloadFormatUnavailable,
    PayloadView,
)


@dataclass(frozen=True, slots=True)
class _AudioPiece:
    observation: EnvObservation
    sample_rate: int
    num_channels: int
    data: bytes


@dataclass(frozen=True, slots=True)
class _AudioTrack:
    source: PerceptionSourceRef
    start_ns: int
    end_ns: int
    wav_bytes: bytes


class LangChainGeminiInputAdapter:
    """
    Convert AlphaAvatar ModelInput to LangChain Gemini messages.

    Temporal audio is sent as one continuous WAV track per source and window,
    not one independent audio block per fixed slice.
    """

    _VISUAL_KINDS = {
        ObservationKind.VIDEO_FRAME,
        ObservationKind.SCREEN_FRAME,
    }

    _AUDIO_KINDS = {
        ObservationKind.AUDIO_FRAME,
        ObservationKind.AUDIO_SEGMENT,
    }

    async def adapt(
        self,
        model_input: ModelInput,
        *,
        config: ProviderTaskConfig,
    ) -> list[Any]:
        return await asyncio.to_thread(
            self._adapt_sync,
            model_input,
            config,
        )

    @staticmethod
    def _attr(value: object) -> str:
        return quoteattr(str(value))

    @staticmethod
    def _relative_sec(
        temporal: ModelTemporalPart,
        monotonic_ns: int,
    ) -> float:
        start_ns = temporal.alignment.time_range.start.monotonic_ns
        return max(0, monotonic_ns - start_ns) / 1_000_000_000

    @classmethod
    def _relative_label(
        cls,
        temporal: ModelTemporalPart,
        monotonic_ns: int,
    ) -> str:
        return f"+{cls._relative_sec(temporal, monotonic_ns):.2f}s"

    @staticmethod
    def _audio_piece(observation: EnvObservation) -> _AudioPiece | None:
        payload = observation.payload

        if payload is None:
            return None

        if observation.kind == ObservationKind.AUDIO_FRAME:
            try:
                frame = payload.get(
                    PayloadFormat.AUDIO_FRAME,
                    view=PayloadView.RAW,
                    fallback_to_raw=False,
                )
            except PayloadFormatUnavailable:
                return None

            if not isinstance(frame, AudioFrame):
                return None

            return _AudioPiece(
                observation=observation,
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
                data=frame.data,
            )

        if observation.kind != ObservationKind.AUDIO_SEGMENT:
            return None

        try:
            data = payload.get(
                PayloadFormat.AUDIO_PCM16_BYTES,
                view=PayloadView.RAW,
                fallback_to_raw=False,
            )
        except PayloadFormatUnavailable:
            return None

        sample_rate = getattr(payload, "sample_rate", None)
        num_channels = getattr(payload, "num_channels", None)

        if (
            not isinstance(data, bytes)
            or not isinstance(sample_rate, int)
            or not isinstance(num_channels, int)
        ):
            return None

        return _AudioPiece(
            observation=observation,
            sample_rate=sample_rate,
            num_channels=num_channels,
            data=data,
        )

    @staticmethod
    def _wav(
        pcm: bytes,
        *,
        sample_rate: int,
        num_channels: int,
    ) -> bytes:
        output = io.BytesIO()

        with wave.open(output, "wb") as wav:
            wav.setnchannels(num_channels)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm)

        return output.getvalue()

    def _build_audio_track(
        self,
        source: PerceptionSourceRef,
        pieces: list[_AudioPiece],
    ) -> _AudioTrack:
        pieces.sort(
            key=lambda item: (
                item.observation.time_range.start.monotonic_ns,
                item.observation.observation_id,
            )
        )

        first = pieces[0]
        sample_rate = first.sample_rate
        num_channels = first.num_channels
        frame_width = num_channels * 2

        if any(
            item.sample_rate != sample_rate or item.num_channels != num_channels for item in pieces
        ):
            raise ValueError("One audio source contains mixed sample rates or channels")

        if any(item.observation.source != source for item in pieces):
            raise ValueError("Audio track contains observations from multiple sources")

        start_ns = min(item.observation.time_range.start.monotonic_ns for item in pieces)
        end_ns = max(item.observation.time_range.end.monotonic_ns for item in pieces)
        total_samples = max(
            1,
            round((end_ns - start_ns) * sample_rate / 1_000_000_000),
        )
        pcm = bytearray(total_samples * frame_width)

        for item in pieces:
            offset_samples = round(
                (item.observation.time_range.start.monotonic_ns - start_ns)
                * sample_rate
                / 1_000_000_000
            )
            source_samples = len(item.data) // frame_width

            source_start = max(0, -offset_samples)
            target_start = max(0, offset_samples)
            copy_samples = min(
                source_samples - source_start,
                total_samples - target_start,
            )

            if copy_samples <= 0:
                continue

            source_byte = source_start * frame_width
            target_byte = target_start * frame_width
            size = copy_samples * frame_width

            pcm[target_byte : target_byte + size] = item.data[source_byte : source_byte + size]

        return _AudioTrack(
            source=source,
            start_ns=start_ns,
            end_ns=end_ns,
            wav_bytes=self._wav(
                bytes(pcm),
                sample_rate=sample_rate,
                num_channels=num_channels,
            ),
        )

    def _audio_tracks(
        self,
        temporal: ModelTemporalPart,
    ) -> tuple[_AudioTrack, ...]:
        observations = [
            observation
            for observation in temporal.observations
            if observation.kind in self._AUDIO_KINDS
        ]

        raw_sources = {
            observation.source
            for observation in observations
            if observation.kind == ObservationKind.AUDIO_FRAME
        }

        groups: dict[PerceptionSourceRef, list[_AudioPiece]] = {}
        for observation in observations:
            source = observation.source

            if observation.kind == ObservationKind.AUDIO_SEGMENT and source in raw_sources:
                continue

            piece = self._audio_piece(observation)

            if piece is not None:
                groups.setdefault(source, []).append(piece)

        ordered_sources = sorted(
            groups,
            key=lambda source: (
                source.source_id,
                source.source_generation,
            ),
        )

        return tuple(
            self._build_audio_track(source, groups[source])
            for source in ordered_sources
            if groups[source]
        )

    @staticmethod
    def _image_block(observation: EnvObservation) -> dict[str, Any] | None:
        payload = observation.payload

        if payload is None:
            return None

        try:
            image = payload.get(
                PayloadFormat.IMAGE_JPEG_BYTES,
                view=PayloadView.ANNOTATED,
                fallback_to_raw=True,
            )
        except PayloadFormatUnavailable:
            return None

        if not isinstance(image, bytes):
            return None

        return {
            "type": "image",
            "base64": base64.b64encode(image).decode(),
            "mime_type": "image/jpeg",
        }

    @staticmethod
    def _append_text(
        content: list[dict[str, Any]],
        text: str,
    ) -> None:
        if content and content[-1].get("type") == "text":
            content[-1]["text"] += f"\n{text}"
        else:
            content.append({"type": "text", "text": text})

    def _states_xml(
        self,
        temporal: ModelTemporalPart,
        *,
        boundary: str,
    ) -> str:
        states = (
            temporal.alignment.source_states_at_start
            if boundary == "start"
            else temporal.alignment.source_states_at_end
        )

        if not states:
            return f"<source_states boundary={self._attr(boundary)} />"

        lines = [f"<source_states boundary={self._attr(boundary)}>"]

        lines.extend(
            "  <source "
            f"source_id={self._attr(state.source.source_id)} "
            f"source_generation={self._attr(state.source.source_generation)} "
            f"modality={self._attr(state.modality.value)} "
            f"kind={self._attr(state.source_kind.value)} "
            f"state={self._attr(state.state.value)} "
            "/>"
            for state in states
        )

        lines.append("</source_states>")
        return "\n".join(lines)

    def _temporal_blocks(
        self,
        temporal: ModelTemporalPart,
        *,
        config: ProviderTaskConfig,
    ) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []
        tracks = self._audio_tracks(temporal)

        max_audio_sec = float(config.input_options.get("max_inline_audio_sec", 180.0))
        total_audio_sec = sum((track.end_ns - track.start_ns) / 1_000_000_000 for track in tracks)

        if total_audio_sec > max_audio_sec:
            raise ValueError(
                "Gemini inline audio exceeds configured duration: "
                f"duration={total_audio_sec:.2f}s, max={max_audio_sec:.2f}s"
            )

        alignment = temporal.alignment
        end = self._relative_label(
            temporal,
            alignment.time_range.end.monotonic_ns,
        )

        self._append_text(
            content,
            "\n".join(
                (
                    f"<temporal_input mode={self._attr(alignment.mode.value)} "
                    f'start="+0.00s" end={self._attr(end)}>',
                    "  "
                    + self._states_xml(
                        temporal,
                        boundary="start",
                    ).replace("\n", "\n  "),
                )
            ),
        )

        for track in tracks:
            self._append_text(
                content,
                "  <audio_track "
                f"source_id={self._attr(track.source.source_id)} "
                f"source_generation={self._attr(track.source.source_generation)} "
                f"start={self._attr(self._relative_label(temporal, track.start_ns))} "
                f"end={self._attr(self._relative_label(temporal, track.end_ns))}>",
            )
            content.append(
                {
                    "type": "audio",
                    "base64": base64.b64encode(track.wav_bytes).decode(),
                    "mime_type": "audio/wav",
                }
            )
            self._append_text(content, "  </audio_track>")

        for item in temporal.slices:
            start = self._relative_label(
                temporal,
                item.time_range.start.monotonic_ns,
            )
            end = self._relative_label(
                temporal,
                item.time_range.end.monotonic_ns,
            )

            self._append_text(
                content,
                "  <slice "
                f"index={self._attr(item.index)} "
                f"start={self._attr(start)} "
                f"end={self._attr(end)}>",
            )

            if tracks:
                self._append_text(
                    content,
                    f"    <audio_interval start={self._attr(start)} end={self._attr(end)} />",
                )

            for event in item.source_events:
                state = event.source_state
                if state is None:
                    continue

                at = self._relative_label(
                    temporal,
                    event.time_range.end.monotonic_ns,
                )
                reason = "" if not state.reason else f" reason={self._attr(state.reason)}"

                self._append_text(
                    content,
                    "    <source_event "
                    f"at={self._attr(at)} "
                    f"source_id={self._attr(state.source.source_id)} "
                    f"source_generation={self._attr(state.source.source_generation)} "
                    f"kind={self._attr(state.source_kind.value)} "
                    f"state={self._attr(state.state.value)}"
                    f"{reason} "
                    "/>",
                )

            for observation in item.observations:
                if observation.kind not in self._VISUAL_KINDS:
                    continue

                block = self._image_block(observation)

                if block is None:
                    continue

                captured_at = self._relative_label(
                    temporal,
                    observation.time_range.end.monotonic_ns,
                )

                self._append_text(
                    content,
                    "    <visual_evidence "
                    f"observation_id={self._attr(observation.observation_id)} "
                    f"source_id={self._attr(observation.source.source_id)} "
                    f"source_generation={self._attr(observation.source.source_generation)} "
                    f"captured_at={self._attr(captured_at)}>",
                )
                content.append(block)
                self._append_text(content, "    </visual_evidence>")

            self._append_text(content, "  </slice>")

        self._append_text(
            content,
            "  "
            + self._states_xml(
                temporal,
                boundary="end",
            ).replace("\n", "\n  "),
        )
        self._append_text(content, "</temporal_input>")

        return content

    def _message_content(
        self,
        message: ModelInputMessage,
        *,
        config: ProviderTaskConfig,
    ) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []

        for part in message.parts:
            if isinstance(part, ModelTextPart):
                self._append_text(content, part.text)

            elif isinstance(part, ModelImagePart):
                block = self._image_block(part.observation)
                if block is not None:
                    content.append(block)

            elif isinstance(part, ModelAudioPart):
                raise NotImplementedError("Direct ModelAudioPart is not used by ENV Memory")

            elif isinstance(part, ModelTemporalPart):
                content.extend(
                    self._temporal_blocks(
                        part,
                        config=config,
                    )
                )

        return content

    def _adapt_sync(
        self,
        model_input: ModelInput,
        config: ProviderTaskConfig,
    ) -> list[Any]:
        messages = []

        for item in model_input.items:
            if not isinstance(item, ModelInputMessage):
                raise TypeError(
                    "LangChainGeminiInputAdapter currently accepts ModelInputMessage items only"
                )

            content = self._message_content(
                item,
                config=config,
            )

            if item.role in {
                ModelRole.SYSTEM,
                ModelRole.DEVELOPER,
            }:
                text = "\n".join(block["text"] for block in content if block.get("type") == "text")
                messages.append(SystemMessage(content=text))

            elif item.role == ModelRole.ASSISTANT:
                messages.append(AIMessage(content=content))

            else:
                messages.append(HumanMessage(content=content))

        return messages
