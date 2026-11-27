# AlphaAvatar Agents

[English](README.md)

`alpha-avatar-agents` 定义 Agent 执行契约和运行时组合。
具体的模型后端和功能实现位于插件包中；应用托管和传输组装归 Host 和 RTC 负责。

## 📦 包结构

```text
alphaavatar/agents/
├── avatar/               # Engine, Loop, Context, Provider, Voice and Vision contracts.
├── runtime/              # Runtime composition, capability registry and inference.
├── configs/              # Strict Avatar and plugin-selection configuration.
├── character/            # Presentation and transport contracts.
├── memory/               # Memory interfaces and public schemas.
├── persona/              # Persona interfaces and public schemas.
├── router/               # Interaction processor contracts.
├── status/               # Status contracts.
├── tools/                # Tool abstractions and operation contracts.
├── reflection/           # Reserved, empty package; no Reflection contracts yet.
├── workspace/            # Workspace, user and session paths and their preparation.
├── utils/                # Identity, time and shared utilities.
├── log.py                # Agent logging configuration.
└── version.py            # Package version.
```

此处只列出部分文件和功能目录；省略普通的包初始化文件。

## 原生执行

```text
Router turn decision / direct input
    -> AvatarEngine
    -> Foundation Loop
    -> ContextManager + ProviderService + AvatarCapabilityRegistry
    -> OutputRuntime
```

AvatarEngine 负责有界的 Turn 准入、重复／过期输入隔离、提交和精确中断。
它不继承 LiveKit Agent，不构造模型提示词，不注册 SDK 工具，也不直接写入 Memory。

Loop 负责模型／工具执行和规范记录的发布。
ContextManager 负责规范的会话历史、请求内投影和查询准备。
Provider 负责模型客户端和追踪。
State 和静态的 loop 预算在每次查询时截取一次，不会在模型步骤之间改写。
生成完成始终与播放完成和中断相区分。

## 职责归属

Provider 的 schema、枚举和抽象位于 `alphaavatar.agents.avatar.provider`。
插件实现不得把 SDK 类型引入 Core 或公开的输出数据。
运行时组件在适当时使用 Core 的 LifecycleComponent 和 LifecycleGroup。
AvatarRuntime 组合 Session、State、Core 运行时、Foundation、能力及其推理客户端；它不是插件的生命周期管理器。

Engine 在 Router 启用决策之前启动其消费者。
它在其规范记录消费者仍然存在时停止准入，并让 Loop 执行收尾。
插件的最终处理仍由各插件自己负责。
Host 负责外围的执行生命周期；断开传输会释放 RTC 订阅，与 Engine 的销毁相互独立。

InferenceRuntime 拥有共享 socket 和串行的 runner 进程。
InferenceExecutor 只拥有客户端连接。
Host 监督该服务，但不会为 runner 进程创建第二个所有者。
Host 既不会自动重放失败的作业，也不会自动重放会改变状态的请求。

## 配置

Agent 配置选择插件，以及由处理器维护的 `init_config` 设置。
主模型是 `loop.init_config.model`；没有 SDK 的 `llm` 部分。
已启用的插件将其能力授予每个 Run；精确匹配的 `tool_policies` 条目可以拒绝某项能力（`enabled: false`），或要求授权方（`approval_required: true`）。
原生 provider extra 在 `alpha-avatar-plugins-provider` 上选择，而不是在 Agents SDK 的 `providers` extra 上。

Host 加载共享的应用配置文件，并在严格校验 AvatarConfig 之前移除 `host`。
执行子进程恢复已校验的快照，保留原来的 Avatar 身份和已解析的工作区，而不是再次追加 Avatar ID。
`alphaavatar` 命令及其参数解析器只属于 Host。

## 边界

原生 TTS 和 Character 使用 AlphaAvatar 契约，而不是 AgentSession。
Host 为 Character 提供限定范围的 RTC 传输，Character 插件负责浏览器端呈现。
真实的渲染器、RTC 和 provider 集成仍需要端到端验证。

会话范围内的 Perception／Output 一致性检查保持不变。
持久化的 Episode、跨附着恢复、睡眠／唤醒和 Dream 调度是另外的工作。
