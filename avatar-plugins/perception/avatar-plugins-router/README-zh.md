# 🎯 AlphaAvatar Interaction Router 插件

Router 通过相互独立的处理器协调实时感知、寻址、轮次判断、合成和转录同步。它借用模型／语音抽象，不直接向 LiveKit 或前端发布。

## ⚙️ 运行时与处理器

InteractionRouterRuntime 实现 `on_start()` / `on_stop()`，并通过本地适配器把有序的处理器生命周期委托给 Core LifecycleGroup。RouterProcessorBase 保留其 `name`、`start()` 和 `stop()` 接口。

工厂按依赖关系安排消费者的顺序。处理器是独立拥有的生命周期组件，不是新的任务专属运行时。启动回滚／关闭同样覆盖部分初始化；关闭失败会在普通的同级清理完成后向上传播，而不是只记录日志。

| 处理器 | 主要输入 | 输出 |
| --- | --- | --- |
| AudioActivityProcessor | 感知音频 | 带 VAD 状态和前导音频（pre-roll）的语音帧与片段。 |
| SpeechTranscriptionProcessor | 路由后的语音 | 带片段来源信息的转录观测。 |
| SemanticAddressingProcessor | 转录文本和对话焦点 | 类型化的语义寻址证据。 |
| VisualAddressingProcessor | 人脸标注 | 人脸朝向寻址证据。 |
| TurnTakingProcessor | 语音、转录文本和寻址证据 | Turn 决定。 |
| SpeechSynthesisProcessor | AUDIO_SYNCED 来源文本 | AudioFrame 及文本／音频对齐。 |
| TranscriptSynchronizationProcessor | 来源文本、对齐、播放和控制 | 根据播放得出的转录文本分块。 |

## 🎙️ 音频与转录

```text
RTC -> PerceptionRuntime.audio -> AudioActivityProcessor
    -> SPEECH_FRAME / SPEECH_SEGMENT -> SpeechTranscriptionProcessor
    -> TRANSCRIPT_SEGMENT
```

每个来源拥有独立的 VAD／分段状态。前导音频和有界队列使输入接入与转录和模型延迟相互隔离。语音工厂来自 `runtime.foundation.voice`（VoiceBundle）；Router 拥有借用的流／请求，而不是工厂的生命周期。

## 🎯 寻址与对话焦点

Semantic Addressing 使用配置的 Avatar 别名，以及自上一个已提交 Turn 以来的时序转录窗口（按媒体顺序排列的每位说话者的片段，外加有界的已提交 Turn 历史），把每条转录文本标注为 POSITIVE（对 Avatar 说）、NEGATIVE（不是对它说）或 UNKNOWN。每个结果标注其自身的转录文本，并引用它读取的上下文；只有已提交的 `TurnSnapshot` 才会让它所拥有的输入退役。UNKNOWN 表示弃权，不是存在其他受话者的证据。

明确的 POSITIVE／NEGATIVE 证据会更新对话焦点；UNKNOWN 保持焦点不变。纯音频交互可以从“面向 Avatar 的对话”这一先验开始，明确的非 Avatar 证据会覆盖该先验。模型实现保持在 SemanticAddressingModelBase 契约之后。

VisualAddressingProcessor 消费 FACE_DETECTION 标注，平滑朝向分数，并发布限定于主体的证据。当无法确定主体时，会跳过含糊的多人脸观测。人脸朝向是一种启发式判断，不是对视线的测量。视线、手势及其他未来的证据生产者可以使用同一标注契约。

寻址融合保留来源信息，检测相互冲突的目标，并让明确的当前证据优先于焦点回退。供应商特定的阈值保留在所属的模型／处理器中。

## 🔀 Turn 决定与 Engine 准入

TurnTakingProcessor 协调一个开放的时序输入窗口，以及等待 STT 或准入的已封闭输入、转录／寻址就绪状态、异步评估、过期结果拒绝和有界的证据等待。片段的说话者标签只会加入输入的 `input_devices`，从不设定输入的边界。它根据策略发布 COMMIT、HOLD、PASSIVE、INTERRUPT 或 CANCEL 决定。

```text
Speech + transcripts + addressing
    -> TurnTakingCoordinator / policy
    -> perception turn-decision annotation
    -> AvatarEngine
    -> committed Turn and Loop submission / precise interruption
```

Engine 现在拥有准入和原生执行调度。不存在单独的 TurnController 或 SDK 应答接收端（response sink）。Router 的决定本身不是模型请求，也不是持久化确认。

