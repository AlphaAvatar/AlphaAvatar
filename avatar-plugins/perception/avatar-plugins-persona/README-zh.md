# 🧬 AlphaAvatar Persona 插件

[English](README.md)

Persona 提供可独立配置的用户画像、说话人识别和人脸识别。具体的处理、身份解析和持久化位于插件中；公开的画像和处理器契约保留在 Agents 中。

## 概览

```text
PersonaRuntime
├── ProfilerProcessor  -> profile deltas
├── SpeakerProcessor   -> speaker identity and attributes
├── FaceProcessor      -> visual identity and annotations
├── PersonaCache       -> active per-participant state
└── PersonaStore       -> persistent profile/identity state
```

每个处理器拥有自己的配置和生命周期。Provider 配置和 prompt 放在所属处理器下，而不是放在一个平行的插件级全局 Provider 树中。禁用 Profiler 不会禁用人脸／说话人身份识别或画像持久化。

## 处理器

| 处理器 | 主要输入 | 职责 |
| --- | --- | --- |
| Profiler | 已提交的对话／Turn 上下文 | 提取持久的画像增量，而不重新生成完整画像。 |
| Speaker | 经路由的语音观测 | 计算说话人 embedding（CAM++；3 s 窗口，短于一个窗口的语音按其自身长度计算一次），解析身份并更新声音属性，每项各在自己的有界通道上进行：一个 Turn 的 Context 只等待其片段的身份，最长等待 `speaker.identity_wait_sec`；属性用于之后的 Turn。向量按声音模型分别存储，存放在以模型为后缀的 `speaker_collection_name` 中（`_campplus`）；从不检索或合并其他模型的向量。 |
| Face | 摄像头视频帧；跳过屏幕共享帧 | 对帧采样、识别身份，并发布人脸／属性标注。 |

Speaker 和 Face 使用有界的推理队列，并保留来源身份；Face 每隔 `face.sample_interval_sec`（0.2 s）对一个来源采样一帧，其帧队列容纳 `face.frame_queue_sec`（0.4 s）的帧，分析落后时最旧的帧让位。原始音频或视频不会作为 Persona 画像持久化。人脸标注丰富感知证据，而不覆盖其原始观测。

画像加载、身份合并和运行时用户元数据与基于模型的提取相互独立。时区、登录时间、会话 ID 和登录次数是系统观测到的值，不是生成的画像事实。

## 运行时与生命周期

PersonaRuntime 负责缓存／上下文协调、来源绑定、初始画像加载和最终保存。它暴露 Core 生命周期钩子 `on_start()` / `on_stop()`。处理器保留 `start()` / `stop(finalize=...)`，使正常收尾与启动回滚保持区分。

部分启动的处理器在其启动 await 之前就会被跟踪。关闭时先停止所有自有处理器，再进行最终持久化；取消不能直接放弃自有的清理。随后，执行收尾的关闭让每个用户只对应一个缓存：绑定到同一个已接受用户的各参与者的缓存，合并进其最早参与者的缓存（Turn 按提交顺序各计一次，观测到的细节像保存时那样逐字段合并，说话人和人脸均值一并合并，取已完成的加载和最早的登录）。之后才运行每个处理器的 `finalize_caches()`，因此 Profiler 从每个用户的全部 Turn 中只提取一次其画像，每个用户也只保存一次。并发的关闭请求共享同一工作。清理或保存失败仍是错误，不会因为输出了日志就算作成功关闭。

画像状态通过 PersonaStore 加载／持久化，LanceDB 和 Qdrant 后端经由共享推理运行时访问，而不是在实时事件循环上进行同步数据库调用。

