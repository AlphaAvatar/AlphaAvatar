# 编码约定

[English](coding-conventions.md)

AlphaAvatar 的 Python 代码应有的写法。范例是 `avatar-core/alphaavatar/core/perception/runtime.py` 和 Memory 插件（`MemoryRuntime`、`MemoryStore`、`MemoryContextState`、`PassiveRecall`）。

## 代码顺序

模块和类从上到下阅读，每个名称都在使用之前定义：

- 模块以许可证头和 `from __future__ import annotations` 开头，然后是按组排列的导入：标准库、第三方、`alphaavatar` 绝对导入、相对导入；仅用于类型标注的导入放在 `TYPE_CHECKING` 下。模块的私有辅助函数和私有类放在使用它们的公共代码之前。
- 类的顺序为：一行文档字符串、类常量（`_UPPER_CASE`，按用途分组）、`__init__`、属性、静态方法，然后是其他方法。
- 函数定义在调用它的代码之前：私有方法放在调用它的方法上方。相互递归的函数是唯一的例外。
- 私有方法放在公共方法之前，除非类用 `"""Source state operations"""` 或 `"""Runtime operations"""` 这样的分区字符串划分为功能分区；在每个分区内，这一顺序同样适用。
- 生命周期放在最后：私有实现（`_start`、`_stop`、`_close`）放在其公共入口（`start` 和 `stop`，或 `on_start` 和 `on_stop`）之前。
- 必须在持锁状态下运行的方法以 `_locked` 结尾；后台循环命名为 `_consume_*`；任务的完成回调命名为 `_*_done` 或 `_observe`。

划分为功能分区的类，示例如下：

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

## 构造函数字段

设置较多字段的 `__init__` 按用途对字段分组：借用的服务和设置、身份、预算、正在处理的状态、生命周期。
每组之前有一个空行和一行注释，说明该组包含什么。
第一组紧跟在签名之后，不加空行。
由另一个字段构建的字段放在那个字段之后，在组与组之间和组内都是如此。
例如 Loop 插件中的 `LoopExecution`：

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

## 函数体

在函数内部，做明显不同事情的代码块，或各自跨越多行的代码块，之间用一个空行分隔。
注释不是必需的：只有当一个代码块明显独立、且从代码本身看不出其用途时，才为它加一句简短注释；重复代码或文档字符串的注释应省略。
例如 Provider 插件中的 `_vertex`：

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

`packaging/` 和 `scripts/` 下的 shell 脚本遵循同样的规则。

正在修改的代码遵循这些规则；无人改动的代码不会仅为符合这些规则而重排。
