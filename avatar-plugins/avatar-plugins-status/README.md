# AlphaAvatar Status Plugin

🟢 **AlphaAvatar Status Plugin** provides the default runtime implementation for AlphaAvatar's intermediate status system.

It is used to send short, user-facing or UI-facing status updates while the agent is thinking, calling tools, processing tool results, or recovering from tool errors.

The core status protocol lives in:

```text
alphaavatar.agents.status
```

This plugin provides replaceable implementations for:

```text
StatusPolicy   -> decides whether / when a status event should be emitted
StatusRenderer -> converts a StatusEvent into short user-facing text
StatusSink     -> delivers the event to logs, UI, text channels, or voice
```

---

## Why this plugin exists

Long-running agent interactions often contain noticeable waiting periods:

```text
User input
  -> LLM prefix caching / first-token wait
  -> tool-call generation
  -> tool execution
  -> tool-output prefix caching
  -> final answer generation
```

Without intermediate feedback, users may feel the assistant is stuck.

This plugin reduces perceived latency by emitting short status updates such as:

```text
我想一下。
我查一下。
我整理一下。
I’ll check that.
I’m putting it together.
```

These statuses can be delivered through:

* Logs
* LiveKit data channel events
* UI action events
* Text status messages
* Voice status speech

---

## Architecture

```text
StatusEvent
    ↓
StatusEmitter
    ↓
StatusPolicy
    ↓
StatusRenderer
    ↓
StatusSink(s)
        ├── LoggerStatusSink
        ├── StatusActionEventSink
        └── TextOrVoiceStatusSink
```

---

## Main flow

### 1. A component emits a `StatusEvent`

Examples:

```python
StatusEvent(
    type=StatusType.THINKING,
    source=AvatarModule.AVATAR_ENGINE,
    stage="thinking",
)
```

```python
StatusEvent(
    type=StatusType.TOOL_START,
    source=AvatarModule.DEEPRESEARCH,
    stage=DeepResearchOp.SEARCH,
    message="我查一下。",
)
```

---

### 2. `StatusPolicy` decides whether to emit it

The policy controls:

* Delay before emission
* Per-turn max event count
* Duplicate event suppression
* Per-source throttling
* Immediate events, such as tool start events

This prevents the assistant from speaking or displaying too many status messages.

---

### 3. `StatusRenderer` generates short text

If the event already has `message`, the renderer uses it directly.

Otherwise, it loads a template from:

```text
alphaavatar/plugins/status/templates/
```

Template files are selected by:

```text
{status_type}.{source}.{stage}.txt
```

For example:

```text
templates/zh/tool_start.deepresearch.search.txt
templates/en/thinking.avatar_engine.thinking.txt
```

Each file can contain multiple templates, one per line. The renderer randomly selects one.

---

### 4. `StatusSink` delivers the event

The plugin currently provides three sinks:

```text
LoggerStatusSink
    Writes structured status logs.

StatusActionEventSink
    Sends structured UI/action events through LiveKit data channel.

TextOrVoiceStatusSink
    Sends short text or voice status depending on room type and interaction mode.
```

---

## File structure

```text
alphaavatar/plugins/status/
├── __init__.py
├── policy.py
├── renderer.py
├── sink.py
├── log.py
├── version.py
└── templates/
    ├── en/
    └── zh/
```

---

## File responsibilities

### `__init__.py`

Registers the default status plugin.

It builds:

```text
DefaultStatusPolicy
DefaultStatusRenderer
CompositeStatusSink
```

and returns a configured `StatusEmitter`.

This is the main plugin entry point.

---

### `policy.py`

Contains `DefaultStatusPolicy`.

Responsibilities:

* Decide whether a status event should be emitted
* Apply delay rules
* Avoid duplicate statuses
* Avoid excessive status messages in one turn
* Let important tool events pass through without being blocked by generic thinking events

Typical logic:

```text
avatar_engine.thinking
    delayed and low-frequency

deepresearch.tool_start
    immediate and more important

tool_error
    high priority

memory/persona internal events
    usually suppressed
```

Modify this file when you want to tune status frequency or priority.

---

### `renderer.py`

Contains `DefaultStatusRenderer`.

Responsibilities:

* Use `event.message` if provided
* Detect language from event metadata, such as query text
* Load templates from `templates/`
* Randomly select one matching template
* Fall back from specific templates to generic templates

Matching order:

```text
{type}.{source}.{stage}.txt
{type}.{source}.default.txt
{type}.default.default.txt
```

Example:

```text
tool_start.deepresearch.search.txt
tool_start.deepresearch.default.txt
tool_start.default.default.txt
```

Modify this file when you want to change template loading behavior.

Modify files under `templates/` when you only want to change copywriting.

---

### `sink.py`

Contains delivery implementations.

#### `CompositeStatusSink`

Runs multiple sinks together.

#### `LoggerStatusSink`

Writes status events to logs.

Useful for debugging whether an event was emitted.

#### `StatusActionEventSink`

Publishes structured status action events through LiveKit data channel.

Useful for UI state machines, avatar animations, loading indicators, and activity timelines.

Example payload type:

```text
agent_status_action
```

#### `TextOrVoiceStatusSink`

Delivers user-facing short status text.

It decides delivery mode based on room type and interaction mode.