一个说话人跟踪是会话中的一个声音：它在任何来源和代上匹配，保留它被听到过的每个来源和代，并持续到说话人处理器停止；跟踪不限数量。短于 `speaker.short_segment_sec`（按其 VAD 范围为 1 s）的语音不单独匹配，也没有 Turn 等待它：它的音频接在同一来源的下一个片段之前，并入该片段的向量；下一个片段较长时立即并入，若是短片段，则在这些短片段合计达到 `speaker.short_merge_sec`（2 s）时并入；这些短片段采用该向量找到的关联。说话人跟踪的向量和参与者的说话人向量，各自是其所采纳片段的均值，每个片段的向量按其来源音频的秒数加权：一个 3 s 窗口，或较短片段自身的长度。会话运行期间，参与者的向量与用户存储的声纹保持分离。保存时，它被合并进为同一身份加载的那份声纹，权重为 0.95 存储 / 0.05 会话；绑定到同一用户的参与者只保存一次，使用由他们全部语音得出的一个向量。没有存储声纹的用户直接采用该向量，本会话分配的用户（没有任何存储内容）也是如此；对于加载未完成的其他用户，其存储的声纹保持不变。

每个已关联的语音片段，以及一帧中每张已关联的人脸，都会在存储的向量中检索：top-1 达到或超过 `speaker.identity_match_threshold`（0.6，CAM++ 向量的余弦值）或 `face.identity_match_threshold`（0.40，buffalo_l `w600k_r50` 向量的余弦值）时，将其参与者绑定到该用户，之后的匹配可以再次绑定。两个阈值都属于各自模型的向量，随模型而变；0.40 依据人脸评估的回放选定：在回放中，与 0.45 相比，它让有存储人脸向量的人更常被识别，代价是少量陌生人被绑定。

一帧中的人脸按框面积由近到远依次处理：超过 `face.max_faces` 时，最远的人脸不被跟踪，最近的人脸最先识别；在主参与者的设备上，最近的新人脸由主参与者采纳。同理，一个人脸跟踪是会话中的一张脸：它在任何来源和代上匹配，保留它被看到过的每个来源和代，并持续到人脸处理器停止；跟踪不限数量，`face.max_face_caches` 只限制保留人脸属性的参与者。人脸跟踪的向量是其采纳的每一帧的均值，每帧只计一次。参与者的人脸向量是其身份步骤所采纳各帧的均值，每帧只计一次，保存方式与其说话人向量相同：合并进为同一身份加载的用户存储的人脸向量，权重为 0.95 存储 / 0.05 会话；没有存储向量或该用户是本会话自己的用户时直接采用；加载未完成时保持不变；绑定到同一用户的参与者合为一个向量。

## 能力与上下文

启用的处理器会向 AvatarCapabilityRegistry 提供能力。能力是运行时描述符，可调用时也是类型化操作；它们不只是 prompt 元数据。禁用的处理器不会声明已启用的功能。

Engine 把 Persona 作为读取来源绑定到 ContextManager。Context 为一次查询截取相关的来源内容；它不接管 Persona，也不要求它在模型步骤之间重建 State。Persona 不负责前台生成或 RTC 投递。

## 配置

```yaml
persona:
  plugin: default
  init_config:
    profiler:
      enabled: true
    speaker:
      enabled: true
      inference_queue_size: 1
    face:
      enabled: false
```

此片段演示独立启用。完整示例还会配置 embedding 存储和 Profiler 的 Provider 网关。纯语音示例显式禁用 Face 和视觉寻址；多模态示例可以启用它们。参见[示例](../../../examples/README.md)。

## 安装与开发

```bash
pip install "alpha-avatar-plugins-persona[face,speaker]"
```

`face` 和 `speaker` extra 安装默认配置所选的人脸和说话人模型运行时。

保持职责就近：

```text
Identity/cache orchestration -> PersonaRuntime
Persistence                  -> PersonaStore
Public profile contracts     -> alphaavatar.agents.persona.schemas
Profiler implementation      -> processors/profiler/
Speaker implementation       -> processors/speaker/
Face implementation          -> processors/face/
```

不要仅仅为了共享启动逻辑，就把特定模态的实现移入 Engine。Foundation 服务是借用的，其所有者只在 Persona 停止之后才释放它们。
