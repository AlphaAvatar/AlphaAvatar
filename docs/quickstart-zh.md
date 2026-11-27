# 快速开始

[English](quickstart.md)

用最新发布版本的 Linux 安装包，从零开始在 Linux 服务器上运行 AlphaAvatar Host。其他版本、镜像和无人值守安装见 [DEPLOY.md](DEPLOY.md#or-install-the-linux-package-then-choose-capabilities)。

## 准备条件

- Linux x86_64，glibc 2.28 或更新版本，以及 `tar`、`gzip`、coreutils 和 `curl`。安装包自带 Python：不需要 Python、Node 或编译器。
- 参考 bundle 约需下载 515 MB（本机只运行语音活动检测时约 210 MB），并需要约四倍于此的可用空间；语义寻址需要 x86-64-v3 CPU。
- 一台 LiveKit 服务器，即已实现的会话传输：`LIVEKIT_URL`（除非服务器就在本机，否则为 `wss://`）、`LIVEKIT_API_KEY` 和 `LIVEKIT_API_SECRET`。
- 所选模型供应商的密钥：参考配置使用 OpenAI（`OPENAI_API_KEY`），ENV memory 使用 Google（`GOOGLE_API_KEY`）；setup 也提供其他供应商和你自己的服务器。
- 一个加入 LiveKit 房间的客户端；本仓库不提供客户端（`avatar-app/` 为预留目录）。

## 安装最新发布版本

```bash
curl -fsSL https://github.com/AlphaAvatar/AlphaAvatar/releases/latest/download/install.sh | bash
```

程序文件安装到 `~/.local/lib/alphaavatar`，命令安装到 `~/.local/bin`，安装器会为新终端把该目录加入 PATH；在当前终端中，运行它在 `Next` 下打印的 `source` 那一行。在终端中，首次安装随后会提出运行 `alphaavatar setup`；无论拒绝、失败还是取消，安装都会保留。

## 运行 setup

```bash
alphaavatar setup
```

setup 从参考配置开始，逐步询问：能力、每个部分的供应商和模型、所选内容读取的凭据，最后是安装计划；按 Enter 保留参考配置的答案。输入的凭据只有在你同意时才会存储，存入 `<home>/settings/credentials-<id>.env`，只有你可读，绝不写入 bundle 或 profile 文件。setup 安装并检查该计划，之后才把这个 bundle 设为默认；失败时一切保持原样。默认不启用任何工具：在 bundle 的 tools profile 中启用 DeepResearch 或 MCP，然后运行 `alphaavatar setup <bundle>`。

如果要先编辑 bundle，或者没有终端（例如在 CI 中），先创建 bundle，再按名称对它运行 setup，凭据取自环境、`.env` 或已存储的凭据：

```bash
alphaavatar config init my-avatar --avatar-id my-avatar   # edit its profiles as needed
alphaavatar setup my-avatar
```

`config init` 把 bundle 写入应用主目录（在 Linux 上为 `~/.local/share/alphaavatar`，除非 `XDG_DATA_HOME` 或 `ALPHAAVATAR_HOME` 另有指定），并在尚未设置默认 bundle 时把它设为默认。见 [setup](cli/setup.md) 和 [config init](cli/config.md#config-init)。

## 用 Doctor 检查

```bash
alphaavatar doctor
```

Doctor 对安装和默认 bundle 的静态检查不下载、不联系任何内容。随后它只询问一次：同意后，它像 `start` 那样启动该 bundle 的运行时，下载缓存中缺少的模型文件，并把一个固定的语音场景运行 5 次（`--rounds N`），期间调用 bundle 指定的服务，这些调用可能产生费用。没有终端时，只有配置能[授权](cli/doctor.md#authorization)这一步；`--no-metrics` 只执行静态检查。Doctor 不使用任何 RTC 服务器或客户端。

## 启动 Host

```bash
alphaavatar start
curl --fail http://127.0.0.1:8081/ready   # in another terminal
```

`start` 加载并校验默认 bundle（或指定的 bundle 或文件），首次运行时创建应用主目录和 Avatar 工作区，并在 `127.0.0.1:8081` 上提供 `/live`、`/ready` 和 `/status`；runner 启动时会下载缓存中缺少的模型文件。Ctrl+C 或 SIGTERM 会在其拥有的所有资源释放后停止它。就绪并不能证明语音、工具或播放正常工作（[start](cli/start.md)、[服务](DEPLOY.md#install-a-systemd-service)）。

## 连接客户端

`config init` 和 setup 写入的 bundle 以 `dispatch` 模式使用 LiveKit：Host 以 `avatar.name`（其中为 `AlphaAvatar`）注册，并等待该名称的分派，每次分派提供各自的房间。让 LiveKit 前端及其可信后端使用同一个 LiveKit 部署，并分派这个名称；`LIVEKIT_API_SECRET` 和 API 密钥只保留在服务器端，浏览器参与者从该后端获得限定范围的访问令牌。参与者的 `session_type` 元数据选择 `chat`、`agent`、`audio` 或 `video`（默认 `video`）。启动 Host 本身不会加入房间：请实际测试分派、加入房间、文本交互和音频播放。见 [DEPLOY.md](DEPLOY.md#connect-the-browser-frontend) 和 [Host 配置](../avatar-host/README.md#configuration)。

## 从源码运行，用于开发

默认分支包含尚未发布的改动。它面向 CPython 3.13，需要 uv 0.10.0 或更新版本；`uv sync` 会安装所有包，因此不需要 Linux 安装包的 `setup`、`upgrade` 和 `cleanup`：

```bash
git clone --recurse-submodules https://github.com/AlphaAvatar/AlphaAvatar.git
cd AlphaAvatar && uv sync --all-packages --locked && source .venv/bin/activate
cp .env.template .env.dev    # then fill in the credentials
ENV_FILE=.env.dev alphaavatar config init my-avatar --avatar-id my-avatar
ENV_FILE=.env.dev alphaavatar doctor
ENV_FILE=.env.dev alphaavatar dev
```

`ENV_FILE` 指定读取凭据的 `.env` 文件（默认 `.env`）。`dev` 即 `start`，但使用 DEBUG 级别日志，健康检查服务器使用任意空闲端口；它不会重新加载代码。从源码部署时，请使用某个发布版本的标签（[DEPLOY.md](DEPLOY.md)）；开发环境和检查见 [CONTRIBUTING.md](../CONTRIBUTING.md#python-313-development-environment)。

## 下一步

- [DEPLOY.md](DEPLOY.md)：凭据、健康检查、systemd 服务、日志、存储和更新。
- [命令](cli/README.md)、[config](cli/config.md#credentials)、[upgrade](cli/upgrade.md) 和 [cleanup](cli/cleanup.md)；完整配置的[示例](../examples/README.md)。
- [Avatar 工作区](layouts/avatar-workspace.md)和[模型与缓存](layouts/models-cache.md)：数据和模型存放在哪里；[README](../README.md)；[CONTRIBUTING.md](../CONTRIBUTING.md)。
