# Copyright 2025 AlphaAvatar project
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

import os
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from alphaavatar.agents.utils.files.user_dirs import (
    UserPath,
    UserPathSnapshot,
    migrate_user_path,
    mk_user_dirs,
)
from alphaavatar.agents.utils.files.work_dirs import (
    AvatarPath,
    SessionPath,
    mk_avatar_dirs,
    mk_session_dirs,
)
from alphaavatar.agents.utils.id_utils import get_md5_id, sanitize_id
from alphaavatar.agents.utils.time_utils import TimeStamp


class ParticipantUpdateResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    participant_id: str

    old_user_id: str | None = None
    new_user_id: str

    old_user_path: UserPathSnapshot | None = None
    new_user_path: UserPathSnapshot | None = None

    changed: bool = False


class ParticipantInfo(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Participant Identity
    participant_id: str

    # Room Identity
    room_id: str
    room_type: str

    # Temporary or stable user id.
    user_id: str
    resolved_user_id: str | None = None
    identity_confidence: float | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    timestamp: TimeStamp
    user_path: UserPath | None = None

    @property
    def effective_user_id(self) -> str | None:
        return self.resolved_user_id or self.user_id


class SessionRuntime(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Session ID for the current session.",
    )

    session_timeout: int = Field(
        default=300,
        description="Session timeout in seconds.",
    )

    primary_participant_id: str | None = None
    participants: dict[str, ParticipantInfo] = Field(default_factory=dict)

    avatar_path: AvatarPath | None = None
    session_path: SessionPath | None = None

    pending_user_path_migrations: list[ParticipantUpdateResult] = Field(default_factory=list)

    @property
    def primary_participant(self) -> ParticipantInfo | None:
        if self.primary_participant_id is None:
            return None
        return self.participants.get(self.primary_participant_id)

    @property
    def primary_user_id(self) -> str | None:
        participant = self.primary_participant
        if participant is None:
            return None
        return participant.effective_user_id

    @property
    def primary_user_path(self) -> UserPath | None:
        participant = self.primary_participant
        if participant is None:
            return None
        return participant.user_path

    def model_post_init(self, __context):
        work_dir = os.getenv("AVATAR_WORK_DIR", "")
        self.avatar_path = mk_avatar_dirs(work_dir)
        self.session_path = mk_session_dirs(self.avatar_path, self.session_id)

    def add_participant(
        self,
        *,
        user_id: str,
        room_identity: str,
        room_type: str | None = None,
        timestamp: TimeStamp | None = None,
        metadata: dict[str, Any] | None = None,
        primary: bool = False,
    ) -> ParticipantInfo:
        uid = sanitize_id(user_id)
        rid = sanitize_id(room_identity)
        pid = get_md5_id([rid, timestamp.time_str])

        if pid in self.participants:
            participant = self.participants[pid]
            if room_type:
                participant.room_type = room_type
            if timestamp:
                participant.timestamp = timestamp
            if metadata:
                participant.metadata.update(metadata)
            if uid and participant.user_id != uid:
                self.update_participant_user_id(pid, uid)
        else:
            participant = ParticipantInfo(
                participant_id=pid,
                room_id=rid,
                room_type=room_type,
                user_id=uid,
                timestamp=timestamp,
                metadata=metadata or {},
            )

            if uid:
                participant.user_path = mk_user_dirs(
                    users_dir=self.avatar_path.users_dir,
                    user_id=uid,
                )

            self.participants[pid] = participant

        if primary or self.primary_participant_id is None:
            self.primary_participant_id = pid

        return participant

    def get_participant(
        self, *, participant_id: str | None = None, user_id: str | None = None
    ) -> ParticipantInfo | None:
        if participant_id:
            return self.participants.get(sanitize_id(participant_id))

        if user_id:
            uid = sanitize_id(user_id)
            for pid in self.participants:
                if self.participants[pid].effective_user_id == uid:
                    return self.participants[pid]

        return None

    def update_participant_user_id(
        self,
        *,
        participant_id: str,
        user_id: str,
        confidence: float | None = None,
    ) -> ParticipantUpdateResult:
        pid = sanitize_id(participant_id)

        if pid not in self.participants:
            self.add_participant(participant_id=pid)

        participant = self.participants[pid]

        old_user_id = participant.effective_user_id
        old_user_path_snapshot = (
            participant.user_path.snapshot() if participant.user_path is not None else None
        )

        # Same resolved user, no path migration needed.
        if old_user_id == user_id and participant.user_path is not None:
            if confidence is not None:
                participant.identity_confidence = confidence

            return ParticipantUpdateResult(
                participant_id=pid,
                old_user_id=old_user_id,
                new_user_id=user_id,
                old_user_path=old_user_path_snapshot,
                new_user_path=participant.user_path.snapshot(),
                changed=False,
            )

        participant.user_id = user_id
        participant.resolved_user_id = user_id

        if confidence is not None:
            participant.identity_confidence = confidence

        new_user_path = mk_user_dirs(
            users_dir=self.avatar_path.users_dir,
            user_id=user_id,
        )

        if participant.user_path is None:
            participant.user_path = new_user_path
        else:
            # Important:
            # Mutate existing UserPath object in place so plugins holding the same
            # UserPath reference can see the updated path immediately.
            participant.user_path.update_from(new_user_path)

        new_user_path_snapshot = participant.user_path.snapshot()

        result = ParticipantUpdateResult(
            participant_id=pid,
            old_user_id=old_user_id,
            new_user_id=user_id,
            old_user_path=old_user_path_snapshot,
            new_user_path=new_user_path_snapshot,
            changed=True,
        )

        self.pending_user_path_migrations.append(result)

        return result

    def flush_user_path_migrations(self, *, remove_old: bool = False) -> None:
        for item in self.pending_user_path_migrations:
            if not item.changed:
                continue

            if item.old_user_path is None or item.new_user_path is None:
                continue

            if item.old_user_path.user_root.resolve() == item.new_user_path.user_root.resolve():
                continue

            migrate_user_path(
                old_user_path=item.old_user_path,
                new_user_path=item.new_user_path,
                remove_old=remove_old,
            )

        self.pending_user_path_migrations.clear()
