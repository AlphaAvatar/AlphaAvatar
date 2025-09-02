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
from dataclasses import dataclass, field
from types import MethodType
from typing import TYPE_CHECKING, Any, Literal, Protocol

from livekit.agents.llm import ChatContext

if TYPE_CHECKING:
    from .engine import AvatarEngine


Mode = Literal["pipeline", "realtime"]


class BeforeHook(Protocol):
    """Implement this protocol to create a hook.

    Hooks receive a read-only context and return a HookDecision with an optional patch.
    Hooks should NOT mutate ctx in-place.
    """

    async def __call__(self, ctx: BeforeGenContextRO) -> HookDecision: ...


@dataclass(frozen=True)
class BeforeGenContextRO:
    """Read-only context passed to hooks for a single generation attempt."""

    mode: Mode
    # Common
    speech_handle: Any
    model_settings: Any
    instructions: str | None = None
    # Pipeline-only
    chat_ctx: ChatContext | None = None
    tools: list[Any] | None = None
    new_message: Any | None = None
    tools_messages: list[Any] | None = None
    # Realtime-only
    user_input: str | None = None


@dataclass
class BeforeGenPatch:
    """A patch describes per-call modifications. Only set fields you want to change."""

    instructions: str | None = None
    chat_ctx: Any | None = None
    tools: list[Any] | None = None
    new_message: Any | None = None
    tools_messages: list[Any] | None = None
    user_input: str | None = None
    model_settings: Any | None = None


@dataclass
class HookDecision:
    """Hook result. No short-circuiting or cancellations here."""

    continue_: bool = True  # Kept for API symmetry; not used to cancel others
    patch: BeforeGenPatch | None = None


@dataclass(order=True)
class _RegisteredHook:
    """Internal wrapper to track priority, timeout, and one-shot semantics."""

    priority: int
    name: str = field(compare=False)
    fn: BeforeHook = field(compare=False)
    timeout: float | None = field(compare=False, default=None)
    once: bool = field(compare=False, default=False)


class HookRegistry:
    """Holds registered hooks and runs them in parallel per generation."""

    def __init__(self) -> None:
        self._hooks: list[_RegisteredHook] = []

    # ---- CRUD API ----
    def add(
        self,
        fn: BeforeHook,
        *,
        name: str | None = None,
        priority: int = 100,
        timeout: float | None = None,
        once: bool = False,
    ) -> None:
        """Register a hook. Smaller priority runs earlier in conflict resolution."""
        self._hooks.append(
            _RegisteredHook(
                priority=priority,
                name=name or fn.__name__,
                fn=fn,  # type: ignore
                timeout=timeout,
                once=once,
            )
        )
        # Keep sorted so merge decisions are deterministic
        self._hooks.sort()

    def remove(self, name: str) -> bool:
        """Remove a hook by name."""
        for i, h in enumerate(self._hooks):
            if h.name == name:
                self._hooks.pop(i)
                return True
        return False

    def clear(self) -> None:
        """Remove all hooks."""
        self._hooks.clear()

    def snapshot(self) -> list[_RegisteredHook]:
        """Expose a snapshot (read-only copy)."""
        return list(self._hooks)

    # ---- Execution ----
    async def run_parallel(self, ctx: BeforeGenContextRO) -> HookDecision:
        """Run all hooks in parallel and merge their patches.
        - No cancellation between hooks
        - Timeout affects only the slow hook itself (others continue)
        - One-shot hooks are removed after this run
        """
        if not self._hooks:
            return HookDecision()

        loop = asyncio.get_running_loop()
        tasks: dict[asyncio.Task[HookDecision], _RegisteredHook] = {}

        async def _run_one(h: _RegisteredHook) -> HookDecision:
            try:
                coro = h.fn(ctx)
                if h.timeout is None:
                    return await coro
                return await asyncio.wait_for(coro, timeout=h.timeout)
            except asyncio.TimeoutError:
                # Timeout: log-like behavior without cancellation
                # (No logger dependency here; integrate your own if needed)
                return HookDecision(continue_=True)
            except Exception:
                # Swallow exceptions so one faulty hook won't break the batch
                return HookDecision(continue_=True)

        # Spawn all hook tasks
        for h in self._hooks:
            tasks[loop.create_task(_run_one(h))] = h

        decisions = await asyncio.gather(*tasks.keys(), return_exceptions=False)

        # Cleanup one-shot hooks
        if self._hooks:
            self._hooks = [h for h in self._hooks if not h.once]

        # Collect patches with their hook metadata for merge
        patches: list[tuple[_RegisteredHook, BeforeGenPatch]] = []
        for dec, (_task, reg) in zip(decisions, tasks.items(), strict=False):
            if isinstance(dec, HookDecision) and dec.patch:
                patches.append((reg, dec.patch))

        merged = self._merge_patches_by_priority(patches)
        return HookDecision(continue_=True, patch=merged)

    @staticmethod
    def _merge_patches_by_priority(
        patches: list[tuple[_RegisteredHook, BeforeGenPatch]],
    ) -> BeforeGenPatch:
        """Resolve conflicts by ascending priority (smaller wins).
        First-writer-wins per field.
        """
        if not patches:
            return BeforeGenPatch()

        # Ensure deterministic order
        patches = sorted(patches, key=lambda t: t[0].priority)

        out = BeforeGenPatch()
        for _, p in patches:
            for field_name, value in p.__dict__.items():
                if value is None:
                    continue
                if getattr(out, field_name) is None:
                    setattr(out, field_name, value)
        return out


