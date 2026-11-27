# 插件布局与边界

[English](README.md)

本文说明插件工作区及其运行时边界。能力与实现状态见[插件目录](../README.md#alphaavatar-plugins)。

## 📦 包结构

```text
avatar-plugins/
├── README.md
├── foundation/
│   ├── avatar-plugins-context/
│   ├── avatar-plugins-loop/
│   ├── avatar-plugins-provider/
│   └── avatar-plugins-voice/
├── perception/
│   ├── avatar-plugins-character/
│   ├── avatar-plugins-memory/
│   ├── avatar-plugins-persona/
│   ├── avatar-plugins-router/
│   └── avatar-plugins-status/
└── tools/
    ├── avatar-plugins-deepresearch/
    ├── avatar-plugins-mcp/
    └── avatar-plugins-rag/
```

每个 `avatar-plugins-*` 目录都是独立打包的工作区成员。分层目录用于组织仓库，它们既不是 Python 包，也不是单独的发行包。

Python 命名空间仍为 `alphaavatar.plugins.<plugin>`，发行包名称仍为 `alpha-avatar-plugins-<plugin>`。分层名称不会加入导入路径、entry point、YAML 插件选择或模型缓存命名空间。

本汇总 README 包含插件包目录树。各插件的 README 说明各自的配置、行为和限制，不再重复“包结构”一节。

## 分层职责

### Foundation

Foundation 插件通过 `AvatarRuntime.foundation` 提供可复用的执行与模型服务：

```text
AvatarRuntime
└── foundation: FoundationRuntime
    ├── context: ContextManager
    ├── loop: Loop
    ├── provider: ProviderService
    └── voice: VoiceBundle
        ├── vad
        ├── stt
        └── tts
```

Host 构造 Context、Voice 和必需的 Loop，把 Foundation 绑定到运行时，然后初始化 Loop。Loop 初始化会解析其共享服务并检查流式支持；这不是一次前台模型请求。`null` Loop 不是一种禁用 Loop 的运行模式。

Context 拥有完整的原生历史、请求内投影和逐次查询准备。Provider 拥有共享模型客户端和追踪，不拥有对话历史或工具权限。VoiceBundle 拥有可复用的语音工厂；Router 拥有借用这些工厂的各个流和合成任务。

原生主链路是 Engine -> Loop -> Context/Provider -> OutputRuntime。OpenAI 流式后端与 LangChain 结构化任务后端的能力不同；当前的原生实时 Loop 需要显式选择 `backend: openai`。

### Perception

Perception 层插件提供持久记忆、身份、交互协调、角色呈现和状态反馈。这一仓库分层的范围比原始感官处理更广，也不同于 Core 的 `PerceptionRuntime`。

Router 接收 `runtime`，并借用 `runtime.foundation.voice`。其工厂把所需组件传给各处理器。Memory 独立消费已提交的 Turn 和规范 Output 记录。Persona 负责身份／资料处理。Status 消费执行事实，生成类型化的呈现决定和非递归的旁白。

Character 包通过注入的 CharacterTransport 提供原生 AIRI 浏览器生命周期。Host 拥有房间凭据和就绪回调；插件拥有自己的浏览器。共享的受信任前端单独部署，且不注册 Character 推理 runner。当前示例保持 `character.plugin: null`；启用它需要完成 Character 部署步骤。Reflection、Planning 和 Behavior 仍是计划中的能力，不是已实现的独立包。

### Tools

DeepResearch、MCP 和 RAG 各自拥有其操作 schema、实现和配置。Engine 收集已启用的能力；Loop 通过原生能力注册表调用它们，并带有显式的执行策略和授权。工具不会收到 StatusEmitter 或 `monologue` 参数。

已注册的能力不会自动获得批准。不能仅因 MCP 或 RAG 聚合能力中的某个操作是只读的，就把该聚合能力标记为只读。Sandbox 仍在计划中。

MCP 在其隔离的 runner 中拥有原生 MCP 客户端会话。每个连接的 transport／session 作用域由同一个异步任务进入和退出；runner 先关闭这些所有者，再等待其事件循环线程结束（join）。网络期限到达时会完成本地工作的收尾，而不是遗弃一个 future、从而隐式允许重复调用。RAG 存储的收尾与其已接受的操作串行执行。

## 注册与生命周期

配置按能力类型和名称选择每个实现：`voice.stt.plugin: openai_segment` 选择 `voice.stt` 类型下的 `openai_segment`。已安装的包在 `alphaavatar.<type>` 组中以该名称声明一个 entry point，指向其 `AvatarModulePlugin` 类；内置插件在各自的 `pyproject.toml` 中以同样方式声明，查找它们时不会导入任何包。工厂校验其 `init_config`（`settings`），并给出它使用的推理 runner（`inference_runners`）；`config check`、Doctor 和 start 都在会话开始前解析这些选择，再根据这些 runner 规划 worker。缺失、重复或无法加载的实现会在选择它的设置处报错。工厂创建已配置的实例，不拥有任何特定于某次执行的状态。

`alphaavatar.core.lifecycle.LifecycleComponent` 定义 `on_start()` 和 `on_stop()`。`LifecycleGroup` 负责有序的启动阶段、同一阶段内独立组件的并行运行，以及按相反阶段顺序进行的清理。清理同样覆盖部分完成和尚未启动的初始化。重复的关闭请求共享所属的工作，已关闭的实例不会重新启动。

处理器接口可以保留各自的 `start()` / `stop()` 方法和有意义的收尾参数。Memory 和 Persona 在各自的运行时中保留业务专属的记录排空和持久化；这些职责不属于 Core。

`HostExecution` 在执行子进程中拥有 Engine 和 AvatarRuntime。SessionManager 依次安排附着输出、Engine，然后是输入。终止时，附着清理先释放输入接入、呈现、订阅和连接，然后 HostExecution 才完成 Engine 和 Runtime 的收尾。已接受的工具工作收尾期间，Engine 保持其内部记录消费者运行。`LiveKitConnection` 只报告连接事件并释放传输资源；它既不销毁执行，也不删除房间。

消费方插件不得关闭借用的 Foundation 服务。保持 Core 独立于 Agents、具体插件、Provider SDK 和 LiveKit。不要为了共享生命周期实现而把传输适配器引入 Engine。

## 配置与模型初始化

示例使用五个分节：Avatar Identity & Workspace、Runtime、Foundation Plugins、Perception Plugins 和 Tools Plugins；多模态示例还有第六个分节 Host & RTC Access。这些标题用于组织编写；实际的键仍是 `avatar`、`runtime`、`loop`、`context`、`voice`、`vision`、`router`、`status`、`character`、`memory`、`persona` 和 `tools`。`defaults` 包含 YAML 锚点，不是运行时配置。可选的顶层 `host`（应用托管与 RTC）和 `application`（主目录与缓存根目录）分节由 Host 读取，Host 会在严格的 AvatarConfig 校验之前移除它们。

插件配置保留在其所属插件或处理器中。主模型在 `loop.init_config.model` 下配置；时序对齐属于 `runtime.perception.temporal_alignment`。对话提取与整合属于 `memory.init_config.conversation.pipeline`。

`prepare_inference_runners()` 把已校验的 AvatarConfig 传给插件自身的选择器。Worker 重建所选计划；所选 runner 在初始化期间、开始处理实时请求之前解析并加载模型。导入和工厂注册不得下载或加载模型。更改启用的组件需要重启应用。

`InferenceRunner` 是一个执行契约，不是全局 runner 注册表。下载、离线使用和清理见[模型缓存](../docs/models-cache-layout.md)，已存储的个人数据与备份见 [Avatar 工作区](../docs/avatar-workspace-layout.md)，完整配置见[示例](../examples/README.md)。

## 工作区维护

将新包放在合适的分层下，并让其公开命名空间独立于物理目录。更改包布局时，同步更新工作区源、发布包列表、依赖和锁文件。

保留包内相对资源，并更新相对于仓库的路径、可编辑源和文档链接。AIRI 仍是 Character 的子模块。保留其固定的修订版本；源码层面的生命周期集成并不能证明真实的渲染器／RTC 验证已经成功。

```bash
uv lock --check
uv sync --all-packages --locked
```

插件目录中每个插件添加一行，而不是每个处理器或后端各一行。明确标出计划中和不受支持的集成。参见[贡献指南](../CONTRIBUTING.md)和 [v0.6.8 开发版发布说明](../docs/releases/v0.6.8.md)；原生 Host 取代了 Agents SDK 的 worker 托管，但全新安装验证以及真实 RTC／渲染器验证仍是单独的要求。
