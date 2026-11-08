# AlphaAvatar 编码 Agent 指南

[English](AGENTS.md) · [项目概览](README.md) · [开发](CONTRIBUTING.md)

本文是面向编码 Agent 的仓库导航指南。
用于查找一项变更的职责归属、契约、实现及相关检查。
详细行为应保留在链接指向的源码和文档中，不在此重复。
路径均相对于仓库根目录；下文的 shell 命令也从该目录运行。

## 1. 从这里开始

只阅读任务所需的部分，再沿实现及其消费者继续查阅。

| 问题 | 首先查看 |
| --- | --- |
| 项目要构建什么？ | [开发目标](#2-开发目标)和[路线图](docs/ROADMAP.md)。 |
| 变更归哪个包负责？ | [工作区地图](#3-工作区地图)和[依赖边界](#4-依赖边界)。 |
| 一次交互如何运行？ | [运行时职责归属](#5-运行时职责归属)，再查看相关输入／输出章节。 |
| 某个标识表示什么？ | [标识参考](docs/identifiers-zh.md)。 |
| 代码应如何组织？ | [编码规则](#18-编码规则)和[编码约定](docs/coding-conventions.md)。 |
| 如何运行或验证？ | [开发检查](#19-开发与验证)和 [CLI 文档](docs/cli/README.md)。 |
| 已知缺陷在哪里？ | [缺陷登记](docs/bugs-zh.md)；根据当前源码核实各条记录。 |
| 为什么做出某项修改？ | 按相关日期／任务查阅 [Agent 工作记录](docs/agent-logs/)。 |

修改代码时，同时定位其公开契约和所有受影响的消费者。
进行审查时，先确认要求审查的提交／引用，并区分源码审查与运行时验证。
工作区中已有的改动属于各自作者；保留无关工作。
明确本次任务的范围，并继续完成用户已经授权的工作。

## 2. 开发目标

AlphaAvatar 是可自行托管、可配置、可插拔的实时多模态个人助理。
长期方向是能够持续记忆、理解并采取行动的助理。

- 面向移动设备及其他个人设备设计，同时支持桌面和服务器执行。
- 保持统一、可组合的运行时架构，逐步支持设备与云端协作。
- 优先采用模块化能力，而不是另建功能削减的移动端架构。
- 保持交互链路异步、响应及时且支持全双工。
- 让输入接收、理解、生成和播放可以独立推进。
- 让丢失、取消、过期工作和部分完成可被观测。
- 明确个人数据的归属和私有上下文的访问。
- 由模型提供各项能力，避免将框架变成不透明的模型封装。
- 复用类型化契约和运行时服务，不在 Core 中重复维护插件状态。

这些是设计目标，不表示所有平台或部署拓扑均已可用。
当前 Host 使用 Python 3.13 和 POSIX 执行监督。
已实现的 RTC 后端是 LiveKit；通用后端契约不表示已有其他实现。
App 目录目前只为未来客户端工作预留；Host 无需 App 即可运行。
移动端运行时交付、其他传输方式和持久执行恢复仍是独立工作。

计划中的里程碑及其注明的状态见 [docs/ROADMAP.md](docs/ROADMAP.md)。
修改行为前，通过当前代码和测试确认实际行为。
发布说明和带日期的实验记录只描述各自版本与条件下的情况。

## 3. 工作区地图

Python 工作区包含四个基础包和十二个插件包。
根目录的 `pyproject.toml` 定义共享开发工具和工作区成员。
每个发行包各自维护运行时依赖元数据和资源。

| 位置 | 职责 | 优先阅读 |
| --- | --- | --- |
| `avatar-core/` | 与传输无关的媒体、事件、时钟、生命周期和运行时契约。 | [Core README](avatar-core/README.md)。 |
| `avatar-agents/` | Engine、Agent 契约、运行时组合、能力和推理。 | [Agents README](avatar-agents/README.md)。 |
| `avatar-rtc/` | 使用 Core 契约的传输适配器。 | [RTC README](avatar-rtc/README.md)。 |
| `avatar-host/` | CLI、应用启动、配置、进程、会话、setup 和 Doctor。 | [Host README](avatar-host/README.md)。 |
| `avatar-plugins/foundation/` | Context、Loop、Provider 和 Voice 的实现。 | [插件边界](avatar-plugins/README.md)。 |
| `avatar-plugins/perception/` | Router、Memory、Persona、Character 和 Status。 | [插件目录](README.md#alphaavatar-plugins)。 |
| `avatar-plugins/tools/` | DeepResearch、MCP 和 RAG。 | [插件边界](avatar-plugins/README.md)。 |
| `avatar-app/` | 为客户端／App 预留的范围；尚未提供可安装的 App。 | [App README](avatar-app/README.md)。 |
| `examples/` | 完整配置示例及配套示例。 | [示例 README](examples/README.md)。 |
| `tests/fixtures/` | 共享小样本及按需启用的大样本清单。 | `conftest.py` 和样本清单。 |
| `packaging/linux/` | Linux 包构建、安装及能力 wheel。 | [Setup 指南](docs/cli/setup.md)。 |
| `scripts/` | 质量、文档、维护和发布工具。 | [任务导航](#21-常见改动路径)。 |
| `docs/` | 指南、CLI 参考、路线图、部署、发布历史和 Agent 记录。 | [文档索引](#22-文档索引)。 |

`avatar-app` 不是 Python uv 工作区成员。
插件分层目录用于组织仓库，不会增加 Python 命名空间层级。
保留共享的 `alphaavatar` 命名空间包；不要添加命名空间根级的 `__init__.py`。

## 4. 依赖边界

移动代码或共享行为时，保持依赖方向。

| 消费方 | 架构允许的依赖 |
| --- | --- |
| Core | 标准库／已声明的底层依赖；不依赖 Agents、Host、插件或 RTC。 |
| Agents | Core 及其已声明的执行抽象；不承担 Host 的职责。 |
| RTC | Core；通过相关可选 extra 引入后端库。 |
| Host | Agents、Core 及选定的 RTC／应用集成。 |
| 插件 | Agents／Core 契约和明确借用的共享服务。 |

核心方向是 **RTC → Core**、**Agents → Core**、**Host → Agents**。
RTC 需要 Agent 行为时，通过注入的回调获得。
Core 不得导入模型 SDK、具体插件或承担 LiveKit 的管理职责。
将 SDK 类型留在适配器边界，不放入公开媒体／输出 schema。
原生链路不使用 `livekit.agents` 及其 worker／AgentSession 生命周期。
Ruff 明确禁止导入这一已移除的 SDK API。
不要将过时的桥接重新建成并行执行链路。

## 5. 运行时职责归属

增加状态、后台任务或关闭操作之前，先找到负责管理它的组件。

| 所属组件 | 管理内容 | 实现入口 |
| --- | --- | --- |
| Host application | 共享服务、执行监督、健康状态和信号。 | [application/](avatar-host/alphaavatar/host/application/)。 |
| Host execution | 子执行实例的 Engine 和 AvatarRuntime 生命周期。 | [execution/](avatar-host/alphaavatar/host/execution/)。 |
| Session attachment | 输入／输出适配器、订阅和连接附着。 | [sessions/](avatar-host/alphaavatar/host/sessions/)。 |
| SessionRuntime | 参与者、已接受的身份绑定及会话事件。 | [session/](avatar-core/alphaavatar/core/session/)。 |
| AvatarRuntime | 组合状态、Core 运行时、Foundation、参与者和能力。 | [runtime.py](avatar-agents/alphaavatar/agents/runtime/runtime.py)。 |
| PerceptionRuntime | 观测／标注发布、来源谱系和时序证据。 | [perception/](avatar-core/alphaavatar/core/perception/)。 |
| TurnRuntime | 已提交的输入快照及其独立消费者。 | [turn/](avatar-core/alphaavatar/core/turn/)。 |
| OutputRuntime | 输出准入、交付、执行观测和规范记录。 | [output/](avatar-core/alphaavatar/core/output/)。 |
| AvatarEngine | 轮次准入、重复／过期输入隔离和前台中断。 | [engine.py](avatar-agents/alphaavatar/agents/avatar/engine.py)。 |
| FoundationRuntime | 共享的 Context、Loop、Provider 和 Voice 服务。 | [foundation/](avatar-agents/alphaavatar/agents/runtime/modules/foundation/)。 |

消费者管理自己的任务、订阅和请求状态。
借用共享服务不意味着获得关闭该服务的权利。
断开传输、停止执行和持久化记录是不同的边界。
会话关闭不是唯一可以写入持久数据的时点。

## 6. 配置与插件选择

从选定的 bundle／文件及其生效配置入手，不要猜测默认配置。

| 关注点 | 入口 |
| --- | --- |
| Host 配置加载 | [host/configs/](avatar-host/alphaavatar/host/configs/)。 |
| 严格的 Avatar 配置 | [agents/configs/](avatar-agents/alphaavatar/agents/configs/)。 |
| 插件发现与设置校验 | [runtime/plugin/](avatar-agents/alphaavatar/agents/runtime/plugin/)。 |
| 运行时限制与保留策略 | [runtime_config.py](avatar-agents/alphaavatar/agents/configs/runtime_config.py)。 |
| 选择示例 | [examples/agent_configs/](examples/agent_configs/)。 |
| 编写 bundle／profile | [CLI 配置指南](docs/cli/config.md)。 |

- Host 在严格校验 AvatarConfig 之前读取顶层 `host` 部分。
- 主模型在 `loop.init_config.model` 下选择。
- Foundation 组件选择包括 `context`、`loop` 和 `voice`。
- 处理器专属的设置、提示词和模型规格由各自组件维护。
- 通过 `alphaavatar.<type>` 入口点发现已安装的实现。
- `AvatarModulePlugin` 校验设置，并声明选定的推理 runner。
- 注册和配置检查不得加载或下载模型。
- 工厂创建已配置的实例，不保存会话专属的可变状态。
- 可选 STT `language` 和 `prompt` 需要选定实现明确支持。
- 自动语言选择与固定语言提示具有不同语义。
- 当前更换选定组件需要重启应用。
- 执行子进程恢复经过校验的快照，不会再次解析 Avatar 工作区。

校验错误应指向实际选择或配置该插件的设置项。

## 7. 启动与关闭

使用所属组件的生命周期，不要为同一资源另加第二个管理器。

1. Host 解析配置、应用／工作区路径及选定服务。
2. 共享推理服务初始化选定的 worker 计划。
3. 执行实例装配 Session、AvatarRuntime、Foundation 和 Engine。
4. 附着端的输出先于 Engine 启动；Engine 消费者先于 Router 决策启动。
5. 执行实例可以接收工作后，再启动附着端的输入。
6. 关闭时停止接入输入，并通过各自负责的组件完成已接纳工作的收尾。

具体装配由 Host 实现；修改顺序时查阅源码。

- `LifecycleComponent` 提供异步 `on_start()` 和 `on_stop()`。
- `LifecycleGroup` 对阶段排序，同阶段的独立组件并发运行，停止时按相反阶段顺序执行。
- 部分初始化完成后，也必须负责清理。
- 并发关闭的调用方应共享同一个由所属组件管理的关闭操作。
- 调用方取消不能导致已接纳的清理工作被遗弃。
- 生产者收尾期间，保持规范记录消费者运行。
- 释放借用的订阅，不关闭共享运行时或房间。
- 保留有用的清理失败信息，不要悄然报告成功。

修改这些规则之前，阅读 [core/lifecycle.py](avatar-core/alphaavatar/core/lifecycle.py) 和
[core/cleanup.py](avatar-core/alphaavatar/core/cleanup.py)。
由 Host 的会话／执行策略决定终止；RTC 断连本身不负责销毁 Engine。

## 8. 感知与时序证据

输入是类型化的 `EnvObservation` 值；解释以标注形式到达。
Core 管理其谱系、事件顺序、保留策略和时序查询。

| 契约 | 含义 |
| --- | --- |
| `PerceptionSourceRef` | 来源身份及其世代。 |
| `PerceptionSegmentRef` | 由完整来源引用限定的语音片段。 |
| `PerceptionEntityRef` | 由所属来源限定的感知实体标签。 |
| 观测 ID | 一条观测，包括其载荷／引用和媒体时间。 |
| 标注 ID | 一条以证据为目标的解释记录。 |
| 事件序号 | 所属事件流内的发布顺序。 |
| 消费者 ID／游标 | 读取方及其在该流内已确认的进度。 |
| 感知 cutoff | 为已提交轮次捕获的保留证据边界。 |

不要将不同流的序号作为全局时钟比较。
发布顺序和媒体时间戳回答不同的问题。
消费者游标不标识说话者，也不定义轮次拥有的片段。
跨世代传递时使用完整的类型化来源／片段／实体引用。
证据丢失时，显式暴露缺口、遗漏数量和保留边界。
不要仅因原始观测已过期，就替换为更新的证据。

先查看 [PerceptionRuntime](avatar-core/alphaavatar/core/perception/runtime.py)，再查看
[感知 schema](avatar-core/alphaavatar/core/perception/schemas/) 和
[标识规则](docs/identifiers-zh.md)。

## 9. 语音模型与语音流

可复用的语音组件属于 Foundation Voice。
Router 拥有借用这些组件的流和任务。

| 事项 | 实现 |
| --- | --- |
| VAD 模型／工厂与 runner | [voice/vad/](avatar-plugins/foundation/avatar-plugins-voice/alphaavatar/plugins/voice/vad/)。 |
| 分段／实时 STT 实现 | [voice/stt/](avatar-plugins/foundation/avatar-plugins-voice/alphaavatar/plugins/voice/stt/)。 |
| TTS 供应商实现 | [voice/tts/](avatar-plugins/foundation/avatar-plugins-voice/alphaavatar/plugins/voice/tts/)。 |
| 音频活动与片段发布 | [router/audio_activity/](avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/audio_activity/)。 |
| 转录消费 | [router/speech/](avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/speech/)。 |
| 轮次端点评估 | [router/turn_taking/](avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/)。 |

- 规范化音频只发布一次，由独立消费者派生结果。
- VAD 片段边界不会自动成为对话轮次边界。
- 片段 ID 由语音链路分配，不由说话者识别分配。
- STT 结果保留原始片段及来源世代。
- 转录终态必须与消费者实际收到的内容一致。
- 区分上传、等待应答头、首个事件和最终事件的计时。
- 连接复用要求所属 HTTP 应答／正文的生命周期正确收尾。
- 供应商的分帧／解码细节保留在其适配器内部。
- 固定的语言提示不能无声地变成普遍适用的硬编码语言策略。
- prompt／language 实验不能证明所有语言或噪声音频的行为。
- VAD 延迟对照也需要正确的跨片段轮次处理行为。
- 对照测量结果时，保留样本身份和严格的通过标准。

支持的设置见 [Voice README](avatar-plugins/foundation/avatar-plugins-voice/README.md)。

## 10. 轮次判断与准入

轮次判断评估由观测和标注组成的时序输入流。
Persona 提供说话者／身份证据；轮次判断不识别人。

| 组件 | 职责 |
| --- | --- |
| `TurnTakingProcessor` | 消费感知／标注／轮次流，并拥有处理器生命周期。 |
| `TurnTakingCoordinator` | 维护输入窗口，协调评估、等待和发布。 |
| `InputWindow` | 输入成员、活动／已关闭片段、转录文本和修订号。 |
| `TurnEvidenceBuilder` | 根据输入和保留的时序上下文构造模型证据。 |
| `TurnAddressing` / `AddressingFusion` | 匹配并合并寻址证据。 |
| 轮次判断模型 | 通过声明的能力估计端点／交互证据。 |
| `TurnTakingPolicy` | 根据证据和评估生成动作。 |
| `AssessmentWork` | 替换、取消、追踪并回收异步评估任务。 |
| `AvatarEngine` | 校验提出的动作／输入，准入实际轮次。 |

实现：[turn_taking/](avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/)。
公开契约：[agents/router/](avatar-agents/alphaavatar/agents/router/)。

- `input_id` 标识提出的时序输入；`revision` 用于检测过期评估。
- 说话者／实体标签不会把端点音频拆成独立的人物候选。
- 端点 HOLD 让当前输入保持开放，接收后续语音并重新评估。
- 一旦确定端点，输入可在等待 STT 结果时封闭。
- 封闭输入的成员保持固定，同时下一份输入可以继续到达。
- 待处理记录服务于转录／准入生命周期，不是说话者登记表。
- 转录等待有观察点和固定的硬期限；重新评估不能延长期限。
- 新到达的语音必须保留其自身适用的转录预算。
- 提出的 `COMMIT` 标注不能证明 Engine 已经提交轮次。
- `TurnRuntime` 发布已接受的 `TurnSnapshot`；`_consume_turns()` 观察该确认。
- 按实际提交的证据边界推进，不能使用收到确认时的墙钟时间。
- 结束已确认输入时，保留较新或不属于该输入的内容。
- 已过期、来源世代已取消或证据不可用的提议可能被拒绝。
- Engine 的 `_inputs` 按输入记录已处理动作，以隔离重复处理。
- 该动作记账与权威的已提交轮次流相互独立。

修改这条链路时，检查转录先到／音频先到的顺序、取消和延迟确认。
同时检查自然停顿、多说话者、匿名片段和媒体时间重叠。

## 11. 参与者、身份与私有上下文

区分传输身份、感知实体、会话参与者和持久用户。

| 概念 | 所有者／入口 |
| --- | --- |
| 设备／传输端点 | RTC／Host 适配为 Core 会话契约。 |
| 说话者／人脸证据 | [Persona 处理器](avatar-plugins/perception/avatar-plugins-persona/alphaavatar/plugins/persona/processors/)。 |
| 片段关联与就绪状态 | [ParticipantRuntime](avatar-agents/alphaavatar/agents/runtime/modules/participants/)。 |
| 已接受的参与者／用户绑定 | [SessionRuntime](avatar-core/alphaavatar/core/session/)。 |
| 轮次准入时的主体解析 | `AvatarEngine._decision_actors()`；当前身份投影使用 `ParticipantRuntime.project_turn()`。 |
| 限于快照范围的 Persona 访问 | [persona/runtime.py](avatar-plugins/perception/avatar-plugins-persona/alphaavatar/plugins/persona/runtime.py)。 |

- 单凭麦克风、设备或主参与者，不能证明某个片段由谁说出。
- 局部实体标签不能独立确立持久用户身份。
- 一个时序轮次可以包含多个主体或未归属片段。
- 冲突证据不能授予私有用户身份。
- 关联就绪、身份推断和属性提取各有独立的完成时间。
- 尽早启动独立标注工作；只等待消费操作所需的依赖。
- 异步等待可以挂起一个任务，同时让其他输入任务继续运行。
- 轮次准入所需的依赖链不应等待无关的属性提取。
- 后续身份绑定变化时，保留已提交的历史归属。
- 缺少授权时，不能回退到主用户或设备关联来替代。

标识的生命周期和初始化入口见 [identifiers-zh.md](docs/identifiers-zh.md)。

## 12. Context、历史与模型输入

Context 拥有查询准备和规范历史。
Engine 不组装 prompt；Provider 不拥有对话历史。

| 事项 | 入口 |
| --- | --- |
| 查询准备与捕获的状态 | [context/manager.py](avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/manager.py)。 |
| 输入构造 | [context/builder/](avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/builder/)。 |
| 规范的用户／助手／工具历史 | [context/history/](avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/history/)。 |
| 请求内的历史投影 | [context/compressor/](avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/compressor/)。 |
| 公开 Context 契约 | [agents/avatar/context/](avatar-agents/alphaavatar/agents/avatar/context/)。 |

- 将 Builder 生成的用户消息保存为规范历史消息。
- 后续标注到达时，保留该消息捕获的媒体和输入结构。
- 不要为反映后来的身份或解释而改写已存储历史。
- 请求内的压缩／投影不能修改规范历史。
- 运行时上下文描述当前查询，不是规范历史中的工具活动。
- 为一次查询一致地捕获状态和能力，避免每一步都改写前缀。
- 区分键入文字与语音转录的呈现。
- 转录失败通知始终关联到受影响的输入片段。
- 历史通知不能被当作用户当前新发出的指令。
- 读取私有 Memory／Persona 时，使用适用的已接受身份和归属校验。
- 迟到收尾的工具结果保留原有执行和历史归属。

修改上下文时，同时检查首次模型请求和下一轮次复用的历史。
不要从旧 README 中的“有界历史”等表述推断当前契约。

## 13. Loop、Provider 与工具

前台链路是 Engine → Loop → Context／Provider／能力 → OutputRuntime。

| 事项 | 所有者／实现 |
| --- | --- |
| 模型／工具执行 | [Loop 插件](avatar-plugins/foundation/avatar-plugins-loop/alphaavatar/plugins/loop/)。 |
| 共享客户端与结构化任务 | [Provider 插件](avatar-plugins/foundation/avatar-plugins-provider/alphaavatar/plugins/provider/)。 |
| 流式后端契约 | [agents/avatar/provider/](avatar-agents/alphaavatar/agents/avatar/provider/)。 |
| 原生能力注册／调用 | [runtime/capability/](avatar-agents/alphaavatar/agents/runtime/capability/)。 |
| 外部工具实现 | [工具插件](avatar-plugins/tools/)。 |

- 一次 Run 可以包含多次模型请求和工具调用。
- 区分 `input_id`、`turn_id`、`run_id`、请求 ID 和工具 `call_id`。
- 将工具结果与原始调用配对；不要用工具名称作为关联键。
- 能力发现／注册本身不授予执行权限。
- 使用当前操作的策略和授权器；不要假定所有操作都只读。
- 结构化任务后端与原生流式后端的能力不同。
- Provider 共享不代表每个后端都适合实时 Loop。
- SDK 应答映射和错误处理保留在对应的供应商适配器中。
- 通过所属 Loop／输出契约发布规范记录。
- 连接或 worker 失败后，不要自动重放会改变状态的模型／工具工作。

沿所选实现追踪，不要在 MCP 内新增特定模型的推理。

## 14. 输出、合成与播放

Core `EnvOutput` 是生产者内容；`OutputEvent` 补充发布标识和时间。
Router 合成／同步语音；RTC 交付媒体并报告播放进度。

| 接口面 | 用途 |
| --- | --- |
| `OutputRuntime.stream` | 实时交付和呈现。 |
| `OutputRuntime.records` | 由 History／Memory 独立消费的规范批次。 |
| `OutputRuntime.execution` | 供 Status 和诊断使用的执行事实。 |
| 输出范围 | 所属上下文、轮次及可选 Run。 |
| 输出标识 | 由 lane／scope 限定的内容标识。 |
| 文本／音频对齐 | 合成／播放时间的关联和修订。 |

- 记录准入、数据库持久化和远端播放是不同的事实。
- 文本完成、音频完成和来源完成是不同阶段。
- 生成完成不会撤销仍在播放的音频。
- 显式中断以中断准入时解析出的标识为目标。
- 迟到回调不能把中断目标改成较新的 Run。
- 让合成保持其原生生产节奏；字幕交付不能拖慢 PCM 生产。
- 区分估计对齐与实测音频／播放计时。
- 最终计时修正时，保留已发出的字幕前缀。
- 明确终态发布和关闭的所有权。
- 一个订阅者看到终态事件，不能证明全部发布／清理已经完成。

参见 [Core 输出](avatar-core/alphaavatar/core/output/)、
[Router 语音](avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/speech/)，
以及 [RTC 音频](avatar-rtc/alphaavatar/rtc/livekit/audio/)。

## 15. Memory 与 Persona 持久化

Memory 和 Persona 消费共享运行时事实，并保留各自的业务／存储所有权。
它们的持久化规则不属于 Core 或 Engine。

| 事项 | 实现 |
| --- | --- |
| Memory 协调 | [memory/runtime.py](avatar-plugins/perception/avatar-plugins-memory/alphaavatar/plugins/memory/runtime.py)。 |
| 对话／环境／检索处理器 | [memory/processors/](avatar-plugins/perception/avatar-plugins-memory/alphaavatar/plugins/memory/processors/)。 |
| SQLite 权威记录与投影 | [memory/storage/](avatar-plugins/perception/avatar-plugins-memory/alphaavatar/plugins/memory/storage/)。 |
| 公开 Memory schema | [agents/memory/](avatar-agents/alphaavatar/agents/memory/)。 |
| 身份／资料协调 | [Persona 插件](avatar-plugins/perception/avatar-plugins-persona/alphaavatar/plugins/persona/)。 |

- 使用独立的消费进度，消费已提交轮次和规范输出记录。
- 保留原始所有者、参与者、上下文和来源引用。
- 区分权威记录与向量、图和 Markdown 投影。
- 集成多个生产者时，明确图／来源命名空间。
- 通过现有 commit／outbox／存储契约持久化。
- 失败批次在新数据到达后恢复时，不能覆盖后来到达的数据。
- 被动检索提供上下文线索；主动检索可以请求更精确的证据。
- 用户重新绑定不授予移动或暴露另一用户已存数据的权限。
- 历史上下文保持冻结，依赖当前身份的状态可以变化。
- 会话结束是一种收尾边界，不是通用的持久化触发器。
- 将处理器自身的生命周期、配置、prompt 和 Provider 放在一起。

阅读 [Memory README](avatar-plugins/perception/avatar-plugins-memory/README.md)
和 [Persona README](avatar-plugins/perception/avatar-plugins-persona/README.md)，再核对当前源码。

## 16. 推理 runner 与模型资源

InferenceRuntime 拥有 worker 进程和共享端点。
InferenceExecutor 拥有客户端连接，Host 负责监督服务。

| 事项 | 入口 |
| --- | --- |
| Runner 接口 | [inference/runner.py](avatar-agents/alphaavatar/agents/runtime/inference/runner.py)。 |
| Worker 选择、服务与池 | [runtime/inference/](avatar-agents/alphaavatar/agents/runtime/inference/)。 |
| 插件自身的 runner 计划 | 所选插件的工厂和 `inference.py`。 |
| 模型解析与离线策略 | [模型缓存指南](docs/models-cache-layout.md)。 |

- 从已验证的生效配置中选择 runner。
- 在适当的初始化路径中解析／下载模型文件，不要在模块导入时执行。
- 接受实时请求前，先初始化所选模型。
- 模型实现保留在所属插件中；流仍由消费它们的处理器拥有。
- 区分客户端可用性、排队等待和请求执行期限。
- 遵守配置的并发和 worker 限制，不要添加无界任务。
- Runner 初始化／失败不能全局拒绝其他无关且健康的方法。
- 取消必须完成所属请求及其资源的收尾。
- 调用方取消与 worker 进程终止是不同操作。
- 添加监督或诊断时，避免创建第二个进程所有者。
- 离线模式必须准确报告缺少的必需资源。

`ALPHAAVATAR_MODEL_OFFLINE=1` 禁用模型资源下载；远程供应商调用仍遵循各自配置。
不要把假 runner 的成功描述成真实模型或远程服务验证。

## 17. 应用路径与存储数据

路径有两个根：应用主目录，以及每个 Avatar 解析后的工作区。
路径构造与文件系统修改分别由不同组件负责。

| 事项 | 入口 |
| --- | --- |
| 应用主目录、设置、配置与共享缓存 | [Host ApplicationPaths](avatar-host/alphaavatar/host/workspace/application.py)。 |
| Avatar 工作区、用户与会话路径 | [Agents WorkspacePaths](avatar-agents/alphaavatar/agents/workspace/paths.py)。 |
| 显式准备应用目录 | [Host 工作区操作](avatar-host/alphaavatar/host/workspace/operations.py)。 |
| 显式准备 Avatar 目录 | [Agents 工作区操作](avatar-agents/alphaavatar/agents/workspace/operations.py)。 |
| 面向用户的布局与备份说明 | [工作区指南](docs/avatar-workspace-layout.md)。 |

- Host 默认选择平台数据目录；`ALPHAAVATAR_HOME` 或 YAML `application.home` 可选择另一个绝对根目录。
- 保留文档规定的配置、设置、缓存与 Avatar 组织方式。
- Avatar 工作区分别存放环境、用户、图、数据、日志与缓存。
- 会话路径保留路径与上下文契约采用的 SessionRuntime 创建日期。
- 避免对已经解析的工作区再次按 Avatar ID 解析。
- 将逻辑 ID 与文件系统安全的路径键分开保留。
- 校验路径时，不要隐式创建目录或修改全局环境状态。
- 不要将缓存、凭据或生成的运行时数据混入源码改动。

使用链接中的路径 API，不要在插件中重复构造目录。

## 18. 编码规则

代码顺序以 [docs/coding-conventions.md](docs/coding-conventions.md) 为准。
将 `core/perception/runtime.py` 与该文档列出的 Memory 模块作为风格示例。

- 遵循仓库的 Python 版本与 Ruff 配置，当前为 Python 3.13 和 Ruff 0.12.9。
- 优先编写直接、简洁且与相邻模块一致的代码。
- 合理长度的表达式保持在一行；格式化器的目标行宽为 100 列。
- 当行宽、嵌套或可读性需要时再拆行。
- 有用的注释应围绕所有权、不变量和不明显的顺序约束。
- 将处理器专属的业务逻辑放在其所属组件中。
- 在职责完整一致时提取辅助函数或类，不要仅为缩短文件而拆分。
- 快速迭代期间直接使用当前契约，除非任务要求兼容。
- 公共契约变更时，同步迁移消费者、测试、示例与诊断。
- 不要默认保留旧别名或并行的历史实现路径。

模块与类的组织顺序：

1. 现有许可证头、future import，然后依次为标准库、第三方、绝对路径与相对路径导入。
2. 适当时将仅用于类型的依赖放在 `TYPE_CHECKING` 下。
3. 模块私有辅助函数和类放在使用它们的公共代码前。
4. 类文档字符串、分组常量、构造函数、属性和静态方法。
5. 私有方法放在调用它们的方法前；相互递归的方法例外。
6. 功能分区可使用 `"""Input event operations"""` 这样的独立字符串。
7. 每个分区内，私有辅助方法放在公共入口前。
8. 生命周期实现放在生命周期入口前，生命周期方法放在最后。

命名与异步所有权：

- 要求调用时已持锁的方法以 `_locked` 结尾。
- 后台消费循环使用 `_consume_*`。
- 任务完成回调使用 `_*_done` 或 `_observe`。
- 跟踪创建的任务，并观测其终态异常。
- 避免在事件循环上执行阻塞 I/O 或繁重的模型工作。
- 使用现有 runner，或合适的异步／移出事件循环线程的执行边界。
- 按契约为队列、待处理记录和保留的上下文设置界限。
- 在成功、失败、取消和部分启动时，都释放自己拥有的资源。

不要仅为无关的风格整理而重排未改动的模块。

## 19. 开发与验证

完整工作流见 [CONTRIBUTING.md](CONTRIBUTING.md)。
使用 `.python-version`、`pyproject.toml` 和 `uv.lock`，不要自行猜测依赖版本。

准备 Python 工作区：

```bash
uv sync --all-packages --locked
uv pip check --python .venv/bin/python
```

检查结构、锁文件与代码风格：

```bash
uv lock --check
uv run --no-sync python scripts/quality/check_workspace.py
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
git diff --check
```

先运行相关的确定性离线测试：

```bash
PYTHONDONTWRITEBYTECODE=1 ALPHAAVATAR_MODEL_OFFLINE=1 \
  uv run --no-sync pytest -p no:cacheprovider path/to/affected/tests
```

当改动跨越契约时，使用同一环境运行完整测试集：

```bash
PYTHONDONTWRITEBYTECODE=1 ALPHAAVATAR_MODEL_OFFLINE=1 \
  uv run --no-sync pytest -p no:cacheprovider
```

将示例测试路径替换为实际所属包的测试路径。
大样本通过现有 `large_samples` 标记与 fixture 按需启用。
`alphaavatar test` 是计划中的 CLI 命令，目前不能代替 pytest。
适当时运行 pre-commit 检查；hook 可能修改文件，因此要检查其输出。
整个工作区的 CI 还会检查改动文件之外的格式与安装。
确认验证没有留下字节码、缓存或其他意外的工作区改动。
隔离解释器可能忽略通过环境变量控制字节码的设置；应在其所属边界传入参数。
如果检查被环境阻塞，报告准确的命令或阶段，以及剩余未覆盖的内容。
不要仅为让改名后的 API 通过旧测试而削弱断言或严格校验。

## 20. 打包、发布与真实服务验证

修改打包或发布自动化前，先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

- 包布局变更会影响工作区成员、来源、依赖与发布包清单。
- 保持 `uv.lock` 一致，并检查依赖变化。
- 每个发行包负责自己的 README、版本、资源与 Apache 许可证副本。
- 使用受锁文件约束的工作流构建，并用 Twine 检查生成的元数据。
- `--no-sources` 用于检查构建是否独立于可编辑工作区覆盖。
- 构建出 wheel 不代表完整安装或服务运行已经通过验证。
- GitHub Release 不代表所有工作区包都已存在于 PyPI。
- 由标签触发的 GitHub Release 创建，与手动向包索引发布，是不同的工作流。
- Linux 包的构建与安装，和可编辑的源码工作区不同。
- 将已安装包的验证与源码树测试分开。

真实服务检查使用生效配置与现有的外部服务控制选项。
Doctor 在已授权或已配置时可能下载模型或调用远端供应商。
不要让导入或文档检查顺带触发计费实验。
区分离线桩、真实模型推理、远端端点、RTC 与渲染器验证。
报告耗时时，记录样本与配置身份、失败情况，以及预热或首次运行条件。
不要仅凭少量延迟样本就声称端点行为正确。

工作流入口：[.github/workflows/](.github/workflows/)、
[packaging/linux/](packaging/linux/) 与 [scripts/maintenance/](scripts/maintenance/)。

## 21. 常见改动路径

使用下表，避免从方便但不承担该职责的模块入手。

| 任务 | 沿此路径检查 |
| --- | --- |
| CLI 参数、帮助或默认值 | Host `cli/` → 命令实现 → `docs/cli/` → CLI 测试。 |
| Bundle/profile 选项 | Host `configs/` → Agents 配置 → 插件校验 → 示例与 CLI 文档。 |
| 启动或子进程清理 | Host application/execution/processes → 生命周期所属组件 → 生命周期测试。 |
| RTC 输入或输出 | RTC 适配器 → 注入的 Core 契约 → Host 装配 → 适配器测试。 |
| VAD 或片段计时 | Voice VAD → Router 音频活动 → 来源与片段证据 → 计时测试。 |
| STT 请求或终态 | Voice STT → Router 转录 → 轮次判断截止时间与准入 → Doctor。 |
| 自然停顿或过早提交轮次 | 轮次判断窗口、证据、模型与策略 → Engine 准入 → 多片段测试。 |
| 说话者就绪或私有身份 | Persona 处理器 → ParticipantRuntime → Session 绑定 → 轮次主体与上下文检查。 |
| 提示词、历史或媒体重放 | Context manager/builder/history → Provider 模型输入 → 下一次查询的历史测试。 |
| 工具授权或结果归属 | 能力注册表 → Loop tools/execution → Provider 记录 → 身份检查。 |
| TTS 或字幕中断 | Router speech → OutputRuntime 精确范围 → RTC 播放反馈 → 关闭与取消测试。 |
| Memory 持久性或检索 | Memory 处理器 → storage commit/outbox → 投影 → 归属过滤。 |
| Runner 并发或超时 | 插件选择 → InferenceRuntime/pool/executor → runner 所有权测试。 |
| 模型下载或离线行为 | 插件模型规格 → 现有缓存解析器 → 离线测试与缓存指南。 |
| Doctor 指标 | 生产者追踪边界 → Core 追踪 schema → Host 测量 → 对比脚本、测试与文档。 |
| 新插件或包 | 插件边界指南 → 入口点与工厂 → 元数据、工作区与锁文件 → 目录与测试。 |
| 未来的 App 展示 | App 设计与实现 → Core/RTC 交付契约 → 前端检查。 |
| 部署或安装 | Host/setup 或 packaging → `docs/DEPLOY.md` 与 setup 指南 → 安装验证。 |

重命名契约前，用 `rg` 搜索其构造函数、序列化器与消费者。
修改追踪字段时，同时检查生产者与离线报告重建。
修改身份时，除展示标签外，还要检查范围、持久化与取消。

## 22. 文档索引

当前 `docs/` 下的每个非日志文件都列在下表中。
`agent-logs/` 作为一类历史工作记录列出，不按每份产物建立 API 索引。
新增或移动文档时，保持本表与英文对应表同步。

| 文档 | 用途与阅读时机 |
| --- | --- |
| [ROADMAP.md](docs/ROADMAP.md) | 运行时、能力与客户端的开发方向和里程碑状态。 |
| [DEPLOY.md](docs/DEPLOY.md) | Linux 与源码部署、服务配置、凭据和操作流程。 |
| [coding-conventions.md](docs/coding-conventions.md) | 模块与类的顺序、功能分区字符串和方法命名。 |
| [identifiers-zh.md](docs/identifiers-zh.md) | 标识含义、所有者、唯一性与生命周期、初始化和关联规则。 |
| [avatar-workspace-layout.md](docs/avatar-workspace-layout.md) | 应用与 Avatar 数据布局、个人数据、日志和备份边界。 |
| [models-cache-layout.md](docs/models-cache-layout.md) | 模型缓存的所有权、解析、下载、离线行为和清理。 |
| [bugs-zh.md](docs/bugs-zh.md) | 已知缺陷、修复和暂缓处理的观察；根据当前修订核实状态。 |
| [cli/README.md](docs/cli/README.md) | CLI 导航、可用与计划中的命令、配置和退出行为。 |
| [cli/config.md](docs/cli/config.md) | Bundle/profile 创建，以及生效配置的检查与校验。 |
| [cli/setup.md](docs/cli/setup.md) | Linux 安装环境，以及可选能力与依赖的安装配置。 |
| [cli/doctor.md](docs/cli/doctor.md) | 静态与运行时诊断、外部服务控制、报告、证据和计时指标。 |
| [cli/dev.md](docs/cli/dev.md) | 开发模式启动、默认值、日志和支持的选项。 |
| [cli/start.md](docs/cli/start.md) | 服务模式启动、配置覆盖和运行行为。 |
| [cli/test.md](docs/cli/test.md) | 计划中的 Agent 能力测试命令；目前还不是已实现的 CLI 入口。 |
| [cli/cli.html](docs/cli/cli.html) | 已记录的 CLI 展示图集；属于示例输出，不是实时服务或基准测试证据。 |
| [releases/v0.6.1.md](docs/releases/v0.6.1.md) | 查阅 v0.6.1 的人脸识别、视觉身份、声脸融合与 Persona 持久化变更。用于了解该历史版本。 |
| [releases/v0.6.2.md](docs/releases/v0.6.2.md) | 查阅 v0.6.2 的统一 Provider 与嵌入、追踪、运行时与多参与者基础，以及嵌套配置迁移。用于了解该历史版本。 |
| [releases/v0.6.3.md](docs/releases/v0.6.3.md) | 查阅 v0.6.3 的图感知 Memory、节点提及与别名、会话局部实体键，以及 LanceDB 检索。用于了解该历史版本。 |
| [releases/v0.6.4.md](docs/releases/v0.6.4.md) | 查阅 v0.6.4 的 Core 感知流、共享载荷与标注、AvatarRuntime、视觉消费者和在线环境记忆。用于了解该历史版本。 |
| [releases/v0.6.5.md](docs/releases/v0.6.5.md) | 查阅 v0.6.5 的共享音频、Router VAD/STT、持久隔离的推理进程，以及消费者所有权与游标模式。用于了解该历史版本。 |
| [releases/v0.6.6.md](docs/releases/v0.6.6.md) | 查阅 v0.6.6 的统一计时与多模态对齐、不可变轮次、供应商中立输入、Output，以及按播放节奏推进的转录。用于了解该历史版本。 |
| [releases/v0.6.7.md](docs/releases/v0.6.7.md) | 查阅 v0.6.7 的原生语义寻址、对话焦点、Smart Turn、寻址融合、全双工中断与精确轮次快照。用于了解该历史版本。 |
| [releases/v0.6.8.md](docs/releases/v0.6.8.md) | 查阅 v0.6.8 的原生 Host/RTC 所有权、Foundation 与处理器插件、流式模型、工具与语音执行、CPython 3.13 和迁移。用于了解该历史版本。 |
| [agent-logs/](docs/agent-logs/) | Claude 与其他 Agent 对项目改动、验证和未完成工作的按日期记录。 |

仓库的其他入口：

- [README.md](README.md)：产品概述、架构摘要、安装和插件目录。
- [CONTRIBUTING.md](CONTRIBUTING.md)：开发环境、检查、打包与发布工作流。
- 各包 README：局部职责、设置和支持的集成。
- [示例 README](examples/README.md)：配置示例；按当前 Host CLI 核实命令。
- 工作流 YAML 与脚本：CI 和构建行为的可执行来源。

旧文档可能保留早期实现的术语。
遇到不一致时，以当前源码、契约和实际验证为准，并随改动修正相关文档。

## 23. Agent 工作记录

`docs/agent-logs/` 用于说明 Claude 与其他编码 Agent 在 AlphaAvatar 上完成的工作。
按相关任务与日期阅读，不要将全部历史载入上下文。

有用的记录内容包括：

- 任务目标，以及审查或修改的源码修订。
- 架构与实现决策及其理由。
- 改动模块与重要的契约迁移。
- 验证命令、结果和实质性的环境限制。
- 适用时，记录真实服务条件与简明结论。
- 剩余缺陷、未解决的问题和下一项具体步骤。

链接到所属指南或缺陷条目，不要重复大篇幅规格。
将索引保留在目录层级，避免每新增一条按日期记录就扩充本指南。
现有实验转储是对应运行的辅助证据，不是当前运行时契约。
不要将生成的脚本、模型缓存、安装目录或大量原始报告作为常规工作日志加入。
绝不包含凭据、私有环境文件或不必要的个人与媒体内容。
不要暗中重写旧记录，让历史结果与新代码一致。
编辑或移除已有证据集合，属于另行限定范围的维护任务。

## 24. 完成改动

交付前，检查实际行为以及受影响的导航。

- 将实现保持在其所属层级与生命周期内。
- 一起迁移所有受影响的契约与消费者。
- 改动涉及异步执行时，验证取消、过期工作与清理。
- 对行为使用有意义的回归检查；仅改文档时，需要校验链接与路径。
- 报告运行了什么、哪些通过，以及哪些仍未验证。
- 区分特定 SHA 对应的已安装构建、源码测试、远端服务与 CI。
- 路径或契约移动后，更新相关示例、文档与两份导航文件。
- 不要将生成的运行时文件与无关改动混入交付内容。
- 遵循用户要求的输出格式与提交、推送范围。

让本指南保持导航用途：增加稳定的入口与所有权规则，而不是不断扩大的事故流水账。
