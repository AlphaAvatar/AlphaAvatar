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
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from alphaavatar.core.env import EnvAnnotation, EnvObservation


@dataclass
class EnvObservationStore:
    observations: list[EnvObservation] = field(default_factory=list)

    observation_ids: set[str] = field(default_factory=set)
    consumed_by: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    pending_annotations: dict[str, list[EnvAnnotation]] = field(default_factory=dict)

    annotation_renderers: list[Callable[[EnvObservation, EnvAnnotation], None]] = field(
        default_factory=list
    )

    def _attach_annotation(
        self,
        observation: EnvObservation,
        annotation: EnvAnnotation,
    ) -> None:
        observation.add_annotation(
            annotation,
            renderers=self.annotation_renderers,
        )

    def add_observation(self, observation: EnvObservation) -> None:
        if observation.observation_id in self.observation_ids:
            return

        pending_keys = [f"observation:{observation.observation_id}"]

        if observation.frame_id:
            pending_keys.append(f"frame:{observation.frame_id}")

        for key in pending_keys:
            pending = self.pending_annotations.pop(key, [])
            for annotation in pending:
                self._attach_annotation(observation, annotation)

        self.observations.append(observation)
        self.observation_ids.add(observation.observation_id)
        self.observations.sort(key=lambda x: x.timestamp)

    def add_annotation(self, annotation: EnvAnnotation) -> None:
        if annotation.observation_id:
            target_key = f"observation:{annotation.observation_id}"

            for obs in reversed(self.observations):
                if obs.observation_id == annotation.observation_id:
                    self._attach_annotation(obs, annotation)
                    return

            self.pending_annotations.setdefault(target_key, []).append(annotation)
            return

        if annotation.frame_id:
            target_key = f"frame:{annotation.frame_id}"

            for obs in reversed(self.observations):
                if obs.frame_id == annotation.frame_id:
                    self._attach_annotation(obs, annotation)
                    return

            self.pending_annotations.setdefault(target_key, []).append(annotation)
            return

        raise ValueError("EnvAnnotation must include either observation_id or frame_id.")

    def add_annotation_renderer(
        self,
        renderer: Callable[[EnvObservation, EnvAnnotation], None],
    ) -> None:
        if renderer not in self.annotation_renderers:
            self.annotation_renderers.append(renderer)

    def take_pending(
        self,
        *,
        consumer_id: str,
        require_payload: bool = True,
    ) -> list[EnvObservation]:
        consumed = self.consumed_by[consumer_id]

        return [
            obs
            for obs in self.observations
            if obs.observation_id not in consumed and (obs.has_payload or not require_payload)
        ]

    def commit(
        self,
        *,
        consumer_id: str,
        observations: list[EnvObservation],
        clear_payload: bool = False,
    ) -> None:
        consumed = self.consumed_by[consumer_id]

        for obs in observations:
            if obs.observation_id not in self.observation_ids:
                continue

            consumed.add(obs.observation_id)

            if clear_payload:
                obs.clear_payload()

    def prune(
        self,
        *,
        keep_last: int = 600,
        keep_persisted_evidence: bool = True,
        max_persisted_evidence: int = 600,
    ) -> None:
        if keep_last <= 0:
            keep_last = 1

        if len(self.observations) <= keep_last:
            self.prune_pending_annotations()
            return

        old_items = self.observations[:-keep_last]
        recent_items = self.observations[-keep_last:]

        if keep_persisted_evidence:
            persisted_old_items = [obs for obs in old_items if obs.has_persisted_evidence]

            for obs in persisted_old_items:
                obs.clear_payload()

            if max_persisted_evidence > 0:
                persisted_old_items = persisted_old_items[-max_persisted_evidence:]

            kept_items = persisted_old_items + recent_items
        else:
            kept_items = recent_items

        kept_ids = {obs.observation_id for obs in kept_items}

        self.observations = kept_items
        self.observation_ids = kept_ids

        for consumer_id in list(self.consumed_by.keys()):
            self.consumed_by[consumer_id] = {
                obs_id for obs_id in self.consumed_by[consumer_id] if obs_id in kept_ids
            }

        self.prune_pending_annotations()

    def prune_pending_annotations(
        self,
        *,
        keep_last_per_target: int = 16,
        keep_last_targets: int = 512,
    ) -> None:
        if keep_last_per_target <= 0 or keep_last_targets <= 0:
            self.pending_annotations.clear()
            return

        for target_key, annotations in list(self.pending_annotations.items()):
            if len(annotations) > keep_last_per_target:
                self.pending_annotations[target_key] = annotations[-keep_last_per_target:]

        if len(self.pending_annotations) > keep_last_targets:
            overflow = len(self.pending_annotations) - keep_last_targets
            for target_key in list(self.pending_annotations.keys())[:overflow]:
                self.pending_annotations.pop(target_key, None)
