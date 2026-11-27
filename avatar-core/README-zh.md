# AlphaAvatar Core

[English](README.md)

`avatar-core` 提供与传输无关的媒体、事件和生命周期契约。
它不依赖 Agents、具体插件、模型 SDK 或 LiveKit。

## 📦 包结构

```text
alphaavatar/core/
├── cleanup.py          # Cancellation-safe waiting for owned cleanup.
├── lifecycle.py        # Components, phases and ordered lifecycle groups.
├── time.py             # RuntimeClock and runtime time ranges.
├── ipc.py              # Private local socket paths.
├── log/                # Diagnostic records, producers and error formatting.
├── env/                # Input observations, annotations and output envelopes.
├── media/              # AlphaAvatar-owned audio, image, video and text payloads.
├── session/            # Participants, accepted identity bindings and session events.
├── perception/         # Source lineage, event streams, windows and timelines.
├── turn/               # Committed input snapshots and independent consumers.
└── output/             # Delivery, canonical records, control and playback facts.
    ├── enums/
    ├── schemas/
    ├── runtime.py
    ├── stream.py
    ├── journal.py
    └── timeline.py
```

## 运行时契约

| 运行时 | 职责 |
| --- | --- |
| `SessionRuntime` | 参与者、已接受的身份绑定和会话事件。 |
| `PerceptionRuntime` | 归一化的输入证据、来源世代、标注和时间对齐的快照。 |
| `TurnRuntime` | 依据感知截止点截取的已提交输入快照，带有相互独立的消费者游标。 |
| `OutputRuntime` | 经校验的输出准入、精确中断、完成，以及相互独立的记录／执行流。 |

适配器将外部数据归一化为 `EnvObservation`。
生产者向 OutputRuntime 提交 `EnvOutput`；由此产生的 `OutputEvent` 附加运行时的发布身份和时间信息。
输入和输出是不同的契约。
文本输出保留空白字符；媒体复用已校验的帧，而不是为每个消费者重新编码。

身份信息属于类型化的 scope／source 字段。
Context、Turn、Run、输出和分块 ID 不可互换。
元数据是有界的不可变扩展，不用于存放 SDK 客户端、张量、媒体字节或相互冲突的身份字段。

## 交付与完成

实时的 `stream` 订阅承载媒体和呈现内容。
`records` 为 Memory 等独立消费者接纳规范批次。
`execution` 为 Status 和诊断承载有界的执行观测。
记录准入不等于数据库持久化或客户端交付，也不能证明工具执行成功。

`TEXT_COMPLETE` 封闭源文本；`AUDIO_COMPLETE` 封闭合成与对齐；`COMPLETE` 结束源的生产；`PLAYBACK` 报告传输层实测的进度。
中断在准入时解析出精确的输出身份，并绕过普通队列的背压。
迟到的回调不能把中断重新解释为针对更新的 Run。

`IMMEDIATE` 文本不需要音频。
`AUDIO_SYNCED` 文本由 Router 合成，并按播放进度作为字幕释放。
`MIRROR` 仅用于观测，不是第二个用户可见的回复。
估计的时间与实测的时长相区分；最终确定时不会撤回已发出的字幕前缀，也不会改变音频速度。

## 生命周期与诊断

`LifecycleComponent` 定义异步的 `on_start()`／`on_stop()`。
`LifecycleGroup` 按顺序启动各阶段，并按相反顺序停止；同一阶段内的组件并发运行。
清理同样负责部分完成的初始化。
取消不会悄悄放弃已准入的工作，失败的清理仍然可见。

Core 日志在导入时不安装任何 handler。
各模块使用标准 `logging`；Host 负责收集、格式化和文件轮转。
可选的 Core 事件诊断是采样的，可能被丢弃，不能代替规范记录或执行结果。
已保存的日志和备份见 [Host 设置](../avatar-host/README.md)和面向用户的[工作区指南](../docs/layouts/avatar-workspace.md)。
