# AlphaAvatar RTC

`alpha-avatar-rtc` 负责特定于传输的适配器。其基础包只依赖 `alpha-avatar-core`；`livekit` extra 启用 LiveKit 编解码器和适配器。

```python
from alphaavatar.rtc.livekit.audio.codec import from_livekit_audio_frame, to_livekit_audio_frame
from alphaavatar.rtc.livekit.audio.input import LiveKitAudioInput
from alphaavatar.rtc.livekit.audio.output import LiveKitTransientAudioOutput
from alphaavatar.rtc.livekit.status.output import LiveKitStatusOutput
from alphaavatar.rtc.livekit.text import LiveKitTextInput
from alphaavatar.rtc.livekit.transcript.output import LiveKitTranscriptOutput
from alphaavatar.rtc.livekit.video.codec import from_livekit_video_frame, to_livekit_video_frame
from alphaavatar.rtc.livekit.video.input import LiveKitVideoInput
```

与传输无关的图像转换位于 `alphaavatar.core.media.codecs.video`，可通过 `alpha-avatar-core[video]` 获得。

## 📦 包结构

```text
alphaavatar/rtc/livekit/
├── audio/                # PCM codecs, audio ingress and output transport.
├── video/                # Video codecs and video ingress.
├── text/                 # Bounded text-stream ingress.
├── transcript/           # Transcript delivery.
├── status/               # User-facing status delivery.
└── utils/                # LiveKit event-binding helpers.
```

此处只列出部分文件和功能目录；省略普通的包初始化文件。

## 生命周期与职责归属

媒体输入接收一个 LiveKit 房间和共享的 PerceptionRuntime。文本输入接收一个注入的提交回调；Host 将其绑定到 Engine 准入，而不引入 RTC 到 Agents 的依赖。输出适配器接收一个房间和共享的 OutputRuntime；用户转写输出则改为从 PerceptionRuntime 读取最终转写。

适配器暴露 `on_start()` 和 `on_stop()`，供 Core 生命周期协调使用。每个适配器拥有自己的订阅、回调、任务和传输资源。它不得关闭共享的房间、PerceptionRuntime 或 OutputRuntime。Host 的 SessionManager 在执行子进程中安排附着输出、Engine 和输入的顺序。SessionAttachment 释放适配器及其连接；HostExecution 另行让 Engine 和 AvatarRuntime 收尾。LiveKitConnection 报告传输事件，从不关闭执行，也从不删除房间。

部分启动会触发由其负责的清理。并发的关闭调用方共享同一次清理，调用方的取消在清理完成后才传播。已关闭的输入适配器不会重新启动。视频转换始终在事件循环线程之外进行，并在发布前检查来源世代。

包根不导入任何后端。RTC 适配器不得依赖 `alphaavatar.agents`、具体的感知插件或 `livekit.agents`。

## 原生输入与输出

`LiveKitTextInput` 消费 `lk.chat` 文本流，检查传输层提供的发送者身份以及有界的完整内容，然后调用注入的提交回调。它不会预先发布第二份感知副本。这个文本适配器没有实现附加的字节流。

尽管保留了原来的类名，`LiveKitTransientAudioOutput` 在同一条音频轨道上同时承载 ASSISTANT 和 TRANSIENT 输出。它不拥有模型，也不拥有第二条 TTS 管线。Host 提供所选 TTS 供应商声明的音频格式。

消费者读取 `event.output` 及其类型化的 scope、source 和 payload。中断使用 Runtime 固定下来的精确目标，而不是对后来的输出重新做宽泛匹配。播放反馈和最终转写的交付始终与生成完成相区分。内部状态决策和规范记录不会投影为客户端的状态内容。

## 迁移状态

编解码器、媒体／文本输入和音频／状态／转写输出位于此包。应用组装位于 Host。Engine／Loop 负责原生生成；Router 负责合成和转写同步。过时的 SDK model／turn／response 桥接和记录桥接已被移除，而不是作为受支持的替代路径保留。

Voice 提供原生异步 PCM 合成；RTC 只转换／交付由此产生的 Core 帧。原生 Host 负责应用和执行进程的托管；它不使用 Agents SDK 的 worker。原生 Character 呈现由 Host 组装。音频／视频输入适配器接受 `excluded_device_ids` 的不可变快照；对已有轨道和新订阅的轨道，都在创建来源世代或流读取器之前进行过滤。Host 只排除确切的渲染器身份，不会把 Character 输出回送到感知中。此次迁移尚未提供与连接无关的执行，也尚未提供持久的任务恢复。
