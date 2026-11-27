# AlphaAvatar 部署指南

[English](DEPLOY.md)

在 Linux 服务器上运行原生 AlphaAvatar Host，并通过 LiveKit 连接浏览器客户端。按本指南操作之前，先安装一个经过测试的源码版本：某个发布版本的 tag，按 [README](../README.md) 中的方式设置，而不是 README 克隆的默认分支，默认分支包含尚未发布的改动：

```bash
git clone --branch v<version> --recurse-submodules https://github.com/AlphaAvatar/AlphaAvatar.git
```

本开发线面向 Linux 上的标准 CPython 3.13。部署之前，完成 [Python 迁移检查](../CONTRIBUTING.md#python-313-development-environment)，包括一个重新解析并经过审查的 Python 3.13 锁文件。仅修改包元数据，并不构成安装结果或模型兼容性结果。

源码检出中的命令从仓库根目录（`/path/to/AlphaAvatar`）运行。

## 准备部署

使用同一个服务账户，该账户能访问源码检出、其虚拟环境、Avatar 工作区和模型缓存。在服务停止时完成安装或升级，不要在会自动重启的服务中进行：

```bash
cd /path/to/AlphaAvatar
uv python install 3.13
uv venv .venv --python 3.13
uv sync --locked --all-packages
test -f .env.demo || cp .env.template .env.demo
chmod 600 .env.demo
```

复制步骤会保留已有的 `.env.demo`。配置所选 YAML 需要的 LiveKit、模型、embedding 和工具凭据。不要把密钥纳入版本控制。启动环境可以覆盖环境文件中的设置，空值也可以覆盖；但启动环境中为空或只含空白的凭据，或 `ALPHAAVATAR_HOME`，视为未设置，不会覆盖（[凭据](cli/config.md#credentials)）。

```env
LIVEKIT_URL=wss://your-livekit-host
LIVEKIT_API_KEY=your-key
LIVEKIT_API_SECRET=your-secret
OPENAI_API_KEY=your-openai-key
ALPHAAVATAR_HOME=/var/lib/alphaavatar
```

创建应用主目录，并让服务账户可写。不要仅为了访问 `/var/lib` 就以 root 身份运行助理。设置 `avatar.id: my_avatar` 且没有显式的工作区设置时，工作区为 `/var/lib/alphaavatar/avatars/my_avatar/`，模型缓存在 `/var/lib/alphaavatar/cache/models/` 下。

要使用单独的缓存，把下面的顶层部分合并到所选 YAML 中，并创建可写的缓存目录：

```yaml
application:
  cache_root: /var/cache/alphaavatar
```

这样模型会放在 `/var/cache/alphaavatar/models/` 下。如果设置了 `application.home`，它会覆盖由环境选定的应用主目录。对于已有的工作区，把 `avatar.workspace_root` 设为它完整的绝对目录；不会再追加 Avatar ID。从服务环境和 `.env` 文件中删除旧的 `AVATAR_WORK_DIR` 和 `ALPHAAVATAR_MODEL_CACHE` 值：Host 会拒绝这两个设置，而不是迁移已有数据。定位、备份和移动数据见 [Avatar 工作区](layouts/avatar-workspace.md)和[模型缓存](layouts/models-cache.md)。

### 或安装 Linux 安装包，再选择能力

在 Linux x86_64 上，CI 为每个发布版本构建一个小型基础包；在 `main` 和 `dev/**` 上，每次推送改动了包内容时也会构建：它自带 Python，以及 CLI、`config init|check` 和 `alphaavatar setup`。Setup 根据包内的制品目录（列出每个制品的版本和 SHA-256）安装 bundle 恰好需要的内容，检查后再启用。两者都不需要 Python、Node 或编译器：

```bash
curl -fsSL https://github.com/AlphaAvatar/AlphaAvatar/releases/latest/download/install.sh | bash
```

它的报告方式与 `alphaavatar setup` 相同：四个步骤（包、检查、安装、PATH），`OK` 及构建和命令，然后在 `Next` 下列出还需运行的内容；失败时在 stderr 上输出 `FAIL  Not installed` 及原因。颜色只在终端中显示；`NO_COLOR`、`TERM=dumb` 和重定向的输出得到内容相同的纯文本报告。

在终端中，首次安装完成后会提出运行 `alphaavatar setup`；如果 setup 失败或被取消，安装结果仍然保留。`--non-interactive`（`… | bash -s -- --non-interactive`）从不询问，没有终端的运行也不会询问。

为了新终端，安装器会在以 `# >>> AlphaAvatar >>>` 标记的块中把命令所在目录加入 PATH：bash 写入 `~/.bashrc` 以及登录时读取的文件（`~/.bash_profile`、`~/.bash_login` 或 `~/.profile`），zsh 写入 `${ZDOTDIR:-~}/.zshrc`，sh 写入 `~/.profile`。标记顺序错乱的文件保持原样。对于其他 shell，或安装器无法修改的文件，它会打印需要添加的那一行。在运行安装器的终端中，运行 `Next` 下的 `source` 那一行，或者打开一个新终端：

```bash
alphaavatar setup                       # a new bundle, asked part by part
alphaavatar doctor
```

未指定来源时，`install.sh` 安装最新发布版本。发布版本在其安装包旁发布的清单一次性指明该发布版本；安装包及其 `.sha256` 都来自该发布版本，安装包内必须包含这份清单，运行结束时打印所安装的版本和构建。最新发布版本缺少这些文件时报错，绝不会退回到更旧的发布版本：这一入口需要发布这些文件的发布版本，v0.6.9 及以后的发布版本都会发布。

Bash 在运行之前读取整个脚本，因此中途断开的下载什么也不会运行。完全失败的下载留给 bash 一个空脚本：什么都没有安装，但管道仍以 0 退出。因此，依据退出状态继续执行的脚本应先下载，如下面的无人值守示例所做的那样，或者设置 `pipefail`。最多指定一个来源：

```bash
curl -fsSLO https://github.com/AlphaAvatar/AlphaAvatar/releases/download/v<version>/install.sh
bash install.sh --version <version>     # that release
bash install.sh --file <package>        # a downloaded package, such as a CI build, its .sha256 beside it
bash install.sh --url <url>             # from a mirror, its .sha256 beside it
```

`--sha256 <hex>` 直接给出安装包的 SHA-256，代替其 `.sha256` 文件；通过管道运行时，安装器的参数写在 `bash -s --` 之后。

以问答方式运行时，setup 从 `config init` 的参考配置开始：语音、视觉、Memory 和 Persona，轮次判断、寻址、人脸和说话者模型都在本机运行（约需下载 515 MB；语义寻址模型需要 x86-64-v3 CPU）。每个部分都可以关闭；除语音输入所需的语音活动检测模型外本机不运行其他模型时，约 210 MB。向量存入 Avatar 工作区中的 LanceDB 或你自己的 Qdrant；模型和语音来自 OpenAI，或来自你自己的、提供 OpenAI API 的服务器（对话模型使用 Responses）。对于 CI 和无人值守安装，先创建或编辑一个 bundle，再设置该 bundle：凭据取自环境，不提出任何问题，在第一个失败的步骤处停止：

```bash
set -euo pipefail
curl -fsSLO https://github.com/AlphaAvatar/AlphaAvatar/releases/latest/download/install.sh
bash install.sh --non-interactive
export PATH="$HOME/.local/bin:$PATH"   # a script reads no startup file
alphaavatar config init my-avatar --avatar-id my-avatar   # edit its profiles as needed
alphaavatar setup my-avatar
alphaavatar config check my-avatar
```

`setup <bundle>` 安装 bundle 的设置所选择的内容（包括你做的修改）；如果某项选择不在本发布版本可安装的范围内，会在安装任何内容之前拒绝。你自己的每台服务器从一个以其 URL 命名的变量 `ALPHAAVATAR_SERVER_KEY_<hash>` 读取自己的密钥，setup 询问时会显示该变量：一个密钥只用于提供它时对应的服务器，只有同一台服务器才共用一个密钥，你自己的服务器永远不会收到 `OPENAI_API_KEY`。加载时会对照生效的 URL（已应用覆盖）检查该密钥：如果 bundle 的 `base_url` 被改到另一台服务器或被删除，该 bundle 会在创建任何客户端之前被拒绝；你自己命名的变量可以指向任何服务器。除非服务器就在本机，语音通过 HTTPS 发送其密钥。给定 bundle 时，setup 从环境、`.env` 或已存储的凭据中读取凭据，不存储任何凭据；以问答方式运行时，只有在你同意的情况下，凭据才会存入应用主目录设置中的一个文件，该文件只有你可读；那里已存储的值可能被其他 bundle 读取，只有再次确认才会被替换。使新 bundle 成为默认 bundle 的那次设置替换也会指明所存储的凭据，因此即使 setup 被强行终止，两者也要么都保持原样，要么都是新的。`start`、`config check` 和 `doctor` 在环境没有设置时读取已存储的值，并从同一次设置读取中获得默认 bundle。模型权重不属于安装计划：runner 会把它们拉取到模型缓存中，`doctor` 会指出缺少什么，并在你同意后下载。`--plan` 打印计划，不做任何改动。CI 或本地构建不是发布版本：它自己的 wheel 放在其安装包旁边，因此要为它传入 `--artifacts <directory>`。这些 wheel 存在时，安装器会把该参数传给它提出运行的 setup；没有该参数时，setup 会在提出第一个问题之前拒绝。

配置按能力类型和实现指定每个插件，由已安装包的入口点提供这些插件；`config check` 和 `doctor` 会在选择缺失插件的设置处指出它，并说明本发布版本的 setup 是否会安装它，同时给出针对所检查 bundle 的命令（`alphaavatar setup my-avatar`）；setup 不接受配置文件，因此检查配置文件时不给出命令。配置读取的变量如果没有值，例如 MCP 服务器的 `<MCP_PAT>`，会连同读取它的设置一起被指出。加载配置时会解析插件及其设置，以及这些设置所指定的模型供应商，并为它们所有的 runner 规划推理 worker：`config check` 报告的内容就是 `start` 启动的内容。

程序文件安装到 `~/.local/lib/alphaavatar`，命令安装到 `~/.local/bin`（`--prefix`、`--bin-dir`）；应用主目录、工作区和模型缓存保留在 `ALPHAAVATAR_HOME` 指定的位置。新的基础版本或 setup 的环境，会安装在当前版本旁边并完成检查，配置只在切换之后才启用；任何一步失败，当前的版本、命令、配置和数据都保持原样；安装器无法确认由自己创建的内容，一律不删除。再次运行 setup 会保留当前环境已有的内容，因此之前的 bundle 继续可用，即使是在本次 setup 等待确认期间完成的那个。
`packaging/linux/build.sh` 从源码检出构建同样的文件。

升级时，先停止服务，再运行 [`alphaavatar upgrade`](cli/upgrade.md)，先用 `--check` 查看当前构建和目标构建；`--file <package>` 接受 CI 构建。它在当前版本旁边准备目标的基础包和默认 bundle 的环境（由目标版本根据 bundle 的设置规划），检查它们，然后只切换一次 `current`；失败时安装保持原样。改为再次运行 `install.sh` 只会切换到新的基础包，bundle 的能力留给新一次 `alphaavatar setup <bundle>`。之前的版本和环境会保留；在服务仍处于停止状态时，[`alphaavatar cleanup`](cli/cleanup.md) 会删除它们，先用 `--dry-run` 查看哪些会删除、哪些会保留。

## 在前台检查配置

随附的 Demo 使用 `examples/agent_configs/roles/demo.yaml`。运行之前，检查其中启用的功能和服务：

```bash
ENV_FILE=.env.demo .venv/bin/alphaavatar start examples/agent_configs/roles/demo.yaml
```

LiveKit 按名称分派时使用 **`avatar.name`**，而不是 `avatar_name`。浏览器／后端必须把同一个名称分派到同一个 LiveKit 部署。随附的示例使用 `AlphaAvatar`。启动 Host 本身不会加入房间，也不能证明交互已经完成。

长期运行的服务使用 `dispatch`，不要使用一次性的 `direct` 模式。下面是要合并到现有 Host 部分的片段，不是完整的 Avatar 配置：

```yaml
host:
  rtc:
    backend: livekit
    init_config:
      connection_mode: dispatch
  health:
    bind: 127.0.0.1
    port: 8081
  log:
    banner: false
    color: never
```

通过启动日志和本地健康检查确认进展：

```bash
curl --fail http://127.0.0.1:8081/live
curl --fail http://127.0.0.1:8081/ready
curl --fail http://127.0.0.1:8081/status
```

`/live` 检查 Host 进程，`/ready` 检查服务就绪状态，`/status` 说明 runner 和执行状态，不包含配置或凭据。就绪不能证明语音、工具调用或播放已经成功。这些路径没有身份验证：除非设置了 `host.health.bind`，它们只绑定到 `127.0.0.1`，因此只能在你的部署网络管控之后暴露。安装服务之前，按 Ctrl+C 并等待正常关闭。

## 安装 systemd 服务

替换下面的 `/path/to/AlphaAvatar` 和 `your-linux-user`。使用虚拟环境中的实际可执行文件，使服务的主进程是 Host，而不是安装器或 shell 包装脚本。将 unit 保存为 `/etc/systemd/system/alphaavatar-demo.service`：

```ini
[Unit]
Description=AlphaAvatar native Host
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=your-linux-user
WorkingDirectory=/path/to/AlphaAvatar
Environment=ENV_FILE=/path/to/AlphaAvatar/.env.demo
Environment=PYTHONUNBUFFERED=1
Environment=NO_COLOR=1
ExecStart=/path/to/AlphaAvatar/.venv/bin/alphaavatar start /path/to/AlphaAvatar/examples/agent_configs/roles/demo.yaml
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
KillMode=mixed
TimeoutStopSec=300
SendSIGKILL=yes
UMask=0077
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**保留 `KillMode=mixed`**。第一个停止信号发给 Host，使它能够通过各自的关闭协议让执行收尾并关闭推理 runner。systemd 的默认值 `control-group` 会把第一个信号发给服务的所有进程，可能在 Host 完成清理之前终止 runner。不要改为 `process` 或 `none`，它们可能使子孙进程脱离管理。

systemd 最后的强制终止仍会覆盖服务控制组中剩余的进程，包括仍留在该组中的已分离浏览器进程。它可能在 Host 退出或停止期限到期时执行。这是服务范围的边界，不是按执行隔离浏览器，也不能证明外部工具的操作已被撤销。

300 秒的停止时限只是示例。修改进程或工具设置时，把它设为高于你预期的 Host 清理预算。强制终止不等于清理成功。不要为了掩盖关闭问题而禁用最后的回收。systemd 对 `Type=simple` 服务报告 `active`，也不等同于 `/ready` 返回 200。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now alphaavatar-demo
sudo systemctl status alphaavatar-demo
journalctl -u alphaavatar-demo -f
```

停止、重启或禁用服务：

```bash
sudo systemctl stop alphaavatar-demo
sudo systemctl restart alphaavatar-demo
sudo systemctl disable alphaavatar-demo
```

可选的 `examples/scripts/start_alphaavatar_demo.sh` 是前台设置辅助脚本，可以创建环境并同步依赖。它有意不作为上面服务的 `ExecStart`。服务重启不得隐式更新依赖。

## 连接浏览器前端

将前端／后端配置为使用同一个 LiveKit 部署和所选的 `avatar.name`。使用 `NEXT_PUBLIC_AVATAR_NAME` 的前端应将其设为该名称。将 `LIVEKIT_API_SECRET` 和 API 密钥保留在服务器端；绝不要给它们加 `NEXT_PUBLIC_` 前缀，也不要把它们嵌入浏览器端的打包文件。浏览器参与者从可信后端获取限定范围的访问令牌。

在 Host 注册之外，单独测试真实的分派、加入房间、文字交互和音频播放。测试回复过程中和工具操作过程中的取消。客户端断开连接不能证明外部操作没有执行。

## 日志、存储与更新

服务 journal 接收格式化文本。Host 自己的轮转日志文件是 JSONL，通常位于 `<workspace>/.logs/host/` 下；启动记录会报告其实际路径。不要把 journal 文本或旧 SDK 日志字段示例交给 JSON 解析器。用文本编辑器查看 JSONL 文件，或显式选取当前的 `created`、`level`、`source`、`line`、`pid` 和 `text` 字段。分享日志之前先审阅。

更新前后保持 Avatar ID 不变。当前布局如下：

```text
/var/lib/alphaavatar/avatars/<avatar_key>/
├── env/
├── users/
├── graph/
├── data/
│   ├── memory/
│   ├── sessions/
│   ├── indexes/
│   └── artifacts/
├── .logs/host/
└── .cache/

/var/cache/alphaavatar/models/      # Separate downloaded model cache.
```

更新之前，停止服务并备份其工作区。检出经过测试的版本，更新所需的子模块，然后使用已提交的锁文件同步：

```bash
sudo systemctl stop alphaavatar-demo
cd /path/to/AlphaAvatar
# Check out your tested revision here; retain a known-good rollback revision.
git submodule update --init --recursive
uv sync --locked --all-packages
sudo systemctl start alphaavatar-demo
journalctl -u alphaavatar-demo -n 100 --no-pager
```

在弃用备份之前，验证 `/ready` 和一次实际交互。不要让新旧部署使用同一个本地工作区，作为非正式的迁移测试。源码回滚不等于数据库恢复；保留停止服务时的工作区备份，以及经过测试的源码版本和环境设置。