AUDIO_ONLY 和 AUDIO_VISUAL 组合可用的证据。VISUAL_ONLY 仍是主动行为的扩展点；其枚举值或已启用的视觉消费者并不意味着主动视觉 Turn 已完整实现。

## ⚡ 全双工交互

输入、转录、寻址、模型执行、合成和播放各自独立推进。开口打断无需等待最终转录文本或语义评估。打断之后，STT 和寻址可以继续运行，以判断是否适合给出一个新的已提交回答。

旧的决定不能仅因使用同一个 lane，就获得对较新执行的控制权。Runtime 在接受打断时就固定其目标；消费者使用这些精确的输出／lane／scope 标识。

## 🔊 原生输出

ASSISTANT 和 TRANSIENT 使用相同的原生输出契约：

```text
EnvOutput(TEXT_CHUNK, AUDIO_SYNCED)
    -> OutputRuntime.publish(...)
    -> SpeechSynthesisProcessor
    -> EnvOutput(AudioFrame / alignment)
    -> RTC audio adapter
    -> playback feedback
    -> TranscriptSynchronizationProcessor
    -> RTC transcript adapter
```

消费者读取 `event.output`。正式 scope、模型／条目来源信息、内容阶段和完成屏障都是类型化字段，而不是对执行有意义的元数据键。

一个逻辑输出拥有自己的合成任务。来源分块按顺序保留；替换或打断不能重新打开已退役的输出。输出文本保留空白和代码缩进。媒体发布复用已校验的 Core 音频帧；运行时发布不会对 PCM 重新编码。

TEXT_COMPLETE 封闭文本，AUDIO_COMPLETE 封闭音频／对齐的生产，COMPLETE 是 Runtime 输出的终态，PLAYBACK 是传输层交付的证据。合成、播放和转录文本的最终确定不会合并为一个通用的完成广播。

同步器根据已播放的音频释放文本。打断后，已交付的转录文本仍然保留；未播放的来源文本不会被报告为已听到。回退对齐根据合成时长估计时间；原生供应商对齐可以提高精度，而不改变 RTC 的契约。

IMMEDIATE 文本不等待音频。MIRROR 仍是供另一条独立拥有的交付路径使用的观察性文本，不是重复的可见回答。即使 AUDIO_SYNCED 输出不受支持，其消费者仍然存在，因此缺少 TTS 时会产生显式的终态结果，而不会让一个活动输出永远保持打开。

## ⚙️ 配置归属

```text
router.init_config.audio_activity       -> AudioActivityConfig
router.init_config.addressing.semantic  -> SemanticAddressingConfig
router.init_config.addressing.visual    -> VisualAddressingConfig
router.init_config.turn_taking          -> TurnTakingConfig
```

Addressing 拥有观测／模型设置。Turn Taking 拥有证据融合、协调、打断和期限。`addressing_wait_sec`、`transcript_wait_sec`、`transcript_timeout_sec`、`unsegmented_alignment_sec`、`speech_completion_wait_sec`、`commit_timeout_sec`、`max_pending_inputs`、`max_window_segments` 和 `fusion` 直接属于 turn_taking，而不属于其 policy 子树。`transcript_wait_sec` 只用于报告待处理的转录；`transcript_timeout_sec` 是让它退役的硬期限。schema 中 `transcript_wait_sec` 为 0.75 s；`demo.yaml` 以及 `config init` 和 Setup 写入的 profile 将其设为 3.0 s，与期限相等，因此在期限之前不会报告待处理的转录。

`interruption.enabled` 控制受支持的 Turn 打断；`interruption.audio_only_speech_start` 额外选择纯音频情况下的即时开口打断。不存在并行的 `voice.allow_interruptions` 开关。

完整配置见[示例](../../../examples/README.md)。已禁用的可选处理器不会被构造；输出消费者仍遵循其显式的不受支持输出处理。Runner 选择和模型初始化仍与处理器启动相互独立。

## 🔌 边界

Core 拥有数据、计时、状态转换和生命周期契约。Router 拥有交互处理器。Voice 拥有工厂。Persona 拥有身份处理。Engine 拥有准入和执行；Host 负责装配；RTC 拥有编解码器、房间／音视频轨资源和交付投影。

Router 不拥有数据库持久化、传输专属类型、Provider 客户端实现或另一个通用事件总线。它不会直接消费规范记录来替代 Memory／Context 消费者。

## 📦 安装

```bash
pip install "alpha-avatar-plugins-router[semantic,turn-taking]"
```

本插件通过 Agent 配置选择。`semantic` 和 `turn-taking` extras 安装默认配置所选的本地 Semantic Addressing 与 Smart Turn 运行时。
