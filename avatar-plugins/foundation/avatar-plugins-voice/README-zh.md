# AlphaAvatar Voice 插件

[English](README.md)

Voice 是 Foundation 层插件，提供通过 `runtime.foundation.voice` 使用的 VAD、STT 和 TTS 实现。

## 所有权

共享容器是 `VoiceBundle`，不是 VoiceService，也不是单独的运行时。Host 选择语音工厂，并在构造 Router 之前注入该 bundle。Foundation 拥有可复用的工厂，并在借用方停止后关闭它们。

Router 处理器拥有各自的 VAD／STT 流、TTS 请求、队列和取消状态。ASSISTANT 与 TRANSIENT 合成共享所选的 TTS 工厂，同时保留各自不同的输出标识。消费者不关闭借用的工厂。

## 配置与推理

```yaml
voice:
  vad:
    plugin: silero

  stt:
    plugin: openai_segment
    model: gpt-4o-transcribe

  tts:
    plugin: openai
    model: gpt-4o-mini-tts
    speaker: ash
    instructions: Speak in a friendly and conversational tone.
```

这是一段配置片段；完整示例还会选择 Loop 和 Context。模型可用性和凭据取决于具体部署。

`voice.stt.language` 和 `voice.stt.prompt` 均为可选项，默认都不设置。
- `language` 是 ISO-639-1 代码（`zh`、`en`），模型会把它当作既定语言。不设置或设为 `auto` 时不发送语言：由模型自行检测语言，混用或切换语言的语音需要这样处理。固定语言是一种提示，不是检测得到的证据；`TranscriptionEvent.language` 只是重复该设置，从不表示检测结果。
- `prompt` 用于引导转录（人名、风格、保留每一句话）。
- `openai_segment` 两者都接受；`openai_realtime` 接受 `language` 和 `delay`，但不接受 `prompt`。所选实现不接受的设置会被 `config check` 在其所在位置（`voice.stt.prompt`）拒绝，与任何未知设置一样。

打断策略属于 `router.init_config.turn_taking.interruption`。未使用的 `voice.allow_interruptions` 字段已移除，并会被拒绝；它不是第二个打断开关。

选择 Silero 即同时选择其推理 runner。模型在 runner 初始化期间解析，而不是在插件导入时解析。参见[模型缓存](../../../docs/models-cache-layout.md)和[插件布局与边界](../../README.md)。

## 原生 TTS 与媒体契约

TTSBase 声明不可变的 `sample_rate` 和 `num_channels`，Host 据此配置 RTC 音轨。`synthesize(text)` 返回一个只供单一消费者使用、带有 `aclose()` 的 TTSStreamBase；Router 对自己打开的每个流都显式调用 `aclose()` 关闭。

`openai` 和 `voiceai` 都是 AvatarModulePlugin 工厂；配置过程不会构造供应商客户端，TTS 路径上也没有 LiveKit TTS 适配器、分块流或音频发射器。

| 插件 | 请求路径 | 请求的传输格式 | Core 输出 |
| --- | --- | --- | --- |
| OpenAI | `/v1/audio/speech` | `response_format: pcm`、`stream_format: audio` | 24 kHz 单声道 PCM_S16LE |
| Voice.ai | `/api/v1/tts/speech/stream` | `audio_format: pcm_32000` | 32 kHz 单声道 PCM_S16LE |

供应商 schema 位于 `tts/openai.py` 和 `tts/voiceai.py`；`tts/codec/pcm.py` 为两者负责有界的流生命周期、PCM 分帧、请求预算和重试。OpenAI 通过 OpenAI SDK 的流式应答进行流式传输，底层使用自己持有的 `httpx` 客户端，并关闭了 SDK 的重试；Voice.ai 使用该 codec 的 aiohttp 传输。两者都不解码压缩音频，也不对 PCM 重采样。TCP 分片会被组装成不可变的 Core 帧；这并不是端到端零拷贝的声明。音频内容不会存放在无界的应答缓冲区中。

