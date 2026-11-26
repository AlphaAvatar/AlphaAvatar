# AlphaAvatar 路线图

[English](ROADMAP.md)

本文件是 AlphaAvatar 路线图的中文版，与英文版 [ROADMAP.md](ROADMAP.md) 同步维护：按版本记录已交付、开发中和计划中的工作。两份文件是路线图唯一的维护来源，文档站的 Roadmap 页面由它们生成，Agent 直接阅读。某个版本实际交付了什么，见对应的 [Release 文档](releases/)；系统当前如何工作，见技术文档，例如[标识参考](identifiers-zh.md)。本路线图链接这些文档，不替代它们。

## 目标

> **构建通用的多模态个人助手**，能通过流式的语音、文字、图像和视频输入识别用户。

> 它应具备**自我记忆**、**用户画像感知**、**自主反思**、**规划能力**、**持续自我进化**和**实时交互反馈**。

> 助手将与主流外部工具和个人工作区**无缝集成**，高效解决实际问题。

<a id="reading-this-roadmap"></a>
## 阅读说明

- **里程碑**是一个版本，或两个分组之一：`earlier`（v0.6.5 及之前已交付）和 `backlog`（未排期）。
- 每个**事项**有稳定的 ID，格式为 `<领域>-<编号>`。事项改到其他里程碑时只移动所在的行，ID 不变；ID 不重复使用。领域代码见[领域](#areas)。
- 三件事分开记录：事项的**状态**、它的目标**里程碑**、里程碑的**发布**状态。一个版本中的事项完成，不代表该版本已经发布。
- 日期保留原有精度：已完成事项记到月份，发布记到 GitHub Release 的发布日（UTC）。`—` 表示没有。
- [规划说明](#planning-notes)记录的是方案，不是当前行为。
- 表格中的状态值保留英文，两种语言版本相同，便于工具解析。

| 事项状态 | 含义 |
| --- | --- |
| `proposed` | 已列出，但是否做、怎么做尚未决定。 |
| `planned` | 已纳入该里程碑，尚未开始。 |
| `in-progress` | 已开始，说明中写明进展位置。 |
| `implemented` | 已在源码中实现，验证尚未完成。 |
| `done` | 已实现并验证；属于已发布里程碑的，随该版本交付。 |

| 发布状态 | 含义 |
| --- | --- |
| `released` | 已打 tag 并发布为 GitHub Release，有 Release 文档。 |
| `in-development` | 有开发分支，尚未发布。 |
| `planned` | 尚未开始。 |
| `unscheduled` | 未分配到版本。 |

<a id="timeline"></a>
## 时间线

| 里程碑 | 版本 | 主题 | 发布 | 发布日期 | Release 文档 |
| --- | --- | --- | --- | --- | --- |
| [`earlier`](#earlier) | v0.1.0–v0.6.5 | v0.6.5 及之前的基础 | released | 2025-11-13 – 2026-07-25 | 各条目版本未核实 |
| [`v0.6.6`](#v0.6.6) | v0.6.6 | 统一时间、多模态对齐与能力感知 | released | 2026-08-17 | [v0.6.6](releases/v0.6.6.md) |
| [`v0.6.7`](#v0.6.7) | v0.6.7 | 原生轮次判断、语义寻址与全双工打断 | released | 2026-09-05 | [v0.6.7](releases/v0.6.7.md) |
| [`v0.6.8`](#v0.6.8) | v0.6.8 | 原生 Host、运行时能力与实时语音 | released | 2026-10-22 | [v0.6.8](releases/v0.6.8.md) |
| [`v0.6.9`](#v0.6.9) | v0.6.9 | 语音可靠性、参与者归属与独立安装 | released | 2026-11-25 | [v0.6.9](releases/v0.6.9.md) |
| [`v0.7.0`](#v0.7.0) | v0.7.0 | 配置与版本、新 Web／App UI、安装配置启动引导、文档与 Roadmap、Demo 稳定性 | in-development | — | 分支 `dev/v0.7.0` |
| [`v0.7.1`](#v0.7.1) | v0.7.1 | 工具层插件 | planned | — | — |
| [`v0.7.2`](#v0.7.2) | v0.7.2 | 感知层插件与多人识别 | planned | — | — |
| [`v0.7.3`](#v0.7.3) | v0.7.3 | WebRTC 后端 | planned | — | — |
| [`v0.8.0`](#v0.8.0) | v0.8.0 | 独立于交互连接的 Avatar 执行 | planned | — | — |
| [`v0.8.1`](#v0.8.1) | v0.8.1 | 配置初始化；其余范围待定 | planned | — | — |
| [`backlog`](#backlog) | — | 长期，未排期 | unscheduled | — | — |

## 即将进行

<a id="v0.7.0"></a>
### v0.7.0 · 配置与版本、新 Web／App UI、安装配置启动引导、文档与 Roadmap、Demo 稳定性

- **发布：**in-development · 分支 `dev/v0.7.0`
- **顺序：**统一配置与版本管理 → Figma／Web／App 新 UI → 安装、配置和启动引导 → 文档与 Roadmap → Demo 稳定性及体验验收。
- **验收路径：**打开 Web／App → 引导安装或连接 Host → 图形化配置并保存 → Doctor 诊断 → 启动和交互 → 查看状态、定位问题及完成更新。
- **未定：**App 首批交付哪些平台、各平台支持的本地／远程 Host 连接方式（APP-01）；是否提供 TUI 或 Agent 配置入口（APP-02）。

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CFG-01` | **统一的配置体验** — 在已有的 bundle、profile 和 Host 配置服务上，统一 CLI、Web、App 的配置体验与文档。图形化入口复用现有的配置、校验和凭据逻辑，保留手动编辑配置文件的方式。 | planned | — | 跟踪 O-37（`consolidation.item_ops` 在运行时不起作用）；修复方案未定 |
| `CFG-02` | **版本管理** — 统一系统版本号管理：明确的版本来源、构建标识和组件版本展示，减少各 Python 包、CLI、Web／App 及发布产物之间的重复维护。 | planned | — | 相关：RUN-22 |
| `UI-01` | **基于新 Figma 设计的产品 UI** — 基于新 Figma 设计，统一 Web 和 App 的视觉规范与交互流程，覆盖首次使用、配置、连接、运行状态和故障诊断。 | planned | — | 设计进度不在此记录 |
| `WEB-09` | **AlphaAvatar-web 新 UI** — 将新 UI 引入 AlphaAvatar-web，完善 Demo 的连接、语音／视频交互、状态展示和错误反馈。 | planned | — | 独立仓库；相关：WEB-07 |
| `APP-01` | **avatar-app 新 UI 与首批平台** — 将新 UI 引入 `avatar-app`，明确 Web、桌面、iOS 的首批交付范围，以及各平台支持的本地 Host／远程 Host 连接方式。 | planned | — | `avatar-app` 目前只有 README；平台范围未定 |
| `APP-02` | **安装、配置和启动引导** — 在 App 中引导用户完成 Host 安装或连接、首次配置、凭据填写、Doctor、启动／停止和升级。优先完成图形化流程。 | planned | — | TUI 和 Agent 配置作为可选入口评估 |
| `DOC-01` | **文档组织** — 整理 AlphaAvatar、AlphaAvatar-web 和 AlphaAvatar-docs 的文档，统一安装、配置、架构、开发和部署导航；按实际落地的新 UI 更新 README、截图和示例。 | in-progress | — | 本仓库：[文档清单](manifest.yaml) 和本路线图；其他仓库和基于新 UI 的更新尚未开始 |
| `DOC-02` | **Roadmap 页面** — 在文档站建立独立的 Roadmap 页面，以仓库中的路线图（中英两版）为唯一维护来源，仓库保留清晰入口，统一展示规划、进行中和已完成的事项。 | in-progress | — | 仓库中的路线图已为此改为版本时间线；文档站页面尚未实现 |
| `OPS-01` | **Demo 部署** — 优化 Demo 部署：配置、健康检查、日志、更新和故障恢复，部署可重复，日常演示稳定。 | planned | — | — |
| `QA-02` | **v0.7.0 的 Agent 测试** — 把基于 Agent（Claude、Codex 等）的缺陷查找和测试扩展到新 UI、配置生成、Host 连接、安装引导和 Demo 部署，贯穿开发和验收。 | planned | — | — |

<a id="v0.7.1"></a>
### v0.7.1 · 工具层插件

- **发布：**planned
- **重点：**工具层插件的优化。
- **未定：**是否纳入 RAG 优化（RAG-13）；RAG 与 Files 是否合并（FIL-01）；是否纳入流式语音和 embedding 调研（VOI-02）。

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `DRS-07` | **改进 DeepResearch** — 优化 DeepResearch 插件。 | planned | — | 范围未定；候选为 DRS-03～DRS-06 |
| `RAG-13` | **改进 RAG** — 优化 RAG 插件。 | proposed | — | 是否纳入待定；候选为 RAG-07～RAG-12 |
| `FIL-01` | **Files 插件** — 引入 Files 插件。 | proposed | — | RAG 与 Files 是否合并为一个插件未定 |
| `MCP-15` | **改进 MCP** — 优化 MCP 插件。 | planned | — | 范围未定；候选为 MCP-11～MCP-14 |
| `AGX-01` | **其他 Agent 作为子 Agent** — 让 AlphaAvatar 可以把其他 Agent（如 Claude Code、Codex、DeepSeek harness）作为子 Agent 接入。 | planned | — | — |
| `VOI-02` | **流式 STT、TTS 与 embedding 调研** — 调研更多厂商的流式 STT 和流式 TTS，优化 embedding。 | proposed | — | 是否纳入待定；见[滚动提交 STT](#pn-rolling-stt)；相关：RUN-23 |
| `QA-03` | **v0.7.1 的 Agent 测试** — 基于 Agent 的缺陷查找和测试。 | planned | — | — |

<a id="v0.7.2"></a>
### v0.7.2 · 感知层插件与多人识别

- **发布：**planned
- **重点：**感知层插件与多人识别的优化。
- **依赖：**多人场景的被动检索（MEM-36）和寻址输入（RTR-22）使用 Persona 各项的身份识别结果。

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `MEM-31` | **Memory 与 Persona 的多模态更新** — Memory 和 Persona 的更新引入多模态输入。 | planned | — | 相关：MEM-28 |
| `MEM-32` | **细粒度的记忆归属** — Memory 的更新关联到具体的 message、Turn 和 `user_id`，逐条确定记忆条目的归属。 | planned | — | 相关：O-29（混合批次）、MEM-26、MEM-30 |
| `MEM-33` | **环境的 Avatar 记忆** — 为 ENV 记忆添加 Avatar 记忆类型。 | planned | — | 目前 ENV 记忆归会话主参与者和 Avatar，经由其用户 owner 读取 |
| `MEM-34` | **工具的经验记忆** — 为工具记忆添加第二层级的经验记忆。 | planned | — | — |
| `MEM-35` | **更丰富的记忆来源引用** — 丰富记忆条目的 `source_ref`；目前记录的是消息、工具调用和结果，以及运行事件。 | planned | — | schema 另定义了感知来源、片段和实体三种，目前没有写入方；相关：MEM-22、MEM-31 |
| `MEM-36` | **多人场景的被动检索** — 被动检索考虑对话中的多个人。 | planned | — | 见[多人场景的被动检索](#pn-memory-recall) |
| `PER-29` | **可配置的画像详细度** — Persona 的 profile 详细度可配置，例如 YAML 配置；不配置时使用当前默认。 | planned | — | 原计划在 v0.6.10 |
| `PER-30` | **多角度人脸向量** — 为人脸的不同角度保留独立向量。 | planned | — | — |
| `PER-31` | **带缓冲带的跟踪阈值** — Persona 跟踪引入缓冲阈值（三段阈值）和策略，防止误匹配。 | planned | — | 相关：O-24、KD-41 |
| `PER-32` | **不确定的说话人与同段多人** — 说话人匹配处在阈值之间时，按阈值给出询问的不确定性通知；处理同一片段内多人说话的识别。 | planned | — | 相关：O-25 |
| `CTX-19` | **带用户 ID 的 XML 输入** — 注入给 Avatar、Persona 和 Memory Provider 的消息改用 XML，并带上 `user_id`。 | planned | — | — |
| `PER-33` | **按当前用户提取画像** — Persona profiler 按当前缓存的 `user_id` 提取。 | planned | — | — |
| `RTR-22` | **多人寻址输入** — 按多人识别结果格式化语义寻址的输入（XML）。 | planned | — | 相关：O-25（多人场景的寻址证据） |
| `PER-34` | **声画绑定** — 通过声音与人脸的绑定识别画面中谁在说话。 | planned | — | 相关：PER-28、VIS-11 |
| `PER-35` | **身份识别策略** — 更新身份识别策略。 | planned | — | 相关：AGT-12、PER-25 |
| `PER-36` | **Persona 的 Markdown 展示** — Persona 信息支持 Markdown 展示。 | planned | — | 相关：PER-21 |
| `QA-04` | **v0.7.2 的 Agent 测试** — 基于 Agent 的缺陷查找和测试。 | planned | — | — |

<a id="v0.7.3"></a>
### v0.7.3 · WebRTC 后端

- **发布：**planned
- **未定：**WebRTC 后端的实现边界，见 RTC-10。

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RTC-10` | **WebRTC 后端** — 在现有 LiveKit 后端之外实现一个 WebRTC 后端。 | planned | — | 已实现的 LiveKit 后端本身基于 WebRTC；新后端的边界未定：是否需要 LiveKit 服务、选用哪个库（此前提到过 aiortc）、信令如何实现；相关：RTC-08 |

<a id="v0.8.0"></a>
### v0.8.0 · 独立于交互连接的 Avatar 执行

- **发布：**planned
- **重点：**交互连接的生命周期与 Avatar 执行生命周期分离。
- **背景：**当前已有的标识和建议语义见[执行生命周期](#pn-execution-lifecycle)。

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `EXE-01` | **执行生命周期与连接分离** — 让 Avatar 拥有独立于交互连接的执行生命周期。 | planned | — | 见[执行生命周期](#pn-execution-lifecycle)；相关：RUN-19、RUN-28 |
| `EXE-02` | **Episode 管理** — 把 Episode 作为 Avatar 的活跃运行周期来管理。 | planned | — | `episode_id` 已存在，但没有这一生命周期 |
| `EXE-03` | **持久化 Context** — Context 可以跨会话和 Episode 持续存在。 | planned | — | `context_id` 已存在，但不会持久保存工作 |
| `EXE-04` | **执行关联与执行层 run_id** — 在 Context 和 Episode 之间关联执行；把 `run_id` 扩展到执行状态、追踪、重试和恢复。 | planned | — | `run_id` 已用于标识一次 Loop Run；早先的讨论把这一项放在 0.7.1 |
| `EXE-05` | **暂停与恢复** — 任务的暂停与恢复。 | planned | — | — |
| `EXE-06` | **基础的唤醒与休眠** — 基础的自动唤醒和休眠。 | planned | — | Host 尚未实现休眠／唤醒 |
| `EXE-07` | **Dream** — Dream 调度、后台反思与跨周期整理，以及唤醒抢占。 | planned | — | 相关：RFL-02 |
| `RFL-01` | **Reflection 插件** — 引入 Reflection 插件。 | planned | — | 原长期条目：构建 Reflection 插件 Alpha，总结近期记忆、工具结果、失败、重复的用户需求和行为改进 |
| `EXE-08` | **会话创建等待** — 新会话创建时不应让用户长时间等待。 | planned | — | 目前每次 dispatch 都启动一个执行进程并装配会话；Doctor 以 `session_ready` 报告这段耗时；原笔记中的 LiveKit Agents room 创建方式已在 v0.6.8 移除 |
| `EXE-09` | **停机后的恢复** — Host 停止后的数据恢复。 | planned | — | 持久执行恢复尚未实现 |
| `QA-05` | **v0.8.0 的 Agent 测试** — 基于 Agent 的缺陷查找和测试。 | planned | — | — |

<a id="v0.8.1"></a>
### v0.8.1 · 配置初始化；其余范围待定

- **发布：**planned
- **未定：**本版本其余范围待定。

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CFG-03` | **像 STT 一样校验 init_config** — 优化 `avatar-agents` 对 `init_config` 的校验，做法类似 STT 配置。 | planned | — | 相关：O-10（STT 模型在字段处校验）、O-27 |

## 已发布

<a id="v0.6.9"></a>
### v0.6.9 · 语音可靠性、参与者归属与独立安装

- **发布：**released · 2026-11-25 · [v0.6.9](releases/v0.6.9.md)
- **顺序：**语音时序与关联证据 → 配置公共服务与 CLI → Runner 并行与压力验证 → 安装、升级、清理及 Doctor。
- **验收路径：**干净 Linux 安装 → CLI 交互配置 → Doctor 验证并导出报告 → 启动、实际 LiveKit 通话和正常停止（维护者验收）→ 两份 0.6.9 构建之间升级 → 准备失败时原环境继续可用 → 安全清理旧环境。
- **Setup 流程：**能力选择 → Provider／模型选择 → 凭据收集 → 最终摘要与安装确认 → 安装依赖、校验、启用 Bundle → 成功结果和下一步。
- **版本计划原文及对应事项：**
  - 修复语音终态、取消和迟到结果处理链路，引入语音时序与关联证据，修复 TTS 语速 → RTR-14, VOI-01
  - 修复 Memory 失败批次恢复时覆盖新批次、造成事件丢失的问题。被动检索负责提供当前场景与历史记忆的关联线索，供后续主动检索精确定位 → MEM-18
  - 修复单人／多人场景下的用户解析、数据归属和覆盖问题，引入 ParticipantRuntime 统一参与者解析。SessionRuntime 迁移到 Core，Avatar Workspace 路径由 Agents 管理，应用目录和平台路径由 Host 管理，统一 ID 设计及文档 → AGT-11, AGT-16, AGT-17
  - Persona 支持多人 face／speaker 识别，统一感知实体、会话参与者与持久用户身份之间的关联 → PER-20
  - Runner 输入改为显式配置，移除对全局变量的隐式依赖 → RUN-15
  - 实现可配置的 Runner 并行，完成多路语音、队列压力和取消测试，并提供相应运行指标 → RUN-15, RUN-29
  - 补齐 Voice 给 Agent 的能力提示，优化 Context 插件结构及提示渲染 → CTX-18
  - 修复 turn-taking／addressing 链路，按实际 Turn 提交边界累计未提交输入，不再按 segment／speaker 独立判断。统一三分类 label，明确 HOLD、不确定超时决策及 notice → RTR-13
  - Memory 身份绑定优化和检索修复 → MEM-18
  - 引入新的 persona speaker vector 模型，支持短于推理窗口的原长推理与识别，并保留极短段累计策略；修复 speaker／face 向量更新和存储，按模型隔离声纹，优化匹配、tracking 及 Persona cache 退出去重 → PER-20
  - 简化复杂逻辑，统一身份字符串与 ID 契约，完善架构和标识符文档 → AGT-17
  - 引入独立 alphaavatar CLI 和 Linux 安装包，安装后可直接执行配置、启动、Setup、升级和清理等操作，无需激活开发环境或使用 uv run → RUN-17
  - 完善 Host 配置公共服务，引入 profiles／bundles、交互式 Setup 和凭据存储，统一配置校验、凭据优先级、环境加载及日志脱敏 → RUN-16
  - 完成事务式 upgrade 和独立 cleanup：在旁边准备并校验完整环境，成功后切换；准备失败时原环境继续可用。清理支持只读预览，并保护当前环境、依赖基础包和应用数据 → RUN-17
  - 完善 Doctor 自检及报告体验：一个入口串联静态检查与运行验证，覆盖纯语音和语音＋视觉，展示 Input → Context → Output 耗时、首字／首音频帧延迟、Runner 队列和失败阶段，并支持导出脱敏报告 → RUN-18
  - 建立基于 Agent 的开发审查与回归流程，补齐必要的确定性测试 → QA-01
  - 复用已有压力测试，补齐长时间运行、取消、队列积压和不同语音输入的覆盖验证；是否提供 alphaavatar test 入口另行确定。语音验证保留 input／segment／STT-final／Turn-cutoff 之间的有界关联证据 → RUN-29, QA-06

#### Agent 基础

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `AGT-11` | 新增 `ParticipantRuntime`：需要时从 Turn 的输入读取其参与者，已确定的语音和人脸关联保留整个会话；私有 Memory 与 Persona 读取使用已接受的身份。 | done | 2026-11 | Release 文档：Participants, Identity and Persona |
| `AGT-16` | **会话与路径的所有权** — `SessionRuntime` 移到 Core；Avatar workspace 路径归 Agents，应用和平台路径归 Host。 | done | — | Release 文档未逐条列出；v0.6.9 tag 中有、v0.6.8 中没有 |
| `AGT-17` | **标识契约** — 统一身份字符串和 ID 契约，并写入标识参考文档。 | done | — | Release 文档未逐条列出；[identifiers-zh.md](identifiers-zh.md) 首次出现在 v0.6.9 tag |

#### Prompt 与上下文

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CTX-18` | **语音提示与 Context 结构** — 补齐给 Agent 的语音提示；优化 Context 插件结构和提示渲染。 | done | — | Release 文档未逐条列出；在 v0.6.8 与 v0.6.9 两个 tag 之间，Context 插件新增了对 `<speech>`、`<unavailable_speech>` 以及语音和不确定性通知的模型说明 |

#### 运行时与 Host

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RUN-15` | **可配置的 runner worker** — runner 使用显式的启动输入；可复制的 runner（Silero VAD、Smart Turn v3）运行多个 worker 进程，每个方法有界队列、独立期限、有界且不重放的重启，以及按方法的健康指标。 | done | 2026-11 | Release 文档：Inference Runners, Parallelism and Metrics |
| `RUN-16` | **Bundle、Profile 与凭据** — 从完整模板生成带注释的 profile，`config init` 和 `config check`，交互式与无人值守的 Setup，凭据与配置分开存储。 | done | 2026-11 | Release 文档：Configuration, Credentials and Interactive Setup |
| `RUN-17` | **Linux 安装包、升级与清理** — 自带 CPython 3.13 的 Linux x86_64 安装包，安装器设置 PATH 并提供 Setup，事务式向前升级（不支持回滚或降级），以及清理不再使用的构建。 | done | 2026-11 | Release 文档：Standalone CLI, Linux Package, Upgrade and Cleanup |
| `RUN-18` | **Doctor 诊断与指标** — 静态检查，以及经授权在固定语音和图像样本上的运行诊断，包含丢句归因、阶段延迟、runner 队列数据和不含凭据的文本／JSON 报告。 | done | 2026-11 | Release 文档：Doctor and CLI Display |
| `RUN-29` | **压力与长时间验证** — 在不加载模型的替身 runner 上，进行长时间运行、取消、队列积压和多路语音的压力测试。 | done | — | Release 文档：Validation (synthetic stress and soak tests) |

#### Interaction Router

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RTR-13` | **整句输入窗口** — 一个开放的输入窗口跨越停顿、匿名片段和说话人标签；明确的 HOLD 原因、有上限并附通知的不确定等待，只在 Turn 实际提交后推进。 | done | 2026-11 | Release 文档：Turn Taking and Addressing Across an Utterance |
| `RTR-14` | **转写终态与期限** — 每个 STT 片段只有一个终态；迟到的 final 在硬期限前并入所属 Turn，过期后 Turn 带通知提交；有界的片段到 Turn 关联追踪。 | done | 2026-11 | Release 文档：Speech Transcription States, Late Results and Correlation |

#### Memory

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `MEM-18` | **按 owner 检索与批次归属** — 检索按记忆类型和 owner 读取；混合批次保留已验证的 owner；失败的 ENV 批次只重试自己的范围；被动检索有时间上限。 | done | 2026-11 | Release 文档：Memory Ownership, Recovery, Retrieval and Embedding Spaces |
| `MEM-19` | **embedding 空间记录** — 每个文本向量存储记录生成它的 embedding 模型；Host 打开存储时拒绝其他模型，在任何改动之前。Setup 只能提前检查已有的本地 LanceDB 记录；Qdrant 和实际向量维度在打开存储时检查。 | done | 2026-11 | Release 文档：Memory Ownership, Recovery, Retrieval and Embedding Spaces |

#### Persona

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `PER-20` | **CAM++ 说话人向量与会话实体** — CAM++ 中英 ONNX 说话人向量，每个会话中一个声音或一张脸是一个实体并跨来源，就近优先的多脸关联，短句延续推理和加权更新存储的向量。 | done | 2026-11 | Release 文档：Participants, Identity and Persona |

#### 质量与流程

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `QA-01` | **基于 Agent 的审查与回归** — 用编码 Agent 进行开发审查和回归，并补齐所需的确定性测试。 | done | — | 工作记录见 `docs/agent-logs/` |

#### 语音服务

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `VOI-01` | **TTS 语速** — 修复合成语音的语速。 | done | — | Release 文档未逐条列出；在 v0.6.8 与 v0.6.9 两个 tag 之间，OpenAI 和 Voice.ai TTS 实现新增了经过校验的 `speed` 设置 |

<a id="v0.6.8"></a>
### v0.6.8 · 原生 Host、运行时能力与实时语音

- **发布：**released · 2026-10-22 · [v0.6.8](releases/v0.6.8.md)
- **版本计划原文及对应事项：**
  - Persona 插件按子能力拆分重构注册，各自维护生命周期（类似 Router 插件中的 processor）；Persona 在 avatar-agents 中的业务逻辑移到插件中，avatar-agents 只保留抽象 → PER-18
  - Memory 插件按子能力拆分重构注册，各自维护生命周期（类似 Router 插件中的 processor）；重构 memory note、memory object_ids 及 Memory 存储 → MEM-16, MEM-17
  - 统一 workspace 实现 → RUN-24
  - capability 从「prompt metadata」升级为真正的运行时能力系统 → RUN-12
  - 实现 turn_runtime stream 来触发 Turn 级消费者 → CORE-12
  - Persona 插件的 config／provider 采用与 Memory 一样的按 processor 放置方式 → PER-18
  - 重构 Router 目录结构，将 `addressing` 和 `turn_taking` 移到 processor 对应目录下，Router 插件的 config 采用与 Memory 一样的按 processor 放置方式 → RTR-11
  - 优化插件注册（区分 avatar_module_plugin 和 avatar_runtime_plugin）和模型下载（去掉 download 函数，在 runner 初始化时按需下载，不需要提前下载） → RUN-25, PER-19
  - 规范相关插件模型的下载代码和目录 → RUN-25
  - avatar-plugins 拆成三层子目录（基础层、感知层、工具层），基础层进入 runtime，为其他插件（例如 Router）提供基础组件初始化，同时更新 README 和 Release 文档 → RUN-26, RUN-13
  - LiveKit RTC 搬迁到 avatar-rtc，独立出 Context 管理插件 → RTC-05, RUN-13
  - 移除 livekit.agents（统一工具和能力的注册；Provider 作为插件移到 avatar-plugins，avatar-agents 中的 provider 移到 avatar/ 目录下，并提供统一的模型输入输出结构，支持结构化输出和流式输出） → RUN-11, RUN-12, CTX-10
  - 优化日志系统 → RUN-27
  - 优化 pyproject.toml 的结构和规范，升级到 Python 3.13，完善 Ruff 检查 → RUN-14

#### Core 运行时契约

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CORE-12` | **已提交 Turn 事件流** — 新增权威的已提交 Turn 发布，消费者各有游标，与临时感知观测和模型 Run 的身份相区分。 | done | 2026-10 | Release 文档：Runtime Capabilities and Committed Turns |
| `CORE-13` | **规范输出与投递边界** — 区分执行信号、规范的模型／工具记录和面向用户的输出投递，打断精确，投递状态有界。 | done | 2026-10 | Release 文档：Runtime Capabilities and Committed Turns |

#### RTC

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RTC-05` | **独立的 RTC 包** — LiveKit 媒体适配器移到 `avatar-rtc`，应用所有权归 Host，Core 媒体契约与传输无关。 | done | 2026-10 | Release 文档：Native Host and RTC Ownership |
| `RTC-06` | **原生媒体与转录投递** — 新增原生的文本、音频、状态和转录适配器，异步生命周期、按播放节奏推进的字幕、打断隔离和精确的输出身份。 | done | 2026-10 | Release 文档：Realtime Speech, Commentary, and Transcript Delivery |

#### Prompt 与上下文

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CTX-10` | **按查询截取的上下文与原生续接** — 一次截取 Turn 的 State 和不可变的生成前缀；之后的模型／工具步骤继续时，不会悄悄改变原来的感知边界。 | done | 2026-10 | Release 文档：Native Model, Provider, Context, and Tool Execution |
| `CTX-11` | **口语优先的回答与过程说明** — 音频输出开启时选择自然的口语回答；支持可选的、用户可见的、针对任务的工具前说明，不暴露内部推理。 | done | 2026-10 | Release 文档：Realtime Speech, Commentary, and Transcript Delivery |

#### 运行时与 Host

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RUN-11` | **原生应用 Host** — `avatar-host` 负责统一的 CLI、应用服务、进程监管、托管执行、准入与收尾，以及 RTC 会话接入的生命周期。 | done | 2026-10 | Release 文档：Native Host and RTC Ownership |
| `RUN-12` | **原生 Loop 与运行时能力** — 移除 SDK 前台执行，引入可调用的能力绑定，验证原生 Provider 流式输出、工具策略和权威的模型／工具记录。 | done | 2026-10 | Release 文档：Runtime Capabilities and Committed Turns; Native Model, Provider, Context, and Tool Execution |
| `RUN-13` | **由处理器使用的 Foundation 服务** — Context、Loop、Provider 和 Voice 提供共享运行时服务，使用它们的插件保留各自的业务逻辑和生命周期。 | done | 2026-10 | Release 文档：Three-layer Plugin Workspace and Model Initialization |
| `RUN-14` | **Python 3.13 工具链** — 统一 Python 3.13 的包元数据、workspace 锁文件、Ruff／pre-commit，以及 CI 的构建、安装和适配器检查。 | done | 2026-10 | Release 文档：Python 3.13, Packaging, and Quality |
| `RUN-24` | **统一的 workspace 布局** — 环境数据、用户、图、Memory 记录、会话、索引、日志和缓存使用同一套 workspace 布局。 | done | — | Release 文档：Workspace, Logging, and Diagnostics |
| `RUN-25` | **插件注册与 runner 初始化时解析模型** — `AvatarModulePlugin` 注册与运行时插件实例分离；移除预下载步骤，启用的 runner 在初始化时解析模型；统一模型代码与缓存目录。 | done | — | Release 文档：Runtime Capabilities and Committed Turns; Three-layer Plugin Workspace and Model Initialization |
| `RUN-26` | **三层插件 workspace** — `avatar-plugins` 分为 Foundation、Perception 和 Tools 三层。 | done | — | Release 文档：Three-layer Plugin Workspace and Model Initialization |
| `RUN-27` | **结构化的 Host 日志** — 简洁的 Host 横幅，以及一致的时间、级别、源码位置、进程和消息格式。 | done | — | Release 文档：Workspace, Logging, and Diagnostics |
| `RUN-28` | **AvatarRuntime 的创建与关闭** — `AvatarRuntime.create()` 由已激活的资源组合出运行时，`aclose()` 将其关闭。 | done | — | Release 文档未逐条列出；由 `a92ff4e1`（2026-09-27）引入，早于 v0.6.8 tag；相关：EXE-01 |

#### Status

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `STS-06` | **原生执行与投递状态** — 区分模型／工具进度、本地输出投递失败、打断和就绪；通用的思考播报改为可选，不再总是说出来。 | done | 2026-10 | Release 文档：Realtime Speech, Commentary, and Transcript Delivery |

#### Interaction Router

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RTR-11` | **由处理器持有的 Router 配置** — Addressing 和 Turn Taking 移到各自处理器的目录和配置下，与独立管理的语音处理器并列。 | done | 2026-10 | Release 文档：Highlights (processor-owned Router) |
| `RTR-12` | **流式语音与字幕同步** — 新增有界的 PCM 合成与预取、改进的语音分句、按播放节奏发布的转录，以及相互独立的异步音频与字幕传输。 | done | 2026-10 | Release 文档：Realtime Speech, Commentary, and Transcript Delivery |

#### Memory

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `MEM-16` | **由处理器管理的 Memory 运行时** — 独立管理对话、工具、环境和检索能力，消费权威的已提交 Turn 和规范的模型／工具记录。 | done | 2026-10 | Release 文档：Processor-owned Persona and Memory |
| `MEM-17` | **统一的 Memory 存储与导出** — 在同一 workspace 布局下，分开全局主 Memory 记录与按 owner／episode／context 的 Markdown 投影、派生索引和图命名空间。 | done | 2026-10 | Release 文档：Workspace, Logging, and Diagnostics |

#### Persona

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `PER-18` | **由处理器管理的 Persona 运行时** — 具体的 Profiler、Speaker 和 Face 业务逻辑、配置、Provider 和生命周期移到 Persona 插件；Agents 保留抽象契约。 | done | 2026-10 | Release 文档：Processor-owned Persona and Memory |
| `PER-19` | **按需初始化模型** — 统一处理器的模型缓存与解析，只初始化启用的 runner，不再有单独的模型下载命令。 | done | 2026-10 | Release 文档：Three-layer Plugin Workspace and Model Initialization |

#### MCP

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `MCP-07` | **MCP 工具搜索过滤** — `tool_search` 支持动态 `top_k`、服务器过滤和工具类别过滤（由 MCP `readOnlyHint` 得出的 `read`／`write`／`unknown`），作为 LanceDB 预过滤执行。 | done | 2026-10 | Release 文档未逐条列出；在 v0.6.8 tag 之前合入（#11） |
| `MCP-08` | **MCP compact／raw 输出模式** — `tool_call` 支持 `output_mode="compact"`（截断结果、不回显参数）和 `"raw"`（默认），控制长工具结果。 | done | 2026-10 | Release 文档未逐条列出；在 v0.6.8 tag 之前合入（#11） |
| `MCP-09` | **MCP `refresh_tools`** — 新增 `refresh_tools` 操作，重新加载 MCP 工具并同步 LanceDB 索引，无需重启 worker。 | done | 2026-10 | Release 文档未逐条列出；在 v0.6.8 tag 之前合入（#12） |
| `MCP-10` | **MCP 日志脱敏** — 从 MCP 日志（包括 `httpx`／`mcp.client.*` 日志）中去除 token、API key、密码、授权头和 URL 中的凭据。 | done | 2026-10 | Release 文档未逐条列出；在 v0.6.8 tag 之前合入（#13） |

<a id="v0.6.7"></a>
### v0.6.7 · 原生轮次判断、语义寻址与全双工打断

- **发布：**released · 2026-09-05 · [v0.6.7](releases/v0.6.7.md)
- **版本计划原文及对应事项：**
  - 引入多模态回复判断，删除 LiveKit 的 turn detection → RTR-05, RTR-10, RUN-09
  - VAD processor 单独成文件 → RTR-21
  - `interaction` 目录改为 `router` → RUN-10

#### Core 运行时契约

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CORE-10` | **类型化感知身份与标注事件** — 标注提升为有序的感知事件，并新增来源、来源代、片段、实体和传输参与者的类型化引用，用于精确的多模态溯源。 | done | 2026-09 | Release 文档：Perception Events and Typed Lineage |
| `CORE-11` | **按决策精确截取的感知快照** — 新增在某个感知事件序号处截取历史感知的能力，已提交的 Turn 不会包含决策之后到达的观测。 | done | 2026-09 | Release 文档：Exact Turn Snapshots |

#### 运行时与 Host

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RUN-09` | **原生的用户 Turn 决定权** — 新增由标注驱动的 AvatarTurnController、明确的 Router COMMIT／INTERRUPT 决定和精确的不可变 Turn 快照，不依赖 LiveKit 文本轮次检测。 | done | 2026-09 | Release 文档：Multimodal Turn Taking |
| `RUN-10` | **Router 契约分离** — 可复用的交互路由契约移到 `alphaavatar.agents.router`，公共 Router schema 和模型接口与具体插件实现分开。 | done | 2026-09 | Release 文档：Router Architecture (`alphaavatar.agents.router`) |

#### Interaction Router

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RTR-05` | **多模态轮次判断运行时** — 新增带修订号、按说话人的轮次候选、不可变的证据快照、Smart Turn 说完判断、确定性的轮次策略，以及明确的 HOLD、COMMIT、PASSIVE、INTERRUPT 和 CANCEL 决定。 | done | 2026-09 | Release 文档：Multimodal Turn Taking |
| `RTR-06` | **语义寻址** — 用基于转写的语义寻址取代声学唤醒，使用 Avatar 身份、最近的对话上下文和与模型无关的本地推理契约。 | done | 2026-09 | Release 文档：Semantic Addressing |
| `RTR-07` | **对话焦点** — 新增按说话人的对话焦点：明确的 AVATAR／NON_AVATAR 证据更新焦点，UNKNOWN 保持原状态。 | done | 2026-09 | Release 文档：Conversation Focus |
| `RTR-08` | **寻址融合** — 新增类型化的语义、对话焦点、视觉及未来显式寻址证据，冲突时保守处理并保留证据来源。 | done | 2026-09 | Release 文档：Addressing Fusion (What's New) |
| `RTR-09` | **全双工的 Turn 打断** — 把开口打断与说完判断分开，Avatar 输出可以立即停止，同时寻址和最终轮次决定继续异步进行。 | done | 2026-09 | Release 文档：Full-Duplex Interruption |
| `RTR-10` | **移除 LiveKit 轮次检测** — 从 AlphaAvatar 的用户轮次决定中移除 LiveKit 文本轮次检测和旧的声学唤醒路径。 | done | 2026-09 | Release 文档：Removed |
| `RTR-21` | **音频活动处理器模块** — VAD 处理移到 Router 自己的处理器模块。 | done | — | Release 文档：Router Architecture (`AudioActivityProcessor`) |

#### Persona

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `PER-17` | **说话人模型打包与验证** — 说话人向量和说话人属性的 ONNX 模型迁到专用、带版本的 Hugging Face 仓库，修正说话人属性的预处理和性别标签顺序，按用途分开模型缓存。 | done | 2026-09 | Release 文档：Persona Model Packaging |

<a id="v0.6.6"></a>
### v0.6.6 · 统一时间、多模态对齐与能力感知

- **发布：**released · 2026-08-17 · [v0.6.6](releases/v0.6.6.md)
- **版本计划原文及对应事项：**
  - 修复相关缺陷 → GEN-01
  - 时间对齐，优化 prompt → CORE-06, CTX-06, CTX-07
  - ENV Memory 引入音频及自适应更新 → MEM-12, MEM-13
  - 修复 Memory 的 Qdrant 与 LanceDB 版本不一致 → MEM-14
  - 引入内部插件支持的功能描述（类似工具插件），作为 Avatar 的 prompt 输入，让它知道目前具备的能力 → CTX-08, RUN-08, PER-15
  - avatar-core 的流缓冲太短，容易遗忘 → CORE-07
  - Session 按创建日期归入文件夹（会话中的 Memory 存储按日期文件夹存放） → AGT-10
  - avatar-core 中 Stream／Observation 的枚举化、schema 化 → CORE-08

#### Core 运行时契约

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CORE-06` | **统一时间运行时** — 新增 `RuntimeClock`、`RuntimeTime`、`RuntimeTimeRange`、有序感知事件、来源状态跟踪、不可变的感知截止点和共享的多模态时间对齐。 | done | 2026-08 | Release 文档：time-aligned multimodal runtime |
| `CORE-07` | **按时间保留感知数据** — 用按生产节奏、保留时长和安全余量计算的可配置保留量，取代各模态固定的流长度。 | done | 2026-08 | Release 文档：reworked perception stream retention |
| `CORE-08` | **类型化感知契约 v2** — 流、观测、事件和媒体来源的种类在整个感知运行时中使用明确的枚举和 schema。 | done | 2026-08 | Release 文档：schema-ized and enum-ized perception contracts |
| `CORE-09` | **与传输无关的输出运行时** — 新增 AlphaAvatar 自有的输出流、输出时间线、投递状态、打断语义和感知播放进度的输出跟踪。 | done | 2026-08 | Release 文档：transport-independent `OutputRuntime` |

#### Agent 基础

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `AGT-08` | 明确区分参与者的传输身份、会话内参与者 ID、临时用户身份和 Persona 解析出的用户身份。 | done | 2026-08 | Release 文档：participant transport identity separated from logical user identity |
| `AGT-09` | 区分应用时间、参与者时间和运行时时间，使持久化、用户时区上下文和实时时间对齐各自使用独立的时间语义。 | done | 2026-08 | Release 文档：runtime, application and participant time separated |
| `AGT-10` | 按创建日期存储会话，路径为 `sessions/YYYY-MM-DD/<session_id>/`，长时间运行的会话的创建日期保持不变。 | done | 2026-08 | Release 文档：sessions grouped by creation date |

#### Prompt 与上下文

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CTX-06` | **与 Provider 无关的模型输入** — 新增 AlphaAvatar 自有的文本、图像、音频、时间、函数调用和函数输出等模型输入结构，按输入类型渲染，在 Provider 边界转换。 | done | 2026-08 | Release 文档：provider-neutral model input and prompt pipeline |
| `CTX-07` | **结构化的时序输入上下文** — 当前多模态输入渲染为时间对齐的结构化时间线，包含语音、视觉证据、来源状态变化、停顿、感知缺口和直接输入。 | done | 2026-08 | Release 文档：structured `alphaavatar_input` timeline |
| `CTX-08` | **运行时能力感知** — 为 Memory 和 Persona 新增类型化的内部能力元数据，并把当前启用的能力注入稳定的 Avatar system prompt。 | done | 2026-08 | Release 文档：internal runtime capability descriptions |
| `CTX-09` | **参与者级时间上下文** — 运行时上下文可以为多个参与者分别表示当前时间和时区，持久化时间戳与面向用户的时间不耦合。 | done | 2026-08 | Release 文档：participant-scoped current-time snapshots |

#### 运行时与 Host

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RUN-06` | **不可变的 Turn 快照** — 新增 Turn 级不可变感知快照，重试和工具后续步骤复用原来的输入边界，不观察之后的实时状态。 | done | 2026-08 | Release 文档：immutable turn snapshots |
| `RUN-07` | **分阶段并发的生命周期** — 运行时插件按依赖安全的阶段启动和停止，互不依赖的工作并发执行，启动失败时回滚，生产者先于消费者停止。 | done | 2026-08 | Release 文档：staged concurrent runtime lifecycle |
| `RUN-08` | **运行时能力元数据** — 新增可复用的能力契约，内部运行时组件可以独立于具体插件实现，向模型暴露语义能力。 | done | 2026-08 | Release 文档：`AvatarCapability` metadata |

#### 视觉

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `VIS-06` | **无状态的视觉选择** — 移除有状态的采样帧视觉运行时，改为在不可变的对齐感知上做纯函数的 `VisualFrameSelector` 选择。 | done | 2026-08 | Release 文档：`VisualFrameSelector` |
| `VIS-07` | **有时间依据的视觉** — 视觉证据保留时间片和权威的起止来源状态，历史画面不会被误认为当前开着的摄像头或屏幕。 | done | 2026-08 | Release 文档：start and end source states retained |

#### Interaction Router

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RTR-04` | **输出处理运行时** — Router 扩展到语音合成和感知播放进度的转录同步，保持与传输无关的取消和输出顺序。 | done | 2026-08 | Release 文档：speech synthesis and transcript synchronization in output routing |

#### Memory

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `MEM-12` | **音视频 ENV 记忆** — ENV 记忆把采样的视觉观测与连续的原始环境音频结合，排除语音派生流和用户直接输入流。 | done | 2026-08 | Release 文档：audiovisual ENV Memory |
| `MEM-13` | **自适应的 ENV 记忆调度** — 周期性 ENV 更新在说话时推迟边界，尽量在完整的语音边界提交，并有推迟时长上限。 | done | 2026-08 | Release 文档：speech-aware ENV boundaries with a maximum defer |
| `MEM-14` | **Memory 向量库后端一致** — 统一 LanceDB 和 Qdrant 两种 Memory runner 的行为和持久化契约。 | done | 2026-08 | Release 文档未逐条列出；版本计划列在 v0.6.6；Qdrant runner 在 v0.6.5 与 v0.6.6 两个 tag 之间有改动 |
| `MEM-15` | **结构化的记忆时间戳** — 记忆条目持久化结构化的 `created_at` 时间戳，而不是面向用户的会话时间字符串，便于跨会话、跨时区排序。 | done | 2026-08 | Release 文档：structured timestamps |

#### Persona

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `PER-14` | **结构化的 Persona 时间语义** — Persona 运行时状态和画像字段保留结构化的登录／更新时间，面向用户渲染时再转换为各参与者当前的时区。 | done | 2026-08 | Release 文档：structured login and update datetimes |
| `PER-15` | **Persona 能力元数据** — 画像、说话人识别和人脸识别能力在抽象组件层声明，自动出现在 Avatar 的 system prompt 中。 | done | 2026-08 | Release 文档：Persona capabilities |
| `PER-16` | **感知参与者的身份基础** — Persona 身份解析更新解析出的用户身份，同时保持参与者身份稳定和共享的运行时引用。 | done | 2026-08 | Release 文档：participant identity separated from user identity |

#### 通用

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `GEN-01` | **v0.6.6 缺陷修复** — 随 v0.6.6 交付的修复，未逐条列出。 | done | — | 来自版本计划；Release 文档未逐条列出 |

## 更早的历史

<a id="earlier"></a>
### v0.6.5 及之前

- **发布：**released · 2025-11-13 – 2026-07-25
- v0.6.6 之前交付的事项，按领域和月份列出。所属发布版本未核实；参见 [Release 文档](releases/) 和 README 的发布历史。

#### Core 运行时契约

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CORE-01` | **环境观测模型** — 新增与传输无关的 `EnvObservation` 和 `EnvAnnotation` 模型，覆盖视频、音频、屏幕、事件及未来的多模态输入。 | done | 2026-07 | — |
| `CORE-02` | **多表示媒体载荷** — 新增 `MediaPayload`、`PayloadFormat`、`PayloadView` 及 AlphaAvatar 自有的视频帧表示，不含 RTC 专有类型。 | done | 2026-07 | — |
| `CORE-03` | **类型化感知运行时** — 新增相互独立的视频、音频、屏幕、事件和标注流，每个消费者有自己的游标。 | done | 2026-07 | — |
| `CORE-04` | **共享时间线与窗口构建** — 新增观测与标注的对齐，以及供 Persona、Memory、Vision 和未来路由器使用的有序消费窗口。 | done | 2026-07 | — |
| `CORE-05` | **共享音频与语音感知** — 新增归一化的音频观测和派生的语音流，Router、转写、说话人识别及未来的音频处理器可各自独立消费同一来源。 | done | 2026-07 | — |

#### RTC

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RTC-01` | **RTC 适配边界** — RTC 专有的媒体转换与 `avatar-core` 隔离；Core 观测不再直接保存 LiveKit 帧类型。 | done | 2026-07 | — |
| `RTC-02` | **LiveKit 视频输入运行时** — LiveKit 视频帧归一化为 AlphaAvatar 媒体载荷，只发布一次到 `PerceptionRuntime`。 | done | 2026-07 | — |
| `RTC-03` | **按模型边界转换帧** — 通用的 AlphaAvatar 帧只在 LiveKit 模型适配边界才转换回 LiveKit 帧。 | done | 2026-07 | — |
| `RTC-04` | **LiveKit 音频输入运行时** — LiveKit 麦克风帧归一化为 AlphaAvatar 音频载荷，只发布一次到 `PerceptionRuntime.audio`。 | done | 2026-07 | — |

#### Agent 基础

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `AGT-01` | 开发上下文管理器，把实时更新的交互信息路由给 Memory、Persona 等插件模型。 | done | 2025-10 | — |
| `AGT-02` | 通过 `UserPath` 支持可变的用户级工作目录，插件可随身份变化而切换。 | done | 2026-05 | — |
| `AGT-03` | 新增从临时用户到真实用户的身份解析流程，包括延迟的临时目录迁移和会话退出时的清理。 | done | 2026-05 | — |
| `AGT-04` | 按房间类型、会话模式、可用模态、用户元数据和时间信息构建会话上下文。 | done | 2026-05 | — |
| `AGT-05` | 为需要直接访问房间的运行时组件（如状态输出、数据通道发布者）增加 LiveKit 房间绑定。 | done | 2026-05 | — |
| `AGT-06` | 引入统一的 Provider 层，用于基于任务的 LLM 和 embedding 调用，包括结构化输出、用量归一化、Provider 追踪，以及基于 Provider 的 Memory／Persona 提取。 | done | 2026-06 | — |
| `AGT-07` | 以 `SessionRuntime`、`StateRuntime`、感知参与者的会话、嵌套 YAML 配置和初步的插件生命周期边界，重构运行时与配置基础。 | done | 2026-06 | — |

#### Prompt 与上下文

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CTX-01` | **System Prompt 与 Runtime Prompt 分离** — Avatar 介绍、交互方式、persona 和全局行为规则等静态内容放在 system prompt，提高前缀缓存复用。 | done | 2026-05 | — |
| `CTX-02` | **运行时上下文注入** — 记忆、当前时间、计划、反思和 Turn 级行为规则等每轮变化的信息注入在用户查询之后。 | done | 2026-05 | — |
| `CTX-03` | **合成工具形式的运行时上下文** — 新增一种模型兼容的方式，用合成的工具调用／工具输出帧注入运行时上下文。 | done | 2026-05 | — |
| `CTX-04` | **感知交互方式** — 运行时 prompt 知道当前房间是否支持文本、语音、音频输出、视频输入和视频输出。 | done | 2026-05 | — |
| `CTX-05` | **浏览器时区** — Web demo 通过 LiveKit 参与者元数据传入浏览器时区、语言区域和 UTC 偏移，AlphaAvatar 据此构建自然的登录时间上下文。 | done | 2026-05 | — |

#### 运行时与 Host

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RUN-01` | **AvatarRuntime 组合** — 新增 `AvatarRuntime`，作为 `SessionRuntime`、`StateRuntime`、`PerceptionRuntime` 和 `InferenceExecutor` 的会话级组合根。 | done | 2026-07 | — |
| `RUN-02` | **简化的插件生命周期** — 运行时依赖在构造插件时注入，`on_start()` 和 `on_stop()` 只管理生命周期工作。 | done | 2026-07 | — |
| `RUN-03` | **生产者／消费者编排** — 感知消费者先于 RTC 生产者启动，生产者先于消费者停止，保持全双工生命周期边界清晰。 | done | 2026-07 | — |
| `RUN-04` | **AlphaAvatar 推理运行时** — 新增由 Worker 持有的 `InferenceRuntime`、会话级 `InferenceExecutor`、Unix 域套接字 IPC 和常驻 runner 进程，不依赖 LiveKit Agent 的推理内部实现。 | done | 2026-07 | — |
| `RUN-05` | **隔离的推理 runner** — VAD、说话人向量、说话人属性、人脸分析，以及 Persona、Memory、MCP 的全部向量库工作负载都在独立的常驻进程中运行。 | done | 2026-07 | — |

#### 视觉

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `VIS-01` | **视觉输入模块** — 新增独立的 `avatar/vision` 模块，用于实时视觉上下文、按会话启用和视觉插件集成。 | done | 2026-05 | — |
| `VIS-02` | **采样视频帧** — 从实时视频流中采样帧作为视觉输入，而不是把每一帧都发给模型。 | done | 2026-05 | — |
| `VIS-03` | **运行时视觉上下文注入** — 把当前采样帧注入临时的模型上下文，去掉过时的历史画面，必要时加占位。 | done | 2026-05 | — |
| `VIS-04` | **共享感知消费** — 采样帧视觉从 `PerceptionRuntime` 消费异步观测窗口，不再直接订阅 RTC 轨道。 | done | 2026-07 | — |
| `VIS-05` | **延迟解析的标注帧** — 视觉快照保留共享观测，在注入模型时才解析带标注的帧视图。 | done | 2026-07 | — |

#### Status

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `STS-01` | **Status 插件架构** — 新增可替换的 status 插件，包含策略、渲染器和输出实现，核心协议保留在 `alphaavatar.agents.status`。 | done | 2026-05 | — |
| `STS-02` | **中间状态生命周期** — 新增 `READY`、`THINKING`、`TOOL_START`、`TOOL_PROGRESS`、`TOOL_END`、`TOOL_ERROR` 和 `FINALIZING` 等状态事件，用于实时交互反馈。 | done | 2026-05 | — |
| `STS-03` | **LLM 与工具状态反馈** — 引入延迟出现的思考和工具反馈；v0.6.8 保留状态事件，但默认关闭通用的等待播报，改为可选的模型生成说明。 | done | 2026-05 | — |
| `STS-04` | **基于模板的状态渲染** — 状态回复模板从 Python 代码移到按语言区分的模板文件，按 `type + source + stage` 选择，每种有多个随机模板。 | done | 2026-05 | — |
| `STS-05` | **多输出的状态投递** — 支持日志输出、LiveKit action 事件输出，以及按房间类型投递文本／语音；状态语音可打断，不进入对话上下文。 | done | 2026-05 | — |

#### Interaction Router

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RTR-01` | **交互路由运行时** — 在原始感知流与派生交互流之间新增基于插件的处理运行时。 | done | 2026-07 | — |
| `RTR-02` | **音频活动处理** — 新增 AlphaAvatar 原生的 Silero VAD 处理，包括前置缓冲、有界队列、语音边界和发布到 `PerceptionRuntime.speech`。 | done | 2026-07 | — |
| `RTR-03` | **语音转写处理** — 新增 `openai_segment` 和 `openai_realtime` 两种 STT 路径、归一化的转写事件，以及临时的 LiveKit 轮次管线桥接。 | done | 2026-07 | — |

#### Character

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CHR-01` | 将 AIRI Live2D 集成到 AlphaAvatar。 | done | 2025-12 | — |

#### Memory

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `MEM-01` | **自动记忆提取 v1** — 基于 Memory Client，支持助手与用户、助手与工具的记忆以及助手自身记忆的记录和检索。 | done | 2025-09 | — |
| `MEM-02` | **助手与工具记忆提取 v1** — 在用户会话中为 DeepResearch 和 RAG 插件新增助手与工具的记忆。 | done | 2026-01 | — |
| `MEM-03` | **助手与工具记忆提取 v2** — 为自身记忆、助手与用户的共享记忆、助手与工具的共享记忆分别设计 prompt。 | done | 2026-04 | — |
| `MEM-04` | **本地记忆存储与检索** — 支持通过 LanceDB 在本地存储和检索记忆。 | done | 2026-04 | — |
| `MEM-05` | **运行时记忆注入** — 记忆作为每轮变化的上下文，而不是静态的 system prompt 内容，提高前缀缓存命中率。 | done | 2026-05 | — |
| `MEM-06` | **图感知的记忆基础** — 新增基于图的记忆关联，覆盖会话、用户、实体、工具和未来的多模态观测；包括多对象 MemoryItem、会话内图节点、可用别名的查找和 LanceDB 图节点检索。 | done | 2026-06 | — |
| `MEM-07` | **在线 ENV 记忆提取** — 通过可配置的多模态 Provider 任务，从有序的实时视觉观测窗口周期性提取 ENV 记忆。 | done | 2026-07 | — |
| `MEM-08` | **带标注的视觉证据** — ENV 提取优先使用带标注的 JPEG 视图，没有时回退到原始视觉证据，不持久化运行时帧载荷。 | done | 2026-07 | — |
| `MEM-09` | **ENV 记忆整合** — 新增 `MemoryType.ENV` 更新，并在会话生命周期中与对话和工具记忆做最终融合。 | done | 2026-07 | — |
| `MEM-10` | **异步 ENV 调度器** — 把快速的感知截取和游标提交与串行的多模态提取分开，支持合并待处理批次、有界重试和会话停止时排空。 | done | 2026-07 | — |
| `MEM-11` | **Memory 向量库运行时迁移** — Memory 的 LanceDB 和 Qdrant 工作负载从 LiveKit 共享推理执行器迁到 AlphaAvatar 专用的 runner 进程。 | done | 2026-07 | — |

#### Persona

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `PER-01` | **自动用户画像提取 v1** — 基于对话历史生成个性化、结合上下文的回复。 | done | 2025-10 | — |
| `PER-02` | **说话人验证** — 通过说话人向量提取和识别，新增基于语音的画像。 | done | 2025-11 | — |
| `PER-03` | **运行时状态跟踪** — 新增确定性的用户运行时状态，包括当前时区、登录时间、会话 ID、房间类型、上次时区、上次登录时间和登录次数。 | done | 2026-05 | — |
| `PER-04` | **运行时状态以 Markdown 存储** — 运行时状态以 Markdown 本地存储，不与 LLM 提取的画像向量混在一起。 | done | 2026-05 | — |
| `PER-05` | **临时 Persona 替换** — 仅运行时的临时 persona 可被解析出的真实用户画像替换，同时保留当前会话的运行时状态。 | done | 2026-05 | — |
| `PER-06` | **按身份绑定 UserPath** — Persona 本地存储通过可变的 `UserPath` 跟随身份变化。 | done | 2026-05 | — |
| `PER-07` | **实时人脸检测** — 通过 Persona 视觉身份管线，从摄像头输入实时检测人脸。 | done | 2026-06 | — |
| `PER-08` | **基于人脸的身份** — 人脸向量接入 Persona 身份解析、本地缓存匹配和基于向量库的持久化。 | done | 2026-06 | — |
| `PER-09` | **基于感知的 FaceStream** — FaceStream 消费共享的视觉观测，不再直接订阅 LiveKit 轨道。 | done | 2026-07 | — |
| `PER-10` | **人脸标注渲染** — 人脸检测结果发布为 `EnvAnnotation` 记录，并渲染为另一种带标注的载荷视图。 | done | 2026-07 | — |
| `PER-11` | **基于感知的 SpeakerStream** — 说话人识别消费 `PerceptionRuntime.speech` 中路由后的语音观测，不再依赖 LiveKit 的 VAD 切分。 | done | 2026-07 | — |
| `PER-12` | **滚动的说话人推理** — 新增滚动语音窗口、可配置的推理频率、降低说话人属性推理频率，以及只保留最新窗口的队列行为。 | done | 2026-07 | — |
| `PER-13` | **隔离的 Persona 推理** — 说话人向量、说话人属性、人脸分析和 Persona 向量库操作都通过独立的 AlphaAvatar 推理进程运行。 | done | 2026-07 | — |

#### DeepResearch

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `DRS-01` | **Tavily API 集成 v1** — 支持快速在线检索、深度搜索、抓取和网页转 PDF。 | done | 2025-12 | — |
| `DRS-02` | **感知状态的 DeepResearch 工具** — 发出带可选模型说明的 `TOOL_START` 状态，并通过 ToolBase 支持 `TOOL_ERROR` 回退。 | done | 2026-05 | — |

#### RAG

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RAG-01` | **RAG Anything 集成** — 支持基于 DeepResearch 插件的文档和网页进行查询和索引。 | done | 2026-01 | — |
| `RAG-02` | **感知 UserPath 的 RAG 工作区** — RAG 本地工作区通过可变的 `UserPath` 跟随用户身份变化。 | done | 2026-05 | — |
| `RAG-03` | **RAG 初始化等待** — 新增 `_ensure_loaded()`，查询和索引等待 RAGAnything 初始化完成。 | done | 2026-05 | — |
| `RAG-04` | **临时与当前 RAG 查询** — 身份解析后保留之前的临时 RAG 实例作为回退，新的索引写入解析出的用户工作区。 | done | 2026-05 | — |
| `RAG-05` | **便于 LLM 使用的 RAG 输出** — RAG 查询返回结构化的 Markdown 段落，而不是原始 JSON。 | done | 2026-05 | — |
| `RAG-06` | **感知状态的 RAG 工具** — 发出带可选模型说明的 `TOOL_START` 状态，并通过 ToolBase 支持 `TOOL_ERROR` 回退。 | done | 2026-05 | — |

#### MCP

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `MCP-01` | **MCP Host 集成** — 以 MCP 插件形式集成 MCP Host，支持 MCP 注册、工具搜索和并行调用。 | done | 2026-02 | — |
| `MCP-02` | **runner 级的 MCP 初始化** — 把开销大的 MCP 和检索初始化移出每个会话；v0.6.8 起，所选的 MCP 向量库服务由 AlphaAvatar 自有的推理进程运行，而不是 LiveKit Agents worker。 | done | 2026-05 | — |
| `MCP-03` | **基于 LanceDB 的 MCP 工具检索** — 在 LanceDB 中存储 MCP 工具元数据，支持按 Agent 查询做 top-k 语义工具搜索。 | done | 2026-05 | — |
| `MCP-04` | **MCP 工具运行时的健壮性** — 增加稳定的工具 ID、便于 Agent 使用的工具提示、参数校验、混合重排和服务器重连。 | done | 2026-05 | — |
| `MCP-05` | **感知状态的 MCP 工具** — 发出带可选模型说明的 `TOOL_START` 状态，并通过 ToolBase 支持 `TOOL_ERROR` 回退。 | done | 2026-05 | — |
| `MCP-06` | **MCP 向量库运行时迁移** — MCP 的 LanceDB 和 Qdrant 检索工作负载迁到专用的 AlphaAvatar 推理 runner 进程。 | done | 2026-07 | — |

#### Web 客户端

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `WEB-01` | **LiveKit Web Demo v1** — 构建实时浏览器 demo，包含语音、文字聊天、摄像头预览、Agent 音视频舞台和会话控制。 | done | 2026-04 | — |
| `WEB-02` | **浏览器时区元数据** — 通过参与者元数据把浏览器时区、语言区域和 UTC 偏移发给 AlphaAvatar。 | done | 2026-05 | — |
| `WEB-03` | **房间／会话模态感知** — Web 会话元数据帮助 AlphaAvatar 推断可用的文本、语音和视频交互方式。 | done | 2026-05 | — |

## 长期

<a id="backlog"></a>
### 未排期

- **发布：**unscheduled
- 尚未分配到版本的方向和工作。客户端方向为 AlphaAvatar Web、App 和 OS；第三方消息桥不在当前实现范围内，外部工具和个人工作区集成仍是项目的一部分。

#### Core 运行时契约

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CORE-14` | 为长时间运行和多来源会话增加按来源的保留、载荷裁剪、背压和消费者滞后观测。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `CORE-15` | 将时间对齐扩展到更丰富的多来源、多说话人、标注融合和长时间事件场景。 | planned | — | — |
| `CORE-16` | 为人脸、说话人、物体、动作、场景和屏幕理解增加标注融合。 | planned | — | — |
| `CORE-17` | 增加可复用的 Core 策略，用于观测选择、时间窗口和载荷生命周期管理。 | planned | — | — |

#### RTC

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RTC-07` | 在当前 LiveKit 适配器之外，扩展 RTC 屏幕共享和数据通道覆盖、前端兼容性检查，以及端到端传输恢复测试。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `RTC-08` | 增加其他 RTC 后端，例如原生 WebRTC、`aiortc` 和自定义 RTC 提供方。 | planned | — | WebRTC 已排入 RTC-10（v0.7.3）；其他后端留在这里 |
| `RTC-09` | 增加 RTC 层的重连、传输恢复、流控和健康监测。 | planned | — | — |

#### Agent 基础

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `AGT-12` | 完善多用户流式身份管理：参与者级的说话人跟踪、人脸跟踪、并发的 Persona 解析、冲突处理和按用户路由。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实；相关：v0.7.2 的身份事项 PER-31、PER-32、PER-34、PER-35 |
| `AGT-13` | 增强 Provider 运行时能力：回退链、重试策略、成本估算、Provider 健康检查和模型兼容性校验。 | planned | — | — |
| `AGT-14` | 解决多说话人场景的鸡尾酒会问题，包括说话人分离、说话人跟踪、重叠语音处理和按用户路由上下文。 | planned | — | 相关：PER-32（同段多人、v0.7.2） |
| `AGT-15` | 增加用户上传文件的生命周期管理，包括会话临时存储、按身份持久化、产物索引和清理策略。 | planned | — | 相关：FIL-01（v0.7.1） |

#### Prompt 与上下文

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CTX-12` | 按模态、模型能力、上下文大小、延迟目标和当前参与者，自适应分配 prompt 预算并选择上下文。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `CTX-13` | 在不同 Provider、语言、客户端模式和长时间工具流程中，评估并扩展口语优先风格和工具前说明。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `CTX-14` | 基于浏览器时区、语言区域和可选的 IP 地理提示支持国家／位置提示，并只作为弱信号。 | planned | — | — |
| `CTX-15` | 增加运行时上下文压缩，避免记忆、RAG、反思和计划变大后动态 prompt 过长。 | planned | — | — |
| `CTX-16` | 为 system prompt、运行时 prompt、记忆提取 prompt 和 persona 提取 prompt 增加版本管理与评估。 | planned | — | — |
| `CTX-17` | 为 OpenAI、Gemini、Claude、本地模型和小型端侧模型增加各自的 prompt 适配。 | planned | — | — |

#### 运行时与 Host

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RUN-19` | 完善运行时生命周期契约：一致的 `aclose`、健康检查、明确的资源所有权、worker 恢复和运行时健康观测。 | planned | — | 相关：EXE-01、EXE-09（v0.8.0） |
| `RUN-20` | 基于 Turn、Provider 追踪、记忆事件和运行时状态事件，增加会话回放与审计工具。 | planned | — | — |
| `RUN-21` | 在模型调用、工具调用、插件初始化、原生客户端适配器和实时媒体流中，增加更完善的错误处理与恢复策略。 | planned | — | — |
| `RUN-22` | 为每个插件包、Provider 集成、配置 schema 和运行时协议增加版本控制与兼容性检查。 | planned | — | 相关：CFG-02（v0.7.0） |
| `RUN-23` | 优化语音链路、Provider 调用、工具调用、记忆检索、RAG、MCP、状态反馈和原生客户端适配器的延迟，从流式转写、首个短句即合成、预建 Provider 连接和提前计算召回 embedding 开始；Doctor 可度量当前各语音阶段（v0.6.9）。 | planned | — | 相关：VOI-02（v0.7.1） |

#### 视觉

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `VIS-08` | 按交互状态、用户语音、运动、摄像头活动和模型需求改进视觉帧采样策略。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `VIS-09` | 增加面向用户的视觉依据表达，例如明确说出助手能否看到当前摄像头画面。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `VIS-10` | 支持屏幕共享作为视觉输入，用于调试、阅读文档和工作流协助。 | planned | — | — |
| `VIS-11` | 增加多用户视觉场景理解，包括人脸跟踪、当前说话人对齐和按用户路由上下文。 | planned | — | 相关：PER-34（v0.7.2） |
| `VIS-12` | 扩展视觉历史检索：按物体、事件、身份、时间范围、截图和白板搜索。 | planned | — | — |
| `VIS-13` | 增加视觉隐私控制，用户可按会话开启、关闭、查看或丢弃视觉上下文。 | planned | — | — |
| `VIS-14` | 增加多模态评估：视觉依据的准确性、延迟和抗幻觉能力。 | planned | — | — |

#### Status

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `STS-07` | 增加结构化的状态追踪日志，记录事件是已发出、被策略拦截、已渲染、已投递、被输出端跳过还是被打断。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `STS-08` | 让 `TOOL_END` 可用于 UI 的操作时间线，同时默认对文本／语音保持静默。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `STS-09` | 增加带权重的状态模板，常用说法出现更多，同时保留变化。 | planned | — | — |
| `STS-10` | 为安全的元数据增加模板变量，例如 `url_count`、`tool_count`、`document_count` 和 `data_source`。 | planned | — | — |
| `STS-11` | 增加按用户的状态详细程度偏好，例如安静、正常和详细模式。 | planned | — | — |
| `STS-12` | 为前端 UI 增加状态时间线，包括思考、搜索、阅读、工具执行和整理结果。 | planned | — | — |
| `STS-13` | 为长时间运行的 DeepResearch、RAG 索引和 MCP 并行工具执行增加工具进度事件。 | planned | — | — |
| `STS-14` | 增加 Turn 级状态指标，例如首个状态延迟、首个回答延迟、工具数、状态数和打断次数。 | planned | — | — |

#### Interaction Router

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RTR-15` | 借助更强的本地模型和针对性训练，提升语义寻址的准确率、延迟、量化效率和多说话人鲁棒性。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `RTR-16` | 在现有视觉证据接口上增加具体的视觉寻址信号，例如视线、脸部朝向、手势和视觉注意。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `RTR-17` | 增加仅凭视觉的主动轮次生产者，用于求助、异常事件和环境驱动的交互。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `RTR-18` | 把多模态路由扩展到更丰富的多用户、共用麦克风、重叠语音和群聊场景。 | planned | — | 相关：RTR-22（v0.7.2） |
| `RTR-19` | 按更高层的意图和 Behavior 策略，把已提交的交互分流到回答、澄清、工具流程、仅状态或其他行为路径。 | planned | — | — |
| `RTR-20` | 按用户意图、任务类型、交互模式和预期延迟选择早期状态反馈。 | planned | — | — |

#### Character

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `CHR-02` | 改进语音输出、Live2D 动作、面部表情与对话状态之间的同步。 | planned | — | — |
| `CHR-03` | 把状态事件连接到角色动画状态，例如思考、搜索、聆听、说话和错误恢复。 | planned | — | — |
| `CHR-04` | 按情绪、话题和与用户的关系，增加感知 persona 的角色表情控制。 | planned | — | — |

#### Memory

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `MEM-20` | 改进 ENV 记忆检索，支持按物体、事件、身份、地点和时间的视觉历史查询。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `MEM-21` | 改进 ENV 图节点提取，只有具体观测到的实体才成为图锚点。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `MEM-22` | 扩展由处理器管理的 Memory，提供可独立使用的图／时间检索能力和更丰富的媒体／来源引用。 | planned | — | 相关：MEM-35（v0.7.2）；也承接旧 v0.7.2 计划中的媒体历史部分 |
| `MEM-23` | 增加 `node_merge` 做图节点规范化，包括别名冲突处理、重复节点合并、会话内到规范节点的映射和可选的向量库重建索引。 | planned | — | — |
| `MEM-24` | 为长时间会话增加跨窗口的事件整合和重复抑制。 | planned | — | — |
| `MEM-25` | 允许用户按需主动查询、回忆、更正或删除特定记忆。 | planned | — | — |
| `MEM-26` | 多个用户在同一会话中交互时，增加多用户记忆隔离。 | planned | — | 相关：MEM-32、MEM-36（v0.7.2） |
| `MEM-27` | 把事件驱动的记忆触发从当前的周期／用户轮次 ENV 更新，扩展到反思、规划、行为调整和感知状态的交互事件。 | planned | — | — |
| `MEM-28` | 从文本、语音、图像、视频、工具、文件和外部工作区进行全模态记忆更新。 | planned | — | 相关：MEM-31（v0.7.2） |
| `MEM-29` | 把图感知检索扩展到更丰富的关系、时间事件、别名和长期用户目标。 | planned | — | — |
| `MEM-30` | 增加记忆置信度、来源归属和冲突消解。 | planned | — | 相关：MEM-32、MEM-35（v0.7.2） |

#### Persona

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `PER-21` | 支持 persona 可视化界面，用于查看和更正画像。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实；相关：PER-36（v0.7.2） |
| `PER-22` | 为并发交互增加多用户画像管理。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `PER-23` | 在对话进行中实时检索画像并切换画像。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `PER-24` | 在 AlphaAvatar Web、App 和 OS 客户端之间增加共享的用户身份和明确的身份关联。 | planned | — | — |
| `PER-25` | 增加经用户确认的身份合并和身份冲突消解。 | planned | — | 相关：PER-35（v0.7.2） |
| `PER-26` | 增加 persona 隐私控制，用户可查看、编辑、导出或删除画像字段。 | planned | — | — |
| `PER-27` | 为画像更新、反思周期和规划刷新增加事件触发。 | planned | — | — |
| `PER-28` | 增加多用户人脸跟踪、当前说话人对齐和按用户路由视觉上下文。 | planned | — | 相关：PER-34（v0.7.2） |

#### Reflection

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RFL-02` | 在会话退出后增加离线反思周期。 | planned | — | 相关：EXE-07（后台反思、v0.8.0） |
| `RFL-03` | 在长会话中增加在线的轻量反思。 | planned | — | — |
| `RFL-04` | 把反思结果提供给记忆、行为和规划插件。 | planned | — | — |

#### Planning

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `PLN-01` | 基于记忆、persona、反思、提醒和外部工具结果，构建 Planning 插件 Alpha。 | planned | — | — |
| `PLN-02` | 为进行中的用户请求增加短期任务跟踪。 | planned | — | — |
| `PLN-03` | 基于用户记忆和画像增加长期目标跟踪。 | planned | — | — |
| `PLN-04` | 把规划结果集成到 Notion、日历、Todoist 或其他任务系统。 | planned | — | — |

#### Behavior

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `BHV-01` | 构建 Behavior 插件 Alpha，负责回复风格、流程选择、工具使用策略和主动协助规则。 | planned | — | — |
| `BHV-02` | 增加全局行为规则和 Turn 级行为规则。 | planned | — | — |
| `BHV-03` | 增加用户可配置的行为偏好。 | planned | — | — |
| `BHV-04` | 在工具失败或运行时上下文不完整时提供安全的回退行为。 | planned | — | — |

#### World Sandbox

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `SBX-01` | **World Sandbox** — 与外部虚拟环境、代码沙箱、模拟世界或应用交互。 | planned | — | 原为 Plan Overview 中的一行 |

#### DeepResearch

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `DRS-03` | 在长时间研究流程中提供更丰富的 `TOOL_PROGRESS` 更新，例如搜索、提取、阅读和综合。 | planned | — | DRS-07（v0.7.1） 的候选范围 |
| `DRS-04` | 获取指定网页下所有可访问的链接，存入指定文件夹供 RAG 索引。 | planned | — | DRS-07（v0.7.1） 的候选范围 |
| `DRS-05` | 为下载的网页、PDF 和搜索结果自动生成摘要元数据，供记忆和 RAG 之后引用。 | planned | — | DRS-07（v0.7.1） 的候选范围 |
| `DRS-06` | 通过 `UserPath` 让 DeepResearch 的输出感知身份，下载的产物存到正确的用户工作区。 | planned | — | DRS-07（v0.7.1） 的候选范围 |

#### RAG

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `RAG-07` | 身份解析后增加可靠的临时到真实 RAG 迁移策略。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实；身份改绑已不再迁移已存数据（KD-10），需随 PER-35 重新确认；RAG-13 的候选范围 |
| `RAG-08` | 在索引过程中提供更丰富的 `TOOL_PROGRESS` 更新，例如解析、分块、embedding、保存和索引完成。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实；RAG-13（v0.7.1） 的候选范围 |
| `RAG-09` | 支持文件夹索引和跨数据源、按工作区范围的检索。 | planned | — | RAG-13 或 FIL-01（v0.7.1） 的候选范围 |
| `RAG-10` | 为不同数据源增加结构化元数据，包括目录、来源类型、创建时间和用户归属。 | planned | — | RAG-13 或 FIL-01（v0.7.1） 的候选范围 |
| `RAG-11` | 在当前用户 RAG、临时会话 RAG 和全局知识之间做结果重排和答案综合。 | planned | — | RAG-13（v0.7.1） 的候选范围 |
| `RAG-12` | 允许 AlphaAvatar 索引和检索预先写好的 Skills，更高效地执行命令。 | planned | — | RAG-13（v0.7.1） 的候选范围 |

#### MCP

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `MCP-11` | 集成 Notion MCP。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实；MCP-15（v0.7.1） 的候选范围 |
| `MCP-12` | 在并行 MCP 执行中提供更丰富的 `TOOL_PROGRESS` 更新，包括工具数、完成数、失败数和慢工具检测。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实；MCP-15（v0.7.1） 的候选范围 |
| `MCP-13` | 为 Gmail、日历、Todoist 和 Notion 等基于 OAuth 的工具支持全局 MCP 与用户级 MCP 路由。 | planned | — | MCP-15（v0.7.1） 的候选范围 |
| `MCP-14` | 为用户级工具和外部账户授权增加 MCP 权限模型。 | planned | — | MCP-15（v0.7.1） 的候选范围 |

#### Web 客户端

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `WEB-04` | 增加面向用户的 persona 和记忆查看面板。 | planned | — | 旧版 Roadmap 标为进行中；当前进展未核实 |
| `WEB-05` | 增加文档、文件夹、图片和 URL 的上传界面。 | planned | — | — |
| `WEB-06` | 增加屏幕共享和视觉依据支持。 | planned | — | — |
| `WEB-07` | 增加 demo 会话调试面板，显示房间元数据、参与者元数据、Agent 状态和工具状态。 | planned | — | 相关：WEB-09（v0.7.0） |
| `WEB-08` | 增加用户登录和持久的身份绑定。 | planned | — | — |

#### 文档

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `DOC-03` | **用 Agent 管理文档和绘制资产** — 用 Agent 为 AlphaAvatar-docs 管理文档、绘制资产。 | in-progress | — | 设计 Agent 正在完成文档站设计的收尾（2026-11） |

#### 质量与流程

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `QA-06` | **`alphaavatar test` 入口** — 是否提供 `alphaavatar test`，用于场景和基准测试。 | proposed | — | v0.6.9 留待另行确定；[cli/test.md](cli/test.md) 只是方案 |
| `QA-07` | **与编码 Agent 协作的方式** — 找到一种与 Agent 高效协作、同时让构建过程清晰可见的方式：严谨、可复现、可解释；详细记录日志、决策、状态和实验；任何结论都要有依据，不擅自推断；失败要有分析；用验证把关；定期反思总结。 | proposed | — | — |

#### 架构方向

| ID | 事项 | 状态 | 日期 | 说明 |
| --- | --- | --- | --- | --- |
| `ARCH-01` | **跨设备的同一套运行时** — 不是“服务器版 + 手机阉割版”，而是同一套 AlphaAvatar 运行时根据设备资源、网络和可用加速器动态协商能力：既能纯设备端运行，也能连接服务端获取更强的模型能力，还能多端互联、共享能力。 | proposed | — | 包括多设备自托管 |
| `ARCH-02` | **运行时状态对模型可见** — 对用户可见的运行时状态，原则上对模型也应可见。 | proposed | — | — |

<a id="planning-notes"></a>
## 规划说明

以下是随计划记录的方案，不是当前行为，也不是公共契约；当前契约见所链接的技术文档。

<a id="pn-memory-recall"></a>
### 多人场景的被动检索（MEM-36，v0.7.2）

**现状。**每个已提交的 Turn，被动检索会
（[Memory README](../avatar-plugins/perception/avatar-plugins-memory/README.md)、[标识参考 §9](identifiers-zh.md)）：

1. 按 Context 保存该 Turn 已提交的转录文本（`snapshot.text`）；
2. 把同一 Context 最近 `search_context` 个用户 Turn（含当前轮）拼成一条查询，最多保留末尾 `max_query_chars` 个字符。二者是 `memory.retrieval` 的设置，默认为 3 个 Turn 和 8192 个字符；
3. 读者有可读取的已存内容时，对这条查询调用一次 `embed_query()`，用于记忆及图谱候选搜索；没有则跳过 embedding（LanceDB runner 先做这一检查）；
4. 当前 Turn 明确归属于某个用户时，检索 Avatar 的记忆和该用户的记忆；无法归属或混有不同用户时，只检索 Avatar 的记忆；
5. 结果返回时再次检查身份，只保留读者可以读取的内容。

**方案。**检索考虑多人。具体设计未定，计划保留以下约束：

- 查询中的语义线索不授予访问权限。例如最近几轮包含 A、B 的发言，本轮属于 B：A 的话可以作为查询的语义线索，但不会因此获得读取 A 私人记忆的权限。
- owner 过滤在查询时就带上，返回的记录和身份还要再次复核。
- 这里的身份是运行时当前接受的 `user_id` 及身份版本，可能是新用户生成的临时身份，不一定已经完成声纹或人脸识别。

**未定。**附图还写了按 scope 过滤（owner、当前 episode／context）。当前契约按记忆类型和 owner 读取、不看 scope（[标识参考 §9](identifiers-zh.md)）；多人检索是否加入 scope 过滤待定。上面的窗口数值是当前默认值，不是方案中的固定值。

<a id="pn-execution-lifecycle"></a>
### 执行生命周期（EXE-01～EXE-09，v0.8.0）

**现状**（[标识参考](identifiers-zh.md)、[Host README](../avatar-host/README.md)）：

- `PerceptionRuntime` 是 session-scoped 的，内部感知事件带有 `session_id`。因此现在的 session 既是交互连接，也是感知和推理所在的执行域。把二者分开是 EXE-01 的核心。
- `avatar_id`、`session_id`、`episode_id`、`context_id` 和 `parent_context_id` 已经存在。`StateRuntime` 默认为每次执行生成新的 `episode_id` 和 `context_id`，Memory 的 scope 复用它们。它们并不让工作持久化或可恢复。
- `run_id` 已经存在，标识一次 Loop 的模型／工具运行；Host 的 `execution_id` 标识一个托管的执行进程。早先的讨论建议在「0.7.1」引入执行层 `run_id`；按本次安排，这是 v0.8.0 的 EXE-04，是对现有字段的扩展。
- 还没有 `dream_id`。`MemoryScopeKind.DREAM` 已定义，但没有任何地方产生它。
- Host 每次执行只支持一个接入；重新接入、持久执行恢复和休眠／唤醒都没有实现。
- 每次 dispatch 都会启动一个执行进程，先装配会话才能就绪（EXE-08）。原笔记所说的 LiveKit Agents room 创建方式已在 v0.6.8 移除。

**建议语义**（未实现）：

| 标识 | 建议语义 | 生命周期边界 |
| --- | --- | --- |
| `avatar_id` | 持续存在的 Avatar 身份，也是 Avatar-owned memory 的所有者。 | 跨 episode、session、context 保持稳定。 |
| `episode_id` | Avatar 一次活跃、清醒的运行周期。 | 不由某个用户断连直接结束。 |
| `session_id` | 一次交互接入会话，例如实时房间、终端连接。 | 接入结束，不等于 Avatar 停止工作。 |
| `context_id` | 一项持续工作的上下文，例如交互、任务、监控、规划。 | 可以跨 session，也可以跨 episode。 |
| `run_id` | 一次实际执行，用于执行状态、trace、重试和恢复追踪。 | 与逻辑任务分离；一个 context 可以有多次 run。 |
| `dream_id` | 一次后台反思、整理活动的逻辑标识。 | 可以处理多个 episode 的材料，也可以被唤醒中断。 |

**讨论过的规则：**

- 继续同一个未完成任务：保留原来的 `context_id`，新增它与下一 episode 的执行关联。从已有任务派生新任务：创建新的 `context_id`，通过 `parent_context_id` 或其他明确的来源关系关联前一个 context。这两者不能都叫「继承 context」，否则恢复、权限和历史追踪会混在一起。
- 有效交互活动已经超时，并且没有待处理的已接收输入，也没有必须继续运行、尚未到安全暂停点的工作时，episode 可以结束。
- 一个等待下次定时触发的监控 context 可以继续存在，但不必阻止当前 episode 结束。Context 存在，不等于 Context 此刻正在执行。
- Dream 不与 Episode 一一绑定，不是「一个 episode 结束 → 必须立即创建一个 dream → dream 完成才能再次醒来」。Dream 是可配置的后台整理活动，可以聚合多个 episode 的材料；出现新的有效输入时，前台交互优先恢复，Dream 在安全边界暂停或取消。
- Dream 产生的记忆仍通过正常的 Memory 提交路径写入，保留原始证据和来源关系，不建立与 Memory 主库平行的「Dream 记忆真相源」。

<a id="pn-rolling-stt"></a>
### 滚动提交的流式 STT（VOI-02，v0.7.1）

**现状。**默认 STT `openai_segment` 在 VAD 切出完整语音段后对整段转写；另有 `openai_realtime`。转写事件包括 `INTERIM_TRANSCRIPT`，每段一个最终结果（[Voice README](../avatar-plugins/foundation/avatar-plugins-voice/README.md)）。

**方案**（较早的笔记，为 VOI-02 保留）：用户持续说话时，按固定时间窗口提交不重叠的音频块，实时生成中间转写，并按 `segment_id` 和 `chunk_index`（新字段）维护顺序、合并结果及失败状态。整段结束后，再对整段音频执行一次最终转写，生成该段唯一的最终结果，修正分块边界造成的漏词、重复、断句和上下文偏差。还需要覆盖分块乱序返回、单块失败、超时回退、片段取消、重复提交、最终结果覆盖中间结果，以及实时转写的延迟和准确率指标。是否采用未定。

<a id="areas"></a>
## 领域

| 代码 | 领域 | 范围 |
| --- | --- | --- |
| `CORE` | Core 运行时契约 | `avatar-core` 中与传输无关的媒体、感知、时间、Turn 和输出契约。 |
| `RTC` | RTC | 消费 Core 契约的传输适配器；已实现的后端是 LiveKit。 |
| `AGT` | Agent 基础 | Agent 运行时的会话、参与者、身份和时间基础。 |
| `CTX` | Prompt 与上下文 | 查询准备、模型输入、历史和提示渲染。 |
| `RUN` | 运行时与 Host | 运行时组合、推理 runner、原生 Host、安装包和诊断。 |
| `VIS` | 视觉 | 视觉输入选择、视觉依据和视觉历史。 |
| `STS` | Status | 就绪、模型／工具活动和投递反馈。 |
| `RTR` | Interaction Router | 负责实时语音路由、语义寻址、对话焦点、多模态轮次判断、打断、语音合成、转录同步，以及与传输无关的交互决定。 |
| `CHR` | Character | 虚拟角色展示。 |
| `MEM` | Memory | 对话、工具和环境记忆，存储与检索。 |
| `PER` | Persona | 用户画像、说话人与人脸识别、身份延续。 |
| `RFL` | Reflection | 从记忆、persona、工具使用、失败和交互历史中生成元认知洞察。 |
| `PLN` | Planning | 从记忆、反思和工具结果生成短期任务、长期计划、提醒和后续行动。 |
| `BHV` | Behavior | 控制回复风格、流程选择、工具使用策略和主动协助规则。 |
| `SBX` | World Sandbox | 让 AlphaAvatar 与外部虚拟环境、代码沙箱、模拟世界或应用交互。 |
| `DRS` | DeepResearch | 网页研究工具插件。 |
| `RAG` | RAG | 文档索引与检索工具插件。 |
| `FIL` | Files | 计划中的文件能力；与 RAG 的关系未定。 |
| `MCP` | MCP | MCP 服务器工具的发现、检索和调用。 |
| `AGX` | 外部 Agent | 作为子 Agent 接入 AlphaAvatar 的其他 Agent。 |
| `WEB` | Web 客户端 | AlphaAvatar-web 和浏览器 demo。 |
| `APP` | App | `avatar-app` 客户端。 |
| `UI` | 产品 UI | Web 与 App 共用的视觉和交互设计。 |
| `CFG` | 配置与版本 | 配置体验、校验和版本管理。 |
| `DOC` | 文档 | 仓库文档、文档站和本 Roadmap。 |
| `OPS` | 部署与运维 | Demo 部署、健康检查、更新和恢复。 |
| `QA` | 质量与流程 | 基于 Agent 的审查和测试，以及开发原则。 |
| `VOI` | 语音服务 | 语音识别、合成和 embedding 服务。 |
| `EXE` | 执行生命周期 | 独立于交互连接的 Avatar 执行。 |
| `ARCH` | 架构方向 | 尚未排期的跨领域原则。 |
| `GEN` | 通用 | 不属于单一领域的工作。 |

<a id="format"></a>
## 格式

供读取本文件的工具（例如文档站）使用。

- [时间线](#timeline)表的表头为 `| 里程碑 | 版本 | 主题 | 发布 | 发布日期 | Release 文档 |`（英文版为 `| Milestone | Version | Theme | Release | Released | Release notes |`），按顺序列出里程碑。
- 里程碑章节以 `<a id="<里程碑>"></a>` 和一个 `###` 标题开始。里程碑是版本（`vX.Y.Z`）、`earlier` 和 `backlog`。第一个表格之前的列表项是详情：发布、顺序、验收路径、未定事项。
- 事项表的表头为 `| ID | 事项 | 状态 | 日期 | 说明 |`（英文版为 `| ID | Item | Status | Date | Notes |`）。每行属于它之前最近一个锚点所在的里程碑；`####` 领域标题只用于分组。
- 状态和发布状态取[阅读说明](#reading-this-roadmap)中的值，两种语言都用英文。日期为 `YYYY-MM`、`YYYY-MM-DD`、两天组成的区间或 `—`。
- 规划说明（`<a id="pn-…"></a>`）是方案，不是当前行为。
- Release 文档是独立的文档，每个版本一份；路线图链接它们，发布列表不替代路线图。
- 中英两版的里程碑、事项 ID、状态和日期相同。
- `scripts/docs/check_docs.py` 检查这些规则。
