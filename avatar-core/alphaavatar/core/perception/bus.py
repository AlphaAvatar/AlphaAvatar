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
from collections.abc import Callable

from alphaavatar.core.env import EnvAnnotation, EnvObservation
from alphaavatar.core.perception.event import FrameEvent
from alphaavatar.core.perception.store import EnvObservationStore


class PerceptionBus:
    def __init__(self) -> None:
        self._store = EnvObservationStore()

    @property
    def store(self) -> EnvObservationStore:
        return self._store

    def add_annotation_renderer(
        self,
        renderer: Callable[[EnvObservation, EnvAnnotation], None],
    ) -> None:
        self._store.add_annotation_renderer(renderer)

    def publish_frame(self, event: FrameEvent) -> EnvObservation:
        observation = event.to_observation()
        self._store.add_observation(observation)
        return observation

    def publish_observation(self, observation: EnvObservation) -> None:
        self._store.add_observation(observation)

    def publish_annotation(self, annotation: EnvAnnotation) -> None:
        self._store.add_annotation(annotation)

    def take_pending_observations(
        self,
        *,
        consumer_id: str,
        require_payload: bool = True,
    ) -> list[EnvObservation]:
        return self._store.take_pending(
            consumer_id=consumer_id,
            require_payload=require_payload,
        )

    def commit_observations(
        self,
        *,
        consumer_id: str,
        observations: list[EnvObservation],
        clear_payload: bool = False,
    ) -> None:
        self._store.commit(
            consumer_id=consumer_id,
            observations=observations,
            clear_payload=clear_payload,
        )

    def prune_observations(self) -> None:
        self._store.prune()
