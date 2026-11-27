# AlphaAvatar Status 插件

[English](README.md)

Status 是一个受生命周期管理的观察者，不是执行控制器，也不是工具依赖。它的处理器消费 Core 流并推导出呈现；它们不注册工具、不调用前台 Loop，也不发布规范的 Memory 记录。

## 数据流

```text
TurnRuntime events + Output.execution + assistant text
    -> Activity -> Presentation -> typed STATUS decisions -> RTC
                               -> Narration -> TRANSIENT text -> Router / RTC
```

StatusRuntime 拥有 activity、presentation 和 narration 处理器。每个处理器在 `processors/<name>/` 下拥有自己的配置和生命周期。

Activity 保留有界的、限定于 Run 的观测，并依据待处理的 Turn／执行事实解释独立调度的通知。替换一个输出并不是 Run 打断。journal 缺口是诊断上的丢失，不是编造缺失事实的许可。

Presentation 发布带有标识、范围、修订、过期时间和受众的 OutputStatusDecision，经由 EnvOutput 承载。内部决定保留在本地。RTC 只投射允许面向用户的字段，不投射工具参数、私有推理或规范记录。

Narration 消费符合条件的面向用户决定，并使用确定性的中英文规则。未来的模型渲染器必须独立于前台 Loop。播报是临时的，不是一次助手历史提交，也不会重新进入执行 journal。

## 过程说明、打断与终态状态

抑制取决于实际被接纳的文本和同一请求中的过程说明引用，而不是 Provider 名称标志。缺少过程说明时可以允许延迟的回退；失败和未知的工具结果各有不同的决定。已被取代的修订和已过期的决定，不能在之后仍像当前有效那样被播报。

生成的文本不能证明已经播放。启用音频的播报使用 AUDIO_SYNCED 文本，由 Router 负责 TTS／对齐；纯文本会话使用 IMMEDIATE 输出。用户打断和更新的输出可以抢占临时语音。

终态呈现的许可不同于模型生成的许可。终态决定可以保持可显示，而不重新激活已退役的 Run。播报与其决定绑定，并仍会检查范围、修订和有效性。它绝不能声称取消回滚了外部副作用。

## 配置

```yaml
status:
  plugin: default
  enabled: true
  action_topic: agent.status.action
  init_config:
    activity:
      max_pending: 128
      max_runs: 128
    presentation:
      waiting_delay: 1.5
      min_narration_interval: 4.0
      max_narrations_per_turn: 3
      decision_ttl: 5.0
      publish_timeout: 0.5
      system_decisions: true
    narration:
      enabled: true
      language: en
      publish_timeout: 1.0
```

`init_config: {}` 仍然有效。中文规则播报使用 `language: zh`。`text_topic` 已移除；文本和同步转写使用共享的 Output／RTC 路径。各项限制计数的是已发布的播报决定，不能证明语音已被听到。

Status 是有界的、尽力而为的观测／呈现。它的失败不能改变真实的工具结果，也不意味着规范记录已经持久化。

## 所有权与迁移状态

Engine 作为消费者创建／启动 Status，并在关闭消费者之前先让 Loop 收尾。Engine 和 Loop 发布事实；工具不依赖 StatusEmitter，也没有 `monologue` 请求字段。

SDK 执行桥接、原始 schema 的 SDK 工具投影和 TurnController 已移除。Status 观测原生主路径，而不是临时的 SDK 响应路径。Context 截取、模型选择、预算、规范记录和工具授权仍归各自对应的组件负责。
