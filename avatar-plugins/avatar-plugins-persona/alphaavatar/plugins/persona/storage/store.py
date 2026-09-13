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
import json
import os

import numpy as np

from alphaavatar.agents.persona import PersonaCache
from alphaavatar.agents.persona.enums import VectorRunnerOP
from alphaavatar.agents.persona.schemas import UserProfile
from alphaavatar.agents.runtime import AvatarRuntime

from ..profile import UserProfileDetails
from ..profile.serialization import flatten_profile_items, rebuild_profile_items
from .runtime_state import RuntimeStateStore


class PersonaStore:
    def __init__(self, *, runtime: AvatarRuntime) -> None:
        self._runtime = runtime
        self._runtime_state_store = RuntimeStateStore()

    @property
    def vdb_inference_method(self) -> str:
        method = os.getenv("PERSONA_VDB_INFERENCE_METHOD")
        if not method:
            raise RuntimeError("PERSONA_VDB_INFERENCE_METHOD is not configured.")
        return method

    @property
    def users_dir(self):
        return self._runtime.session.avatar_path.users_dir

    async def _infer(self, payload: dict, *, timeout: float | None) -> bytes | None:
        return await asyncio.wait_for(
            self._runtime.inference.do_inference(
                self.vdb_inference_method,
                json.dumps(payload).encode(),
            ),
            timeout=timeout,
        )

    async def load(self, *, uid: str, timeout: float | None = 3) -> UserProfile:
        result = await self._infer(
            {"op": VectorRunnerOP.load, "param": {"user_id": uid}},
            timeout=timeout,
        )
        if result is None:
            raise RuntimeError(f"Persona store returned no load result uid={uid!r}")

        data = json.loads(result.decode())

        details = (
            UserProfileDetails(**rebuild_profile_items(data["details_items"]))
            if data.get("details_items")
            else None
        )

        runtime_state = await self._runtime_state_store.load(
            users_dir=self.users_dir,
            uid=uid,
        )

        return UserProfile(
            details=details,
            runtime_state=runtime_state,
            speaker_vector=data.get("speaker_vector"),
            face_vector=data.get("face_vector"),
        )

    async def search_speaker_vector(
        self,
        *,
        speaker_vector: np.ndarray,
        threshold: float,
        timeout: float | None = None,
    ) -> str | None:
        result = await self._infer(
            {
                "op": VectorRunnerOP.search_speaker_vector,
                "param": {
                    "speaker_vector": speaker_vector.tolist(),
                    "threshold": threshold,
                },
            },
            timeout=timeout,
        )
        if not result:
            return None

        uid = json.loads(result.decode()).get("user_id")
        return str(uid) if uid else None

    async def search_face_vector(
        self,
        *,
        face_vector: np.ndarray,
        threshold: float,
        timeout: float | None = None,
    ) -> str | None:
        result = await self._infer(
            {
                "op": VectorRunnerOP.search_face_vector,
                "param": {
                    "face_vector": face_vector.tolist(),
                    "threshold": threshold,
                },
            },
            timeout=timeout,
        )
        if not result:
            return None

        uid = json.loads(result.decode()).get("user_id")
        return str(uid) if uid else None

    async def _save_vdb(
        self,
        *,
        uid: str,
        persona: PersonaCache,
        timeout: float | None,
    ) -> None:
        details_items = (
            flatten_profile_items(uid, persona.profile_details.model_dump())
            if persona.profile_details is not None
            else None
        )
        speaker_vector = (
            persona.speaker_vector.tolist() if persona.speaker_vector is not None else None
        )
        face_vector = persona.face_vector.tolist() if persona.face_vector is not None else None

        if not details_items and speaker_vector is None and face_vector is None:
            return

        result = await self._infer(
            {
                "op": VectorRunnerOP.save,
                "param": {
                    "user_id": uid,
                    "details_items": details_items,
                    "speaker_vector": speaker_vector,
                    "face_vector": face_vector,
                },
            },
            timeout=timeout,
        )
        if not result:
            raise RuntimeError(f"Persona VDB save returned no result uid={uid!r}")

    async def save(
        self,
        *,
        uid: str,
        persona: PersonaCache,
        timeout: float | None = 15,
    ) -> None:
        operations = []

        if persona.runtime_state is not None:
            operations.append(
                self._runtime_state_store.save(
                    users_dir=self.users_dir,
                    uid=uid,
                    runtime_state=persona.runtime_state,
                )
            )

        operations.append(
            self._save_vdb(
                uid=uid,
                persona=persona,
                timeout=timeout,
            )
        )

        results = await asyncio.gather(*operations, return_exceptions=True)
        errors: list[Exception] = []

        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                errors.append(result)

        if errors:
            raise ExceptionGroup(f"Failed to save persona uid={uid!r}", errors)
