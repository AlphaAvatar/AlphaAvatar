# 原生 Engine 示例

五份配置都使用 `loop.plugin: realtime`，主模型位于 `loop.init_config.model`。`backend: openai` 选择原生 Responses 后端；插件内部的 Memory／Persona 供应商保留各自现有的后端设置。模型和语音标识是部署时的选择，不保证你的账户有权访问。主模型标识沿用仓库中的值；运行之前，把它改为你所配置的供应商上可用的模型。`temperature: null` 避免向可能不接受采样参数的模型注入该参数。

```bash
ENV_FILE=.env.dev alphaavatar config check examples/agent_configs/mm/pipeline_openai_tools.yaml  # optional
ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/mm/pipeline_openai_tools.yaml
```

`defaults` 只包含 YAML 锚点，在别名解析之后被删除。未知的运行时部分（包括已移除的 `llm` 部分）会被拒绝，而不是被静默忽略。原生历史完整保留；以前的 `context.init_config.history_max_*` 设置仍被接受，但会被忽略。打断通过 `router.init_config.turn_taking.interruption` 配置；SDK 时代未使用的 `voice.allow_interruptions` 设置已移除，并会被拒绝。

## 配置布局

仓库中的多模态示例是格式参考。所有配置按相同顺序使用相同的部分；只有多模态示例包含可选的第六部分：

1. Avatar Identity & Workspace
2. Runtime
3. Foundation Plugins（`loop`、`context`、`voice`、`vision`）
4. Perception Plugins（`defaults` 锚点、`router`、`status`、`character`、`memory`、`persona`）
5. Tools Plugins（`tools`）
6. Host & RTC Access（`host`）

保持两个空格的缩进、部分分隔线和有意义的空行。保留以折叠格式书写的介绍／语音指令和 YAML 锚点；不要把它们替换为序列化的单行字符串。

时间对齐位于 `runtime.perception.temporal_alignment`，不是与 perception 并列的部分。对话 pipeline 配置只包含提取和整合。`item_ops`、`candidate_source`、`similarity_threshold`、`max_candidates_per_item` 和 `timeout` 现在属于 `pipeline.consolidation` 内部；`pipeline.maintenance` 映射会被拒绝。

多模态参考配置和 Demo 设置 `candidate_source: union`；voice-minimal 显式设置 `consolidated_lookup`；Hiyori 示例保留处理器默认值 `consolidated_lookup`。这次格式迁移不会给每个场景强加同一种候选策略。

## Runner 并行

默认情况下，每个选定的推理方法在一个由所有会话共享的 runner 进程中运行。一个方法可以选择使用更多独立进程；每个进程持有自己的模型副本，因此内存随每个 worker 增长，而且不会自动扩缩：

```yaml
runtime:
  inference:
    methods:
      alphaavatar.voice.vad.silero:
        workers: 2  # 1-8
```

- 只有声明自己可复制的 runner 才接受大于 1 的 `workers`：Silero VAD（`alphaavatar.voice.vad.silero`）和 Smart Turn v3（`alphaavatar.router.turn_taking.smart_turn_v3`）。向量存储、MCP、语义寻址、说话者和人脸 runner 保持一个 worker。
- `max_pending` 限制每个方法的请求数，等待中和执行中的一并计算；`queue_timeout` 和 `request_timeout` 分别限制等待 worker 的时间和一次执行的时间；`client_timeout` 限制会话本地的等待、连接和发送。重启遵循 `restart_window_seconds` 内的 `restart_limit`。
- 拼写错误、未被选中或不可复制的条目会在加载文件时被拒绝；`alphaavatar config check` 显示生效的 worker 数。在命令行中使用映射形式，因为路径中的点会把方法名拆开：`'runtime.inference.methods={alphaavatar.voice.vad.silero: {workers: 2}}'`。
- 会话容量仍由 `host.processes.capacity` 决定，与 runner worker 无关。

## 适用范围

| 配置 | 范围 |
| --- | --- |
| `mm/pipeline_openai_tools.yaml` | 多模态输入和已配置的工具插件 |
| `roles/demo.yaml` | 带四个上下文帧的多模态助理 Demo |
| `voice/pipeline_openai_tools_minimal.yaml` | 语音工具；不含环境／人脸／视频处理，也不含 Tavily |
| `voice/pipeline_openai_airi.yaml` | 使用 OpenAI TTS 的 Hiyori 风格语音人设；无动画角色 |
| `voice/pipeline_voiceai_airi.yaml` | 使用 Voice.ai TTS 的 Hiyori 风格语音人设；无动画角色 |

AIRI 风格的示例显式设置 `character.plugin: null`。它们的名称描述的是保留下来的人设，并不表示支持旧的动画 AIRI／AgentSession 传输。显式配置时，原生 Host 现在支持原生 Character 生命周期。这些示例不会自动启用它。可信前端必须单独提供；按照 [Character 设置](../avatar-plugins/perception/avatar-plugins-character/README.md)操作。

## 工具授权与外部服务

已启用的插件把它们的能力授予每个 Run。使用 `tool_policies: {}` 时，这些能力无需再次批准即可运行：Loop 的 `approval_required` 默认为 `false`。针对单个能力的精确策略可以用 `enabled: false` 禁止它，或要求 `approval_required: true`；原生 Host 不提供授权器，因此这样的能力不会提供给模型。只启用可信的工具：它们的操作可能消耗供应商额度或修改数据。不要仅因为其中一台服务器是文档服务器，就把聚合的 MCP 能力标记为只读。

已启用的供应商、embedding、MCP 服务器和推理 runner 需要相应的依赖、凭据、网络访问和模型资源。多模态／Demo 配置还保留了 Google 环境提取和 Tavily 研究；voice-minimal 示例不需要这两项服务。OpenAI 和 Voice.ai TTS 的选择使用固定采样率的原生流式 PCM 供应商。Character 有原生生命周期，但仍需要真实的渲染器／RTC 验证。