Example behavior:

```text
WhatsApp / Telegram / Slack / Discord
    -> text status

Web app
    -> text + voice, or text only depending on delivery mode config

Voice-only room
    -> voice status

API room
    -> no voice by default
```

It also applies voice-specific throttling so generic thinking does not block more useful tool progress.

---

### `templates/`

Stores user-facing status copy.

Templates are grouped by language:

```text
templates/en/
templates/zh/
```

Each file can contain multiple candidate lines.

Example:

```text
templates/zh/tool_start.deepresearch.search.txt
```

```text
我查一下。
我帮你搜一下。
我先查查相关信息。
```

Example:

```text
templates/en/thinking.avatar_engine.thinking.txt
```

```text
Let me think.
Hmm, let me think.
Give me a second.
```

Rules:

* One template per line
* Empty lines are ignored
* Lines starting with `#` are ignored
* Keep voice-friendly templates short
* Avoid hidden reasoning
* Avoid saying results have been found before the tool finishes

---

## Status types

Current status types are defined in the core status protocol:

```python
class StatusType(StrEnum):
    READY = "ready"

    THINKING = "thinking"

    TOOL_START = "tool_start"
    TOOL_PROGRESS = "tool_progress"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"

    FINALIZING = "finalizing"
```

Suggested usage:

```text
READY
    Agent/session is ready.

THINKING
    User input has been received, but the model has not produced a visible action yet.

TOOL_START
    A tool starts running.

TOOL_PROGRESS
    A long-running tool reports intermediate progress.

TOOL_END
    A tool finishes successfully.
    Usually useful for UI only, not voice.

TOOL_ERROR
    A tool fails or receives invalid arguments.

FINALIZING
    Tool output has returned and the model is organizing the result or deciding the next step.
```

---

## Common event sources

Typical sources are:

```text
AvatarModule.AVATAR_ENGINE
AvatarModule.DEEPRESEARCH
AvatarModule.RAG
AvatarModule.MCP
```

The recommended pattern is:

```text
type   = generic status category
source = module/plugin that emitted the event
stage  = operation or lifecycle stage
```

Example:

```text
tool_start.deepresearch.search
tool_start.rag.query
tool_start.mcp.tool_call
finalizing.avatar_engine.after_tool
thinking.avatar_engine.thinking
ready.avatar_engine.session_ready
```

---

## Adding a new template

To add a new Chinese template for DeepResearch search:

```text
templates/zh/tool_start.deepresearch.search.txt
```

Example content:

```text
我查一下。
我帮你搜一下。
我先查查相关信息。
```

To add an English version:

```text
templates/en/tool_start.deepresearch.search.txt
```

Example content:

```text
I’ll check that.
I’ll look it up.
Let me search for that.
```

No Python code change is needed.

---

## Adding status support to a new tool

A tool should emit a `TOOL_START` event before a long-running operation.

Example:

```python
self.emit_status_nowait(
    StatusEvent(
        type=StatusType.TOOL_START,
        source=AvatarModule.RAG,
        stage=RAGOp.QUERY,
        message=monologue,
        metadata={
            "op": RAGOp.QUERY.value,
            "query": query,
        },
    )
)
```

For user-facing text, prefer passing `monologue` from the model:

```python
monologue: str | None = None
```

If `monologue` is not provided, the renderer falls back to a template file.

---

## Tool error handling

Tool runtime failures should emit:

```text
StatusType.TOOL_ERROR
```

The shared `ToolBase` can catch tool exceptions and emit a fallback error event.

The renderer will select a template such as:

```text
templates/zh/tool_error.default.default.txt
templates/en/tool_error.default.default.txt
```

or a more specific one:

```text
templates/zh/tool_error.deepresearch.default.txt
```

---

## Recommended extension points

### Change when status events are emitted

Edit:

```text
policy.py
```

### Change what status text says

Edit files under:

```text
templates/
```

### Change how status events are delivered

Edit:

```text
sink.py
```

### Add a new status plugin implementation

Create a new plugin package and register another implementation of:

```text
StatusPolicyBase
StatusRendererBase
StatusSinkBase
```

---

## Design principles

1. Keep `StatusType` small and generic.
2. Use `source` and `stage` for details.
3. Keep voice status short.
4. Do not expose hidden reasoning.
5. Let tools emit concrete progress.
6. Let the engine emit generic thinking/finalizing fallback.
7. Prefer UI action events for frequent or low-level progress.
8. Prefer voice only for meaningful user-facing moments.
9. Keep templates outside Python code.
10. Make status behavior easy to observe and tune.

---

## Example timeline

```text
User asks a question
    ↓
AvatarEngine emits THINKING after delay
    "我想一下。"

Model decides to call DeepResearch
    ↓
DeepResearch emits TOOL_START
    "我查一下。"

Tool returns result
    ↓
AvatarEngine emits FINALIZING after delay
    "我整理一下。"

Model starts final answer
    ↓
Delayed FINALIZING is cancelled
```

---

## Packaging note

Template files must be included in the plugin package.

For setuptools, make sure `pyproject.toml` includes:

```toml
[tool.setuptools.package-data]
"alphaavatar.plugins.status" = ["templates/**/*.txt"]
```

Otherwise templates may work in local development but disappear after installation.
