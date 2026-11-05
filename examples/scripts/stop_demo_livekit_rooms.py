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
import asyncio
import os

from livekit import api

from alphaavatar.agents.env import init_env

init_env()


ROOM_PREFIX = "alphaavatar-demo-"


async def main():
    lkapi = api.LiveKitAPI(
        url=os.getenv("LIVEKIT_URL"),
        api_key=os.getenv("LIVEKIT_API_KEY"),
        api_secret=os.getenv("LIVEKIT_API_SECRET"),
    )

    try:
        rooms = await lkapi.room.list_rooms(api.ListRoomsRequest())

        target_rooms = [room for room in rooms.rooms if room.name.startswith(ROOM_PREFIX)]

        if not target_rooms:
            print(f"No active rooms matched prefix: {ROOM_PREFIX}")
            return

        print(f"Found {len(target_rooms)} matching room(s):")

        for room in target_rooms:
            print(f"Deleting room: {room.name}")
            await lkapi.room.delete_room(api.DeleteRoomRequest(room=room.name))

        print("All matching rooms deleted.")

    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    asyncio.run(main())
