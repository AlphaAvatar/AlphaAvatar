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

import asyncio
import json

from alphaavatar.agents.memory import MemoryItem, VectorRunnerOP

from .graph import save_memory_graph_stubs
from .log import logger
from .memory_markdown import save_memory_items_to_markdown
from .memory_op import flatten_records


class MemoryPersistenceMixin:
    """Writing memory records to the VDB, markdown backup and graph stubs.

    Split out of MemoryRuntime for file size only; behaviour is unchanged.
    Requires from the host class: `inference_executor`, `vdb_inference_method`,
    `session_runtime`, `memory_state`, `_save_lock`.
    """

    async def _save_to_vdb(self, *, memory_items: list[dict], timeout: float) -> bool:
        json_data = {
            "op": VectorRunnerOP.save,
            "param": {"memory_items": memory_items},
        }

        try:
            result = await asyncio.wait_for(
                self.inference_executor.do_inference(
                    self.vdb_inference_method,
                    json.dumps(json_data).encode(),
                ),
                timeout=timeout,
            )
        except TimeoutError:
            logger.error("Memory SAVE timeout!")
            return False
        except Exception:
            logger.exception("Memory SAVE failed")
            return False

        if result is None:
            logger.warning("Memory SAVE failed, result is None!")
            return False

        try:
            payload = json.loads(result.decode())
        except Exception:
            logger.exception("Memory SAVE returned invalid JSON")
            return False

        if payload.get("error") is not None:
            logger.error(
                "Memory SAVE failed, because: %s",
                payload["error"],
            )
            return False

        logger.info(
            "Memory SAVE success: %s",
            {key: value for key, value in payload.items() if key != "error"},
        )
        return True

    async def _persist_memory_items(
        self,
        items: list[MemoryItem],
        *,
        timeout: float,
    ) -> bool:
        async with self._save_lock:
            selected = sorted(
                (item for item in items if item.updated),
                key=lambda item: item.created_at,
            )

            if not selected:
                return True

            flattened = flatten_records(selected, include_topic=True)

            if not flattened:
                return True

            avatar_path = self.session_runtime.avatar_path
            session_path = self.session_runtime.session_path

            if avatar_path is None:
                raise RuntimeError("SessionRuntime.avatar_path is not initialized")

            if session_path is None:
                raise RuntimeError("SessionRuntime.session_path is not initialized")

            markdown_result, graph_result = await asyncio.gather(
                asyncio.to_thread(
                    save_memory_items_to_markdown,
                    avatar_memory_path=avatar_path.memory_dir,
                    session_memory_path=session_path.memory_dir,
                    memory_items=flattened,
                ),
                asyncio.to_thread(
                    save_memory_graph_stubs,
                    graph_path=avatar_path.graph_dir,
                    memory_items=flattened,
                ),
                return_exceptions=True,
            )

            if isinstance(markdown_result, Exception):
                logger.error(
                    "Memory local markdown backup failed",
                    exc_info=(
                        type(markdown_result),
                        markdown_result,
                        markdown_result.__traceback__,
                    ),
                )
            else:
                logger.info(
                    "Memory local markdown backup success: %s",
                    markdown_result,
                )

            if isinstance(graph_result, Exception):
                logger.error(
                    "Memory graph stubs save failed",
                    exc_info=(
                        type(graph_result),
                        graph_result,
                        graph_result.__traceback__,
                    ),
                )
            else:
                logger.info(
                    "Memory graph stubs save success: %s",
                    graph_result,
                )

            if not await self._save_to_vdb(
                memory_items=flattened,
                timeout=timeout,
            ):
                return False

            self.memory_state.mark_saved({item.memory_id for item in selected})
            return True