每个供应商惰性地打开一个可复用的 HTTP 客户端。每个已准入的请求拥有一个有界帧队列、它的各次尝试任务和一个首段音频计时器；不会为每一帧创建任务。休眠中的请求在关闭之前一直计入容量，并且在首次被消费之前不会发起 HTTP。读到末尾、提前退出和取消时都必须关闭流。关闭工厂时先关闭所有流（包括休眠中的流），再关闭 HTTP 会话。并发的关闭调用方共享受管理的清理，调用方的取消在清理完成后才会传播。

这些可选的 `voice.tts` 设置沿用扁平的配置布局：

```yaml
voice:
  tts:
    plugin: openai
    model: gpt-4o-mini-tts
    speaker: ash
    timeout: 30.0
    frame_size_ms: 20
    queue_frames: 8
    max_streams: 4
    max_audio_seconds: 120.0
```

`timeout` 是请求的 HTTP 与重试等待预算；在队列中等待的帧和本地播放不消耗该预算。消费者较慢时生产者会暂停而不丢帧，该等待由消费者自身的期限限定：Router 的短语工作流可能施加更短的期限。这些限制约束的是供应商自身的请求和帧队列，而不是操作系统／TCP 缓冲区或整个进程的内存。

一个请求最多尝试 `max_retries` + 1 次（默认 1 + 1），且只在发出第一帧之前尝试；音频开始后不再重试任何内容。当第一次尝试在 `first_audio_hedge_after`（默认 2.5 s，设为 `null` 则禁用）之后仍未产出音频时，会从该配额中启动一次推测性尝试，先产出音频者胜出：这可能按第二次合成计费。`first_audio_timeout`、`read_timeout` 和 `retry_interval` 依次限定首帧时间、限定两次读取之间的间隔、设定重试前的暂停；该暂停随每次尝试增长。

非 200 应答、内容类型不匹配、经过编码／压缩的应答、空正文、截断的采样和过量音频都视为错误。常见的容器格式文件头会被拒绝，而不是作为原始 PCM 播放。这并不能证明任意原始字节的内容或采样率：那仍是供应商传输契约的承诺。Voice.ai 自动生成的 API 参考将默认应答标注为 audio/mpeg，同时也列出了 PCM 输出选项。本实现要求实际的内容类型与 PCM 兼容；不匹配的线上应答会失败，绝不会猜测，也不会把 MP3 当作 PCM 播放。发布前仍需要进行供应商账号集成测试和试听测试。

密钥来自 `OPENAI_API_KEY` 和 `VOICEAI_API_KEY`，或来自 `voice.stt.api_key_env` / `voice.tts.api_key_env` 指定的变量，绝不来自 YAML 密钥字段。对于 TTS，OpenAI 还会读取 `OPENAI_BASE_URL`；`voice.tts.base_url` 可为任一供应商显式覆盖 URL 基址。TTS 服务器要求 HTTPS；本地网关／测试允许使用回环 HTTP。URL 中嵌入的凭据、查询字符串和 fragment，以及跟随重定向，都会被拒绝。错误信息中不包含凭据、输入文本和 HTTP 错误正文。本地供应商服务器仍属于受信任的运维配置。STT 使用 OpenAI 的 API，除非 `voice.stt.base_url` 指定了其他地址，并且不读取 `OPENAI_BASE_URL`。

配置了 OpenAI instructions 时会原样传递；`tts-1` 和 `tts-1-hd` 模型会拒绝它们。Voice.ai 不接受这一 instructions 设置，会直接拒绝而不是忽略它。面向用户的应用必须告知用户语音由 AI 生成。

Router 仍拥有短语切分、输出标识、打断、对齐和完成屏障。TTS 传输关闭不能证明已经播放，也不是 OutputRuntime 控制事件的新来源。原生 Host 负责应用和执行进程的托管。原生 Character 呈现使用现有的 RTC 音频，不需要另一个 TTS 供应商或播放音轨。

## 传输格式参考

- [OpenAI 语音 API](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)
- [OpenAI 语音格式](https://developers.openai.com/api/docs/guides/text-to-speech#supported-output-formats)
- [Voice.ai 流式 API](https://voice.ai/docs/api-reference/text-to-speech/speech-stream)

```text
Source:       avatar-plugins/foundation/avatar-plugins-voice
Distribution: alpha-avatar-plugins-voice
Namespace:    alphaavatar.plugins.voice
```
