# Coding conventions

How AlphaAvatar's Python reads. The models are `avatar-core/alphaavatar/core/perception/runtime.py` and the Memory plugin (`MemoryRuntime`, `MemoryStore`, `MemoryContextState`, `PassiveRecall`).

## Code order

Modules and classes read top to bottom, every name defined before it is used:

- A module starts with its license header and `from __future__ import annotations`, then imports grouped standard library, third party, `alphaavatar` absolute, relative; imports for typing alone go under `TYPE_CHECKING`. Its private helpers and private classes come before the public code that uses them.
- A class is ordered: its one-line docstring, class constants (`_UPPER_CASE`, grouped by purpose), `__init__`, properties, static methods, then its other methods.
- Define a function before the code that calls it: a private method above the methods that call it. Mutually recursive functions are the one exception.
- Private methods come before public ones, unless the class is divided into functional areas by section strings such as `"""Source state operations"""` or `"""Runtime operations"""`; within each area the order holds again.
- Lifecycle comes last: the private implementation (`_start`, `_stop`, `_close`) before its public entry (`start` and `stop`, or `on_start` and `on_stop`).
- A method that must run with a lock held ends in `_locked`; a background loop is `_consume_*`; a task's done callback is `_*_done` or `_observe`.

A class divided into areas, for example:

```python
class PerceptionRuntime:
    """Session-scoped full-duplex perception runtime."""

    _MAX_SPEECH_SOURCES = 256

    def __init__(self, *, session_id: str, clock: RuntimeClock | None = None) -> None: ...

    @property
    def has_active_speech(self) -> bool: ...

    """Helper"""

    def _publish_event_locked(self, ...) -> PerceptionEvent: ...

    """Cutoff operations"""

    def _capture_cutoff_locked(self) -> PerceptionCutoff: ...

    def capture_cutoff(self) -> PerceptionCutoff: ...
```

## Constructor fields

An `__init__` that sets more than a handful of fields groups them by purpose: borrowed services and settings, identity, budgets, the state being worked on, lifecycle. Each group is preceded by a blank line and a one-line comment naming what the group holds. The first group follows the signature directly, without a blank line. A field built from another comes after it, in the groups and within each. For example, `LoopExecution` in the Loop plugin:

```python
    def __init__(self, request: LoopRequest, ...) -> None:
        # The run (its run, Turn and context IDs), its request and settings, and what it borrows.
        self._identity = LoopIdentity(uuid4().hex, request.turn_id, request.context_id)
        self._request = request
        self._runtime = runtime

        # Its limits, and the options its model requests start from.
        self._budget = ExecutionBudget(request, asyncio.get_running_loop().time())
        self._generation_options = self._budget.options(config.reasoning, finalizing=False)

        # Lifecycle: why it is cancelled, whether its task has begun, and its one shared close.
        self._cancel_reason: str | None = None
        self._started = False
        self._close_task: asyncio.Task[None] | None = None
```

Code being changed follows these rules; code nobody touches is not reordered for them alone.
