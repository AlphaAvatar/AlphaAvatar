# AlphaAvatar Loop 插件

[English](README.md)

Loop 是必需的 Foundation 组件。Host 用 AvatarRuntime 构造它，绑定 Foundation，然后调用 `initialize()`。初始化会解析共享服务并检查流式支持，不会发起前台模型请求。Engine 提交时要求 Loop 已初始化且未关闭。

## 配置与所有权

```yaml
loop:
  plugin: realtime
  init_config:
    model:
      backend: openai
      provider: openai
      model: YOUR_MODEL_ID
      temperature: null
    tool_policies: {}
```

模型标识由部署方提供。旧的顶层 `llm` 分节会被拒绝，不会被解释为 Loop 设置。不能用 `null` 禁用 Loop；缺少必需的模型时，会在校验其具体配置时被拒绝。

```python
loop = runtime.foundation.loop
handle = await loop.submit(request, authorize=authorize)
result = await handle.wait()
```

Provider、ContextManager、能力和 Output 从 AvatarRuntime 获取。不存在 `LoopDependencies`、`on_event` 或 `on_commit` 参数。Engine 拥有准入和前台打断；Loop 拥有执行、已接受的调用、记录和执行终态事实。

部署方选择受信任的插件；每个 Run 再通过 `allowed_capabilities` 进一步限制其中可调用的能力。默认情况下，这些被授予的能力无需二次批准即可运行。精确指定的 `tool_policies` 可以用 `enabled: false` 禁止某个能力，或用 `approval_required: true` 要求批准。要求批准但没有授权器时，该能力保持不可用，也不会作为可用工具对外声明。提供的授权器仍是逐次调用的关卡。模型文本和工具结果不能授予访问权限。

`read_only` 和 `parallel_safe` 默认为 false：它们控制调度和不确定结果的处理，而不是授权。不要只为了放行，就把聚合的 MCP、RAG 或 DeepResearch 工具归类为只读。启用一个插件即授予其暴露的操作，并可能消耗供应商额度或修改数据；只配置受信任的工具。这不是沙箱，也不是多租户授权系统。

## 提交与静态查询上下文

`submit()` 校验已提交的输入，并调度由其拥有的执行。该任务通过 ContextManager 准备 Context；Engine 不预先构建 prompt，也不等待整个模型／工具循环结束。正在退役的执行在其面向用户的输出租约被撤销后，仍保留清理所有权。

State 和静态 `loop_budget` 通过合成的运行时工具上下文只捕获一次。后续请求追加模型／工具续接内容，同时保留固定前缀、工具定义／顺序和所选的推理配置。计数器执行限制并为执行观测提供数据，不会在步骤之间改写 prompt 内容。

## 输出与记录

可见内容被构造为 EnvOutput，并通过 `runtime.output.publish(...)` 提交，带有稳定的输出标识和类型化的 scope／来源关联。文本完成封闭的是来源，而不是剩余的 TTS 或播放。Router 合成 ASSISTANT／TRANSIENT 文本；RTC 报告传输层播放并交付同步的转录文本。

完整的助手／工具批次使用 `runtime.output.records`。它们携带 context／Turn／Run 来源信息，并在后续依赖它们的执行继续之前被原子地准入。Memory 和 Context 独立消费记录；Loop 既不调用 Memory 持久化 API，也不调用传输适配器。

准入是本地接受，不是持久化，也不能证明已经播放。私有推理／供应商续接内容以及合成的 State／预算材料不包含在规范记录投影中。

`runtime.output.execution` 携带请求、工具和 Run 的观测。同一请求内的 commentary 引用标识的是实际被准入的文本，而不是供应商的能力标志。Status 根据事实派生呈现和非递归的旁白；Loop 没有等待／旁白计时器。`feedback_timeout` 仍限制异步用户内容的发布。

必需的记录消费者失败或保留容量耗尽时，执行会显式失败。在支持的情况下，无法准入的工具结果仍可通过返回的结果获取；准入失败不会被声称为已持久化。取消会完成已接受调用的收尾，绝不盲目重放写操作，并且即使失去可见输出权限，也保留已观测到的结果。

## 生命周期与迁移状态

Engine 停止准入并完成 Loop 的收尾，此时 Memory、Status 和 Output 消费者仍保持运行。随后它关闭 Router 和插件；Host 关闭 RTC 输出并释放 AvatarRuntime。Foundation 作为资源所有者以幂等方式关闭 Loop，然后释放 Context、Provider 和 Voice。

原生 Engine/Loop 路径在本源码树中处于启用状态。旧的 TurnController 和 Host SDK 模型／工具／记录桥接已移除。Voice 现已实现原生异步 PCM 合成。Character 有独立的原生呈现生命周期，不会提交另一个 Loop。原生 Host 进程监督与主生成路径相互独立。

执行仍属于当前的 Host 执行。本插件迁移未提供独立于连接的 Episode、恢复、睡眠／唤醒和 Dream 调度。