def install_generation_hooks(engine: AvatarEngine) -> None:
    """Patch the AgentActivity inside the engine to run hooks before reply tasks."""

    if getattr(engine, "__hook_installed", False):
        return

    activity = engine._get_activity_or_raise()

    # --- pipeline ---
    _orig_pipeline = activity._pipeline_reply_task

    async def _wrapped_pipeline(
        _self,
        *,
        speech_handle,
        chat_ctx,
        tools,
        model_settings,
        new_message=None,
        instructions=None,
        _tools_messages=None,
    ):
        ro = BeforeGenContextRO(
            mode="pipeline",
            speech_handle=speech_handle,
            chat_ctx=chat_ctx,
            tools=tools,
            model_settings=model_settings,
            new_message=new_message,
            instructions=instructions,
            tools_messages=_tools_messages,
        )
        dec = await engine._generation_hooks.run_parallel(ro)
        patch = dec.patch or BeforeGenPatch()
        return await _orig_pipeline(
            speech_handle=speech_handle,
            chat_ctx=patch.chat_ctx or chat_ctx,
            tools=patch.tools or tools,
            model_settings=patch.model_settings or model_settings,
            new_message=patch.new_message if patch.new_message is not None else new_message,
            instructions=patch.instructions if patch.instructions is not None else instructions,
            _tools_messages=patch.tools_messages
            if patch.tools_messages is not None
            else _tools_messages,
        )

    activity._pipeline_reply_task = MethodType(_wrapped_pipeline, activity)

    # --- realtime ---
    _orig_rt = activity._realtime_reply_task

    async def _wrapped_rt(
        _self, *, speech_handle, model_settings, user_input=None, instructions=None
    ):
        ro = BeforeGenContextRO(
            mode="realtime",
            speech_handle=speech_handle,
            model_settings=model_settings,
            user_input=user_input,
            instructions=instructions,
        )
        dec = await engine._generation_hooks.run_parallel(ro)
        patch = dec.patch or BeforeGenPatch()
        return await _orig_rt(
            speech_handle=speech_handle,
            model_settings=patch.model_settings or model_settings,
            user_input=patch.user_input if patch.user_input is not None else user_input,
            instructions=patch.instructions if patch.instructions is not None else instructions,
        )

    activity._realtime_reply_task = MethodType(_wrapped_rt, activity)

    engine._generation_hook_installed = True
