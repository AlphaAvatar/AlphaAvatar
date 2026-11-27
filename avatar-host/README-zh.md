# AlphaAvatar Host

[English](README.md)

`alpha-avatar-host` 启动 AlphaAvatar，管理共享推理，并监督 Avatar 执行实例。
交互连接归会话后端管理；Agents、Core 和 RTC 不依赖 Host。
运行服务不需要 App。

## 📦 包结构

```text
alphaavatar/host/
├── main.py             # Public alphaavatar command.
├── version.py
├── cli/                # Commands (dev/start, config, setup, upgrade, cleanup, doctor), arguments and rendering.
├── configs/            # Strict Host/Avatar configuration loading.
├── workspace/          # Application, config and cache paths; Workspace continuity.
├── log/                # Console, JSONL, previews and optional event diagnostics.
├── service/            # The running Host.
│   ├── application/    # Bootstrap, shared services, health and signals.
│   ├── execution/      # Hosted execution ownership and end policies.
│   ├── processes/      # Execution subprocesses, IPC and bounded cleanup.
│   └── sessions/       # Attachments, modes and backend selection.
│       └── livekit/    # Native dispatch, connections and Character transport.
└── tools/              # Run on demand, beside the service.
    ├── doctor/         # Static and runtime diagnosis.
    ├── setup/          # Installation planning and environments.
    ├── upgrade/        # Switching an installation to another build once checked.
    └── cleanup/        # Removing the environments and builds current does not use.
```

[启动概览](../.github/assets/avatar-host/start-up-flow.png) ·
[包概览](../.github/assets/avatar-host/relationships.png)

这些图是概念性的。
Host 在父进程中持有执行句柄；Engine、Runtime 及其会话适配器在执行子进程中组装。

## 运行

使用仓库的 Python 3.13 环境和你已配置的供应商凭据：

```bash
alphaavatar --help
alphaavatar --version
ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/mm/pipeline_openai_tools.yaml
alphaavatar start examples/agent_configs/mm/pipeline_openai_tools.yaml
```

`dev` 默认使用 DEBUG 和一个可用的健康检查端口；它不监视也不重新加载代码。
`start` 默认使用 INFO 和 8081 端口。
帮助／版本命令不会启动模型，也不需要 RTC 凭据。
每个命令接受一个 bundle 名称、一个 YAML／JSON 文件，或不带参数以使用默认 bundle；配置覆盖在其后以 `key=value` 形式给出。

创建一个 bundle（连同其 profile；若尚未设置默认 bundle，则将其设为默认），并可选择在不启动任何内容的情况下检查它：

```bash
alphaavatar config init my-avatar --avatar-id my-avatar
alphaavatar config check my-avatar voice.tts.speed=1.2
alphaavatar doctor my-avatar          # installation, configuration, a diagnostic session
alphaavatar dev                       # the default bundle
```

`start` 和 `dev` 在启动前运行相同的校验。
所有命令和 bundle 布局见 [docs/cli](../docs/cli/)。
Python 入口位于 `alphaavatar.host.configs`（`select_configuration`、`load_application`、`check_application_paths`、`validate_plugin_settings`、`create_bundle`、`read_settings`、`describe_summary`、`describe_application`、`describe_error`、`format_failure`、`output_scrubber`）；Doctor 的报告来自 `alphaavatar.host.tools.doctor.diagnose`（异步），或者用 `prepare` 和 `Diagnosis.run` 先运行静态检查。

## 配置

将现有的 Avatar 设置保留在顶层，并在其旁边添加 Host 设置：

```yaml
host:
  rtc:
    backend: livekit
    init_config:
      connection_mode: dispatch
  log:
    events: false
    conversation:
      content: dev
      file_content: false
```

LiveKit 需要 `LIVEKIT_URL`、`LIVEKIT_API_KEY` 和 `LIVEKIT_API_SECRET`。
模型和工具供应商需要各自的凭据。
远程服务要求 TLS。

| 连接模式 | 行为 |
| --- | --- |
| `dispatch` | 使用 `avatar.name` 注册，并等待匹配的显式 dispatch。由分配提供房间。会话结束后 Host 仍保持可用。 |
| `direct` | 需要 `room_name`，可选择 `device_id`，并在其唯一的执行结束后退出。它仍然需要 LiveKit。 |

远程参与者的 `session_type` 元数据选择 `chat`、`agent`、`audio` 或 `video`；默认为 `video`。
这与连接模式和 `dev/start` 无关。

日志显示时间、级别、源码位置、PID 和内容。
`dev` 预览已提交的用户输入和已记录的助手文本；`content: off` 隐藏这些预览，`content: all` 在两个命令中都启用它们。
JSONL 文件保存在解析后的 Avatar 工作区的 `.logs/host/` 下；除非设置 `file_content: true`，否则不包含对话文本。
控制台捕获和供应商追踪有各自的保留策略。
分享之前，检查所有日志中是否含有个人数据。

`host.log.events=true` 配合 DEBUG 启用采样的 Core 事件元数据和缺口诊断。
这些日志保留来源流的身份和序号；它们不是无损记录，也不是全局有序的重放日志。
不要记录原始媒体或凭据。

## 运行时边界

Host 先启动输出，再启动 Engine 和输入。
断开会话会释放其适配器；何时结束其执行由 Host 策略决定。
共享推理只在执行子进程收尾之后才关闭，InferenceRuntime 始终是其 runner 进程的唯一所有者。
Ctrl+C／SIGTERM 请求有序关闭；重复按 Ctrl+C 不会放弃清理。

音频会话通过 `TranscriptSynchronizationProcessor` 使用由播放驱动的字幕。
PCM 按供应商的原生节奏流式传输；字幕发布和网络发送不会控制音频捕获的节奏。
只提供 PCM 的供应商使用估计的逐词时间，并用实测的音频时长加以修正。
LiveKit 播放反馈测量的是本地音频队列，而不是远端的扬声器。

健康检查路径为 `/live`、`/ready` 和 `/status`。
它们不做身份验证，默认绑定到 `127.0.0.1`；只有在受网络访问控制保护时，才显式设置 `host.health.bind`。
`/status` 报告就绪状态、runner 启动状态以及最近执行的 ID 和状态码；它不返回任何配置或凭据。
执行监督需要 POSIX。
进程组并不是能完整约束所有后代进程的沙箱；需要约束脱离的浏览器进程的部署，需要外部 cgroup／容器。
每个执行只支持一个附着。
重新附着、持久执行恢复和睡眠／唤醒尚未实现。
失去控制连接时，会先结束受影响的作业，再重新注册；不会重放模型或工具工作。
断开连接不会删除房间。

## 更多信息

[部署](../docs/DEPLOY.md) · [开发](../CONTRIBUTING.md) ·
[Avatar 工作区](../docs/avatar-workspace-layout.md) ·
[模型缓存](../docs/models-cache-layout.md) ·
[Character 设置](../avatar-plugins/perception/avatar-plugins-character/README.md)
