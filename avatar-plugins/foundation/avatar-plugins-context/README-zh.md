# AlphaAvatar Context 插件

默认 Context 管理器由 Host 基于尚未装配完整的 AvatarRuntime 创建，之后由 FoundationRuntime 拥有。Engine 借出 Memory／Persona 读取来源；它不组装原生 Loop prompt，也不拥有 SDK ChatContext。

## 接口

通过公开的 ContextManager 契约使用 `runtime.foundation.context`：

- `prepare(ContextPrepareRequest)` 接收来自 Loop 的已提交 Turn，并准备其历史、感知和查询前缀。
- `build(prefix, continuation=...)` 追加执行续接内容，不刷新 State。

不存在并行的 query-manager API。ContextContribution 和 ContextPrepareRequest 位于公开的 `alphaavatar.agents.avatar.context.schemas` 命名空间中。

准备过程等待显式标识的已提交 Turn，一次性捕获 State、来源属性、时间和模态信息，并在事件循环之外渲染前缀。待处理的准备有数量上限，并在收尾之前始终保持被拥有，即使发起请求的执行已被取消。

State 和静态 `loop_budget` 使用合成的 `alphaavatar_runtime_context` function-call／output 对。其标识、内容和位置在一次查询内保持稳定。不会引入中途的 system／developer 更新，也不会按模型步骤改写预算。稳定的前缀允许复用，但不保证命中供应商缓存。

## 原生历史

管理器按 context 和 Turn 保留完整历史，并独立消费来自 Output 的规范模型记录。用户输入来自已提交的 Turn，包括在准备之前就已被取代的 Turn。系统通知以类型化文本部分的形式进入当前用户消息，位于对应语音片段的位置。当快照保留了时序证据时，历史会保留通知事实及其顺序。

不完整的工具调用／输出对会被排除在下一次模型输入之外。正在退役的 Run 的结果仍关联到其原始标识。Context 的确认独立于 Memory 的确认，也不是数据库持久化的保证。

```yaml
context:
  plugin: default
  init_config:
    behavior_rules: "Follow the application's execution and authorization policies."
    max_pending_preparations: 16
```

历史在整个会话期间保留完整的用户消息，保持 ContextBuilder 最初构建时的样子，包括其媒体的顺序和捕获的内容。捕获之后，管理器使用 ContextCompressor 在发出的请求中，把历史图像载荷在原位置替换为 `<image_not_replayed />`。当前 Turn 携带其完整的用户消息和自己的运行时上下文。

仍设置 `history_max_turns`、`history_max_items` 或 `history_max_bytes` 的 profile 可以正常加载，这些值会被忽略。

StateRuntime.global_behavior_rules 可能来自客户端元数据。它作为参考／偏好被捕获，不会提升为应用的系统指令。绑定 Memory／Persona 来源不会转移其所有权。

## 生命周期

Host 在绑定 Foundation 之前构造 Context、Voice 和必需的 Loop，并且只在绑定之后才初始化 Loop。创建 Context 时不得请求尚不可用的 Foundation 服务。Loop 不是可选项，`loop: null` 无效。

在排空记录消费者之前，先停止输入接入和执行生产者。Foundation 在释放 Output 和 Inference 之前，关闭 Loop、Context／准备工作以及共享的 Provider／Voice。Context 不关闭借用的 Memory 或 Persona 组件。

SDK 生成桥接已移除。原生历史和 ContextManager 是主路径，而不是 SDK ChatContext 旁边的回退方案。时序对齐和视觉渲染仍是独立组件；不存在进程全局的查询缓存，也不会逐步修改 State。
