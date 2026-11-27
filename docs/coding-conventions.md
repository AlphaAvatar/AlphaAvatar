# Coding conventions

[中文](coding-conventions-zh.md)

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

## Function bodies

Inside a function, blocks that do clearly different things, or each span several lines, are
separated by a blank line. A comment is not required: a block gets one short comment only where
it stands clearly apart and its purpose is not plain from the code; one that repeats the code or
the docstring is left out. For example, `_vertex` in the Provider plugin:

```python
def _vertex(kwargs: dict) -> bool:
    """Whether the Google SDK authenticates through Vertex AI, as it decides itself: its
    ``vertexai`` setting, else GOOGLE_GENAI_USE_VERTEXAI, else a project or credentials given.
    Vertex AI takes its own credentials (ADC) and needs no API key."""
    from pydantic import TypeAdapter, ValidationError

    # Its own setting first, parsed as the SDK's ``bool | None`` field parses it: "false",
    # "0", "no" or "off", as an interpolated setting gives them, are False.
    try:
        vertexai = TypeAdapter(bool | None).validate_python(kwargs.get("vertexai"))
    except ValidationError:
        return True  # Not a flag: the SDK refuses it, by its own name, before any key is read.
    if vertexai is not None:
        return vertexai

    chosen = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower()
    if chosen in ("true", "1", "yes", "false", "0", "no"):
        return chosen in ("true", "1", "yes")

    return kwargs.get("project") is not None or kwargs.get("credentials") is not None
```

The shell scripts under `packaging/` and `scripts/` follow the same rule.

Code being changed follows these rules; code nobody touches is not reordered for them alone.
