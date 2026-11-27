# AlphaAvatar 虚拟角色插件

[English](README.md)

AIRI 呈现使用原生的 Character 生命周期。它不接收 AgentSession，不生成回答，不合成语音，也不发布第二条音轨。渲染器消费 Agent 现有的 RTC 音频，并发布其画布视频。

## 所有权

Agents 暴露 `VirtualCharacterSession`、`CharacterTransport` 和不可变的 `CharacterConnection` 契约。Host 提供 `LiveKitCharacterTransport`，它拥有房间回调，并签发一个短期有效、限定于房间的渲染器 token。该 token 的参与者身份对每个执行实例都是唯一的。提供给渲染器的连接对象中不包含主服务凭据。

AIRI 插件拥有其 Playwright 驱动、浏览器、上下文和页面，以及注入的传输层的生命周期。会话附着端拥有 Character 会话，将其作为自己的呈现阶段。实时 Host 不会创建 AIRI 推理 runner、事件循环线程、未跟踪的浏览器任务或共享的固定端口服务器。

```text
Start:
    Character READY + video publication -> RTC outputs -> Engine -> RTC inputs

Stop:
    RTC inputs -> RTC outputs -> Character -> connection -> Engine -> AvatarRuntime
```

对于锁定版本的前端，先于音频输出启动 Character 很重要：它会在发送 READY 之前注册其音频订阅处理器。若先发布 Agent 音轨，可能会丢失该订阅事件。Character 不会替代现有的 OutputRuntime、Router 合成、转写或播放反馈路径。

Host 将这个确切的渲染器参与者排除在音频和视频感知之外。其他参与者仍可被感知。avatar 视频是输出，而不是用户证据。

## 前端准备

受信任的 AIRI 前端必须单独提供服务。这有意替代了旧推理 runner 自动执行 `pnpm dev` 启动的做法。一个前端服务可以服务多个相互隔离的执行实例浏览器。Host 不会停止这个共享服务。

仓库保留 `third_party/airi` gitlink。在 AlphaAvatar 仓库根目录初始化它，安装该 checkout 所需的 Node/pnpm 版本，然后准备其依赖和匹配的 Playwright Chromium：

```bash
git submodule update --init --recursive
alphaavatar-airi-install
cd avatar-plugins/perception/avatar-plugins-character/third_party/airi
pnpm --filter @proj-airi/stage-web dev --host 127.0.0.1 --port 5173 --strictPort
```

`alphaavatar-airi-install` 使用 `pnpm install --frozen-lockfile`，对这个 pnpm 工作区不回退到 npm，并运行 Playwright 的 Chromium 安装程序。这是一条显式的设置命令，不会在插件导入或实时通话期间执行。只有使用单独 checkout 的前端时才设置 `AIRI_REPO_DIR`。浏览器所需的操作系统库和合适的运行时用户仍需由部署提供。开发服务器不是生产托管的推荐方案；生产环境必须以适合 `/livekit-avatar` 的路由提供受信任的构建。

## 配置

在一个其余部分都完整的原生配置中显式启用 Character：

```yaml
character:
  plugin: airi
  init_config:
    frontend_url: http://127.0.0.1:5173/livekit-avatar
    video_width: 1280
    video_height: 720
    startup_timeout: 60.0
    close_timeout: 10.0
    chromium_sandbox: true
```

宽／高配置的是浏览器视口；实际编码的视频分辨率和帧率由前端决定。旧的、原本就被忽略的 `video_fps`、`audio_sample_rate` 和 `audio_channels` 选项已移除，并会被拒绝。未知键会被拒绝。渲染器消费现有的 Agent 音频；它没有单独的 PCM 设置。

Chromium 沙箱默认启用。请使用支持沙箱的部署用户／容器设置；不会自动回退到 `--no-sandbox`。可选的 `executable_path` 用于选择一个显式管理的 Chromium。优先使用与已安装 Playwright 版本匹配的浏览器。所提供的示例保持不变，仍为 `character.plugin: null`，包括以 AIRI 命名的语音人设示例。

## 就绪、失败与清理

只有来自与 token 绑定的那个确切参与者、出现在渲染器状态 topic 上的 READY 消息才会被接受。没有该参与者的视频发布，READY 并不充分。来自其他参与者的消息、无效 JSON 和超大数据都不能让会话就绪。缺少 READY／视频属于启动失败，而不是先警告再算作成功。传输层还会拒绝观察到的渲染器音频发布，而不是接受第二条播放路径。

启动后会监控浏览器／页面和传输层。崩溃、渲染器参与者丢失或视频取消发布，会通过会话附着端的失败监视器报告，从而结束当前执行实例。不会静默重试渲染器，也不会重复加入。发布就绪不能证明解码后的帧质量、帧的持续存活，或观看端的音视频同步。

驱动和浏览器的获取各有独立的任务所有权。取消不能丢弃迟到创建的句柄。清理会等待这些获取完成，关闭上下文／浏览器／驱动，移除传输层回调并报告失败。重复的调用方共享清理。`close_timeout` 适用于每个资源关闭操作，而不是整个关闭过程的绝对总期限；本地驱动的获取必须先完成才能释放，清理可能超出呈现启动的期限。

## 凭据边界

初始 HTTP 导航 URL 不包含 token。一个限定范围的初始化脚本通过浏览器本地历史记录，让锁定版本前端现有的查询参数读取逻辑获得连接参数；就绪后会移除该查询。请求使用不含 token 的 Referer，浏览器控制台／页面错误／请求日志不会转发到应用日志。会话错误只暴露安全的阶段／类型信息。这是对锁定版本前端的适配，而不是新的前端凭据协议，配置的前端仍属于受信任代码。

远程前端和 LiveKit 连接要求 TLS；允许本机回环开发。配置的前端 URL 不能包含凭据、查询或片段（fragment）。重定向离开所配置的源／路由会被拒绝。浏览器上下文相互隔离，service worker 被阻止，自动下载被禁用。不会禁用任何 TLS 验证。

真实的 AIRI 构建、LiveKit 服务器／客户端、画布视频以及收听／同步测试仍需进行。
