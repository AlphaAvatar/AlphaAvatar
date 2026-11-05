# AlphaAvatar v0.6.9 第 1 项：干净机器安装 — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 本文件是安装与首次配置流程第 1 项（干净机器安装）的主日志，按时间顺序追加。第 2–5 项各有独立主日志。
- 统一的 KD/O 表仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 第 1 项 | Linux x86_64 安装器：自带 Python，按 tag 或 commit 的锁文件安装 Host，版本目录验证后再切换稳定入口 | 2026-11-05 | `7564770` | 用户已提交（`9f86a6a`） | 已被返工取代：`scripts/install.sh` 已删除，第 7 节待复核的去向见返工第 8 节 |
| 第 1 项返工 | 1A 整理 `scripts/`；1B CI 构建的 Linux 参考安装包、配置三段分离、默认开启视觉、薄安装脚本 | 2026-11-05 | `9f86a6a` | 未提交（用户提交） | 待审查 |

## 历史记录（合并来源）

此前没有安装器的实施记录，只有"未做"的结论。原文都保留，相关日志头部加了指向本文件的链接。

| 原位置 | 原结论 | 现状 |
|---|---|---|
| `2026-10/2026-10-25/claude-code-2a-zh.md`，T-1 第 9 节"后续功能边界" | CLI 只有 `dev`／`start` 和 `--help`／`--version`，安装和升级回滚尚未实现 | 安装由本项落地；升级回滚是第 5 项 |
| `2026-11/2026-11-03/claude-code-t10-zh.md`，T-10A 第 10 节、T-10A1 第 4 节 | 安装器、安装升级列为未做 | 同上 |
| `2026-11/2026-11-03/claude-code-doctor-zh.md`，T-10B 范围和第 11 节 | Doctor 不做安装器和自动安装依赖；`packages.*` 只报告缺包和安装目标 | 不变。安装集合和 Doctor 能力检查的关系见第 7 节第 1 条 |
| `.github/workflows/quality.yml` 的 `install` job | 在源码检出里 `uv sync --all-packages --locked`，再跑导入、测试和 `alphaavatar --help／--version` | 不变。它在已有 Python 的 runner 上运行，不覆盖"机器上没有 Python"和"从任意目录运行" |

---

## 第 1 项 干净机器安装（基线 `7564770`）

### 1. 盘点

- **现有安装路径**（README、DEPLOY.md）：用户先自行安装 uv 和 Python 3.13，克隆源码，`uv sync --all-packages --locked`，再激活 `.venv` 或用 `.venv/bin/alphaavatar`。DEPLOY.md 的 systemd `ExecStart` 直接指向检出目录里的 `.venv`。
- **命令入口**：`alpha-avatar-host` 的 console script `alphaavatar = alphaavatar.host.main:main`。`--version` 输出 `AlphaAvatar <版本>`，取自 `alphaavatar/host/version.py`；`--help` 只做轻量导入。
- **锁文件**：`uv.lock` 有 336 个包，`requires-python >=3.13,<3.14`，全部来自 `https://pypi.org/simple`。
- **发布流程**：
  - 推 `vX.Y.Z` tag 只创建 GitHub Release；
  - PyPI 由人工按单包发布，不保证整组版本齐全。
  - 2026-11-05 查询 PyPI：core、agents、rtc、host、context、loop 有 0.6.8；provider 没有；其余插件停在 0.6.7。
  - 所以安装器不走 PyPI 单包，直接用 tag 或 commit 的源码和其中的 `uv.lock`。

### 2. 支持平台、原生依赖和 wheel 来源

**支持目标：Linux x86_64，glibc ≥ 2.28。** 下限由锁定 wheel 中最新的 manylinux 基线决定（livekit 1.1.2 为 `manylinux_2_28`）。musl 发行版和其他架构，安装器直接拒绝。

按锁文件统计各安装集合，目标为 CPython 3.13、Linux x86_64：

| 集合 | 包数 | wheel 合计 | glibc 下限 | 只有源码包 |
|---|---|---|---|---|
| `alpha-avatar-host[livekit]`（本项安装） | 91 | 120 MiB | 2.28 | `antlr4-python3-runtime 4.9.3`（纯 Python，安装时用 setuptools 构建，不需要编译器） |
| 根 `avatar-agent-all` 组 | 121 | 223 MiB | 2.28 | 同上 |
| 加载任意配置所需（Host + voice、memory、router、persona，见第 7 节） | 138 | 4166 MiB | 2.28 | 另有 `llama-cpp-python 0.3.35`：需要 C/C++ 编译器和 CMake |
| 全部包和 extra | 274 | 4589 MiB | 2.28 | 另有 `pylatexenc 2.10` |

- **本项集合的原生 wheel（18 个）**：
  - livekit 1.1.2（glibc 2.28）、livekit-blingfire 1.1.0（2.24）；
  - 以下为 2.17：numpy、opencv-python-headless、aiohttp、cffi、cryptography、pydantic-core、pillow、orjson、pyyaml、rpds-py、greenlet、brotli、zstandard、zopfli、uuid-utils、hf-xet。
- **wheel 之外的系统库**：WeasyPrint（Agents 依赖）运行时用 cffi 加载 GLib／Pango。干净的 Ubuntu base 上 `import weasyprint` 报 `cannot load library 'libgobject-2.0-0'`。`--version`、`--help` 不受影响，用到 PDF 的路径才需要这些库。
- **Python**：CPython 3.13.12，python-build-standalone 构建，由 uv 0.10.0 下载并按其内置校验和校验。
- **uv**：0.10.0，与 CI 固定的版本相同。来自 GitHub Release `uv-x86_64-unknown-linux-gnu.tar.gz`，安装器固定其 SHA-256 `230e3289…73f1ae`。
- **源码**：`codeload.github.com/AlphaAvatar/AlphaAvatar/tar.gz/<ref>`。
  - git archive 在 pax 头写有 commit，安装器从中读出 commit；
  - ref 是 SHA 时，要求两者一致。
- **构建后端**：workspace 包用 hatchling 构建（本次解析为 1.33.0），antlr4 用 setuptools（84.2.1）。uv 0.10.0 的 `sync` 没有构建约束参数，这两个版本在安装时解析，不在锁文件中（见第 7 节）。

### 3. 范围与决策

- **安装集合**：`alpha-avatar-host[livekit]`，即 Host、Agents、Core 和带 LiveKit 的 RTC，加上托管的 Python。
  - 这个集合不需要编译器，也不拉 CUDA。
  - 能力插件没有装，原因见第 7 节第 1 条，需要第 2 项先定。
- **ref**：
  - 只接受发布 tag（`vX.Y.Z`，规则与 `publish-pypi.yml` 相同）或完整 40 位 commit；
  - 分支名会移动，直接拒绝；
  - tag 的 Host 版本必须等于 tag 版本。
  - 开发分支按固定 SHA 验收，正式发布按 tag 和锁文件安装。
- **目录**，由平台安装器决定：
  - 程序目录 `--prefix`，默认 `$ALPHAAVATAR_INSTALL_DIR` 或 `~/.local/lib/alphaavatar`：
    - `versions/<版本>-<commit 前 12 位>/`：每个版本一个环境；
    - `current`：相对链接，指向当前版本；
    - `python/`：托管 CPython；
    - `tools/uv-0.10.0/`；
    - `cache/`：uv 缓存。
  - 命令 `--bin-dir`，默认 `$ALPHAAVATAR_BIN_DIR` 或 `~/.local/bin`。`alphaavatar` 链接到 `<prefix>/current/bin/alphaavatar`。
  - 程序目录与 `ALPHAAVATAR_HOME`（默认 `~/.local/share/alphaavatar`，与 Host 的平台规则一致）互不包含，否则拒绝。Workspace 和模型缓存都在 `ALPHAAVATAR_HOME` 下，安装器不读写它们。
  - uv、Python 和缓存都放在程序目录内（`UV_MANAGED_PYTHON=1`），不使用、也不修改用户已有的 uv 或 Python。
- **安装与切换**：
  - 虚拟环境不能搬移，所以用 `uv sync --locked --no-editable --compile-bytecode --no-default-groups --package alpha-avatar-host --extra livekit` 直接在最终版本目录里建环境。
  - 候选环境先在 `/` 下检查：`--version` 必须输出 `AlphaAvatar <源码版本>`，`--help` 退出码为 0，`uv pip check` 通过。
  - 检查通过后才写入完成标记 `alphaavatar-install.json`（ref、commit、版本、集合、uv、Python、安装时间），再依次切换 `current` 和命令链接。每次切换都是同一目录内的原子 rename。
  - 切换后再经由命令链接检查一次。
- **失败与并发**：
  - 安装过程持有 `flock`；
  - 失败、Ctrl-C 或 SIGTERM 时，EXIT trap 删除未完成的候选目录和工作目录，`current` 仍指向原版本；
  - 没有完成标记的版本目录不会成为 current，下次安装时会被清掉；
  - 已有完成标记时只做检查和切换，不重建。
- **命令冲突**：`--bin-dir` 下已有不是本安装器创建的 `alphaavatar` 时，在下载之前就拒绝，不覆盖。
- **PATH**：不改 shell 配置文件。Ubuntu／Debian 的 `~/.profile` 在 `~/.local/bin` 存在时会把它加入 PATH，新的登录 shell 即可直接运行。当前 shell 没有该目录时，安装器打印 `export` 提示。
- **用法**：先下载，再运行：`curl -fsSLO …/scripts/install.sh && bash install.sh --ref <ref>`。不用 `curl | bash`，避免下载中断时执行半截脚本。
- **本项不做**：
  - 能力协商、移动端 Runtime、多端协议；
  - 升级回滚和旧版本清理（第 5 项）；
  - 卸载命令；
  - 修改 README／DEPLOY.md（安装命令要引用尚不存在的 v0.6.9 tag）；
  - 加 CI job。

### 4. 改动文件

| 文件 | 改动 |
|---|---|
| `scripts/install.sh` | 新增，可执行（755）。最终版 SHA-256 `bf95a8978b8fb1fe2bf8284a182db84ce402652103730935d73398204d144096` |
| `docs/agent-logs/2026-11/2026-11-05/claude-code-install-zh.md` | 新增，本文件 |
| `2026-10-25/claude-code-2a-zh.md`、`2026-11-03/claude-code-t10-zh.md`、`2026-11-03/claude-code-doctor-zh.md` | 头部各加一行指向本文件 |

Python 包、`pyproject.toml`、`uv.lock` 和 CI 都没有改。

### 5. 干净机器验收

**环境**
- 本机没有 Docker，在本机内核上用 bubblewrap 0.4.0 运行独立根文件系统：
  - 独立的 user、PID、UTS 命名空间，空环境变量，共享主机网络；
  - 不挂载主机文件系统的任何部分。
- 根文件系统：`ubuntu-base-24.04.5-base-amd64.tar.gz`，SHA-256 `e77b6f10…0c86`，与 cdimage.ubuntu.com 的 SHA256SUMS 一致，glibc 2.39。
  - 原始镜像 91 个包，没有 Python、Node、curl、wget。
  - 以 root 身份用 apt 加了 `curl`、`ca-certificates` 和它们的依赖，共 17 个包（含 `openssl`），没有 Python。
  - 新建普通用户 `tester`（uid 1000），家目录取自 `/etc/skel`。
- 安装前确认：`python`、`python3`、`node`、`npm`、`uv`、`pip`、`alphaavatar` 都不存在，`/usr/lib` 下没有 `python*`。
- 内核 `Linux 5.10.134-19.2.al8.x86_64 x86_64`。

**被安装的版本**：`--ref 756477055ae45387582dda4e1955d3ac892cc6a3`（即 `7564770`，Host 版本 0.6.8）。

**结果**：以下用最终版脚本，在两份全新的根文件系统副本中实测，时间为 2026-11-05 15:50–15:52。

| 命令（tester，普通用户） | 退出码 | 输出要点 |
|---|---|---|
| `bash ~/install.sh --ref 7564770…`（副本 1） | 0 | 16 s。下载 uv 0.10.0、源码和 CPython 3.13.12，构建 4 个 workspace 包，装入 95 个包，`uv pip check` 通过。`current -> versions/0.6.8-756477055ae4`，`~/.local/bin/alphaavatar -> …/current/bin/alphaavatar`，打印 PATH 提示 |
| `bash -lc 'cd /srv && command -v alphaavatar && alphaavatar --version'` | 0 | `/home/tester/.local/bin/alphaavatar`、`AlphaAvatar 0.6.8` |
| `bash -lc 'cd /tmp && alphaavatar --help'` | 0 | 完整帮助，子命令 `dev, start, config, doctor` |
| `bash -lc 'cd / && alphaavatar --version'` | 0 | `AlphaAvatar 0.6.8` |
| 再次运行同一安装命令 | 0 | `already installed`，不重建。前后对比没有差异：current、命令链接、版本目录的 inode 和 mtime、完成标记、全部非 `.pyc` 文件内容 |
| 副本 2 独立安装同一 ref | 0 | 17 s。`uv pip freeze` 两边一致（95 个包，SHA-256 前缀 `301ae494ff42b24e`） |

- **两次独立安装的差异**：两边各 13475 个文件，路径和数量相同。逐文件比较后，只有三处不同：
  - 4 个本地构建包的 `uv_cache.json`：uv 记录的构建时间戳，`RECORD` 中只有这一行的哈希不同；
  - `alphaavatar-install.json` 的安装时间；
  - 部分 `.pyc` 的字节。
  - 其余 7593 个文件的哈希完全一致，与较早一次（脚本旧版）的安装也一致。

**完整安装记录**（副本 1）：
```json
{"ref": "756477055ae45387582dda4e1955d3ac892cc6a3", "commit": "756477055ae45387582dda4e1955d3ac892cc6a3",
 "version": "0.6.8", "package": "alpha-avatar-host[livekit]", "uv": "0.10.0", "python": "3.13.12"}
```
占用：`versions` 493M，`python` 107M，`tools` 53M，`cache` 16M。缓存与环境之间是硬链接，`du` 只计一次。

**拒绝与失败路径**（副本 1，最终版脚本）：

| 情形 | 退出码 | 结果 |
|---|---|---|
| `--ref dev/v0.6.9`（分支） | 1 | `--ref must be a release tag (vX.Y.Z) or a full 40-character commit SHA` |
| 不带 `--ref` | 1 | 同上 |
| `ALPHAAVATAR_HOME=~/data`，`--prefix ~/data/program` | 1 | `--prefix … lies inside the application home …` |
| `--bin-dir` 下已有别人的 `alphaavatar` | 1 | 下载前即拒绝，原文件内容不变 |
| `--ref v0.6.8`（发布 tag） | 0 | 解析为 `97510595826f…`，装入 `versions/0.6.8-97510595826f`，current 切过去，`--version` 为 0.6.8 |
| 再装 `7564770` | 0 | `already installed`，current 切回 |
| 安装 `36ba7f6` 时，候选目录已出现后，向整个进程组发 SIGINT（等同 Ctrl-C） | 130 | 候选目录和 `.work` 都已删除；current 仍是 `0.6.8-756477055ae4`，`alphaavatar --version` 正常；再次安装 `36ba7f6` 成功（0） |

**反向验证**（改动只做在 scratchpad 的脚本副本上）：
- **候选检查失败**（版本比较故意改错）：退出码 1，候选目录被删除，current 不变，原命令正常。这说明只有通过检查的候选才会成为 current。
- **中断测试本身的有效性**：
  - 第一版测试把安装器放在后台运行。非交互 shell 的后台任务会忽略 SIGINT，安装照常完成，测试因此无效。
  - 改为先恢复默认信号处理再运行。
- **INT／TERM trap 是否必要**：
  - 曾加过 `trap 'exit 130' INT` 和 `trap 'exit 143' TERM`。
  - 去掉它们后，Ctrl-C（退出码 130）和只发给安装器的 SIGTERM（退出码 143，等待 20 s 后没有残留的 uv 进程）都同样删除了候选目录。bash 本身会在这两种信号下执行 EXIT trap，所以最终版只保留 EXIT trap。

**其他检查**
- **原生依赖探测**（副本 1）：
  - `import livekit.rtc`、`cv2`、`numpy`、`alphaavatar.host.configs.loader` 都成功；
  - `import weasyprint` 失败，缺 `libgobject-2.0-0`；
  - `import alphaavatar.agents.configs` 失败，缺 `alphaavatar.plugins`；
  - `alphaavatar config init demo --avatar-id demo` 退出码 2：`ModuleNotFoundError module=alphaavatar.plugins`。见第 7 节第 1 条。
- **补充：本机 Alibaba Cloud Linux 3（glibc 2.32）**：
  - 用最终版脚本装到 scratchpad，退出码 0，`--version` 为 `AlphaAvatar 0.6.8`。
  - 环境的 Python 是程序目录里的 CPython 3.13.12，没有用到本机的 python3.6，也没有用到用户 uv 目录里的 3.13.13。
  - 这台机器预装了 Python，只作为补充证据，不算干净机器验收。
- **仓库检查**：
  - `uv lock --check` 通过（Resolved 336 packages）；
  - `pre-commit run --files scripts/install.sh` 通过（行尾空白、文件结尾、合并冲突检查；没有 shell 相关 hook）；
  - `git diff --check` 无输出；
  - `bash -n` 通过。
  - 本机没有 shellcheck。
  - 没有改 Python 代码，没有跑 pytest。

### 6. 环境限制

- **不是虚拟机**：验收在 bubblewrap 根文件系统中进行，用的是主机内核 5.10，网络与主机共享。根文件系统和用户空间是干净的，内核和网络不是。
- **apt 警告**：在单 uid 映射下，apt 改属主时出现 `chown … Invalid argument` 警告，不影响 curl 的安装和使用。
- **glibc 2.28 下限没有实测**：只实测了 2.39（干净环境）和 2.32（本机，补充）。下限来自 wheel 标签。
- **磁盘不足以实测大集合**：剩余约 7–9 GB，装不下需要 CUDA torch 的集合（wheel 约 4.1 GiB；开发环境装全部包后 `.venv` 为 9.0 GB）。干净环境也没有编译器，无法构建 `llama-cpp-python`。
- **验收依赖外部服务**：需要访问 GitHub（uv、CPython、源码）和 PyPI。没有测离线安装或镜像源。

### 7. 待复核

1. **Host 单独安装后，任何配置都加载不了，需要第 2 项先定。**
   - `alphaavatar.agents.configs` 在模块级导入四个插件包：
     - `alphaavatar.plugins.voice`（`configs/plugins/foundation/voice_config.py:25`）；
     - `alphaavatar.plugins.memory`（`perception/memory_config.py:24`）；
     - `alphaavatar.plugins.router`（`perception/router_config.py:27`）；
     - `alphaavatar.plugins.persona`（`perception/persona_config.py:26`）。
   - Agents 和 Host 都没有声明这些包，所以本项的安装集合只能运行 `--version` 和 `--help`，`config init` 会失败。
   - 如果把这四个包都装上：
     - wheel 共约 4.1 GiB（4166 MiB），其中 torch 2.9.0 来自 PyPI 默认的 CUDA 12.8 构建；
     - router 依赖的 `llama-cpp-python 0.3.35` 没有 wheel，需要编译器和 CMake，干净机器装不上。
   - 可选方向：
     - (a) 只在配置启用某个插件时才导入它，安装集合按配置决定；
     - (b) 安装器固定装全部能力，并解决编译和体积问题，比如 CPU 版 torch，或者提供 llama-cpp wheel；
     - (c) 其他。
   - 请决定后再开始第 2 项。
2. **构建后端不在锁文件中**：hatchling 1.33.0 和 setuptools 84.2.1 在安装时解析。uv 0.10.0 的 `sync` 没有构建约束参数，安装结果目前只靠这两个后端的输出稳定，两次实测确实一致。
3. **源码完整性**：tarball 的字节没有校验和；ref 为 SHA 时，校验了 pax 头里的 commit。tag 理论上可以被移动，目前只核对 tag 与 Host 版本一致。
4. **`uv pip freeze` 中的源码路径**：4 个本地包显示为 `file://<prefix>/.work/source/...`，该目录安装后已删除。真实来源记录在 `alphaavatar-install.json`。
5. **其他细节**：重复安装时，仍要下载源码才能解析出 commit 和版本。命令链接检查失败时，current 已经切换，不会自动恢复；这种情况需要命令目录本身出错才会发生。
6. **后续批次的文档与 CI**：README 和 DEPLOY.md 的安装段落，以及 systemd `ExecStart` 改用 `~/.local/bin/alphaavatar` 或 `<prefix>/current/bin/alphaavatar`，留给发布批次或第 4、5 项。是否在 CI 中跑安装器也待定：PR 来自 fork 时，codeload 上可能取不到该 commit。

---

## 第 1 项返工（基线 `9f86a6a`）

依据：用户与 Codex 对上一轮的审查意见。目标是同一套 runtime 按设备资源选择能力，打包边界现在就按"实际选择的能力"划分；跨设备协商不在本项。`RTC → Core`、`Agents → Core`、`Host → Agents` 的方向不变，安装和能力检查都在实时音视频链路之外。返工中途用户追加了五条决定，都已落实（第 2、3 节）：
- memory、persona、router 的导入不按 `default` 名字判断；
- 存储名改由各插件的 `NAMESPACE` 提供，代码里不再写死名字；
- Host 内与存储有关的名字也不写死；
- 删除仓库里的 `logs/`、`KMS/`；
- 用户自己修改了 `AvatarModule` 的取值（改为 `avatar.foundation.voice.stt` 等分层名，并删除了 `INTENTION`）。

### 1. 1A 整理 `scripts/`

| 原位置 | 新位置 |
|---|---|
| `scripts/add_copyright.py`、`check_workspace.py`、`doctor_samples.py` | `scripts/quality/` |
| `scripts/release.sh`、`create_pr_labels.sh` | `scripts/maintenance/` |
| `scripts/start_alphaavatar_demo.sh`、`stop_demo_livekit_rooms.py` | `examples/scripts/` |
| `scripts/install.sh` | 删除，由 `packaging/linux/install.sh` 取代 |

- 用普通 `mv` 移动，改动都留在未暂存的工作区。git 中的文件模式不变（`release.sh` 仍可执行）。与原文件逐个 diff，只改了以下几处：
  - `check_workspace.py` 的仓库根：`parents[1]` → `parents[2]`；
  - demo 启动脚本的仓库根：`/..` → `/../..`；
  - 三个脚本里写出的自身路径；
  - `release.sh` 的用法提示。
- 同步更新的引用：
  - Quality CI：`check_workspace`、`doctor_samples check --installed` 两处；
  - pre-commit：`add-python-copyright` 钩子；
  - Makefile：`RELEASE_SCRIPT`；
  - CONTRIBUTING.md 三处、DEPLOY.md、`docs/cli/doctor.md`；
  - `tests/doctor/test_samples.py` 的说明；
  - `host/doctor/samples.py` 的说明（原文写的是并不存在的 `scripts/make_doctor_samples.sh`）。
- `Makefile.bak` 是旧备份，不属于现行文档，没有改。`docs/agent-logs/` 下的历史记录保持原样。
- 单独验证（证据在 scratchpad 的 `evidence1/`）：

| 检查 | 结果 |
|---|---|
| 在仓库根和 `/tmp` 下运行 `python scripts/quality/check_workspace.py` | 两处都是 0，`16 members` |
| 变异：根目录改回 `parents[1]` | 退出码 2，`FileNotFoundError` |
| 在 `/tmp` 下运行 `CONFIG_FILE=missing-config.yaml bash …/examples/scripts/start_alphaavatar_demo.sh` | 打印 `Root dir: /home/ecs-user/AlphaAvatar`，在仓库根找到 `.env.demo`，停在 `Config file not found`，退出码 1 |
| 变异：根目录改回 `/..` | 在 `examples/` 下找不到 `.python-version`，退出码 1 |
| `pre-commit validate-config`；用 `add-python-copyright` 钩子跑新位置的 Python 文件 | 通过 |
| `make -n dry-run VERSION=0.0.0` | `DRY=1 scripts/maintenance/release.sh 0.0.0` |
| 不带参数运行 `scripts/maintenance/release.sh` | 退出码 1，用法提示里是新路径 |
| `python -I scripts/quality/doctor_samples.py check` | 两段样本从源码树读回 |
| 按 Quality CI 步骤：单独构建 Host wheel，在空环境里只装 numpy 和这个 wheel，执行 `check --installed` | 0，样本从已安装 wheel 的 `site-packages/alphaavatar/host/doctor/samples` 读回。wheel 内含 `card_question.wav`、`sum_question.wav` |

- **仓库里的 `logs/` 和 `KMS/`**：两者都是空目录，已删除。
  - `logs/` 是我在 17:32 验证 demo 脚本时产生的：脚本先 `cd` 到仓库根，在检查配置之前就执行了 `mkdir -p logs`。
  - `KMS/` 创建于 2026-05-08，里面只有一个空的 `KMS/logs/`，被 `.gitignore` 第 31 行忽略。`.gitignore` 的这一行没有改。

### 2. 1B 配置：生成与结构校验、所选能力的依赖检查、插件与 runner 装配分开

上一轮的阻断：`agents.configs` 在模块级导入 voice、memory、router、persona，只装 Host 时 `config init` 退出码 2。本轮把三个阶段拆开：

- **生成与结构校验不导入插件**：
  - 四个配置模块去掉模块级导入，改在各自的 `get_plugin` 里导入。memory、persona、router 只要构建就导入，不看插件名（用户决定）；voice 在所选的 VAD/STT/TTS 不为空时导入。
  - `ToolsConfig.model_post_init` 不再在校验阶段导入 MCP。
  - `agents/utils/files/__init__.py` 不再立即导入 `url_to_pdf`，deepresearch 改为直接导入该模块。原来 `config init` 写默认 bundle 时要用 `agents.utils.files.atomic`，会顺带导入 WeasyPrint；干净机器没有 Pango，这条链会失败。
- **所选能力的依赖检查**：
  - `AvatarConfig.plugin_packages()` 给出"配置位置 → 内置插件名"。插件 `<name>` 对应模块 `alphaavatar.plugins.<name>` 和发行包 `alpha-avatar-plugins-<name>`；这个方法本身不导入任何东西。
  - 规则：
    - context、loop 按 entry point 名判断：`default` 对应 context 包，`realtime` 对应 loop 包；自定义名由提供它的包注册同名 entry point，不需要内置包。
    - voice 看三个子项是否为空。
    - status、memory、persona、router 总是需要：它们总会被构建，status 在事件关闭时也会构建。
    - character、deepresearch、rag 看 plugin 是否为空；mcp 看是否启用。
  - Host 的 `loader._check_plugin_packages` 在导入任何插件之前用 `find_spec` 检查。缺失时抛出 `ConfigReferenceError`，信息逐行给出配置位置和包名。这一步发生在 `load_application` 里，所以 `config check`、`start`、`dev` 和 Doctor 的 `config.load` 都会经过它。
  - Doctor 的 `packages.capabilities` 原来自己维护一份映射，现改为用同一份 `plugin_packages()`；原映射在 status 关闭时不要求装包，与实际构建不符。
- **装配**：
  - `plan_inference_runners` 先导入所选插件（导入时注册 runner），再生成计划。
  - 计划按所选插件的配置顺序排列，与进程里先导入谁无关。顺序不固定时，Doctor 依次启动 runner 的两个会话测试失败；排序后恢复，变异验证见第 5 节。
  - `inference.methods` 的并行覆盖仍然按计划校验。
- **测试替身与 O-2**：`doctor_doubles` 原先靠 `import alphaavatar.agents.configs` 的副作用先注册内置插件，现改为显式导入。另有八个测试模块原先在收集阶段导入 `agents.configs`，是为了让插件导入时改环境变量（O-2）的副作用提前发生；现改为导入真正产生副作用的 persona 插件（经由 OpenCV）。
- **参考 bundle 默认开启视觉**：模板写入 `vision: enabled: true`，`input_mode` 默认为 vlm。
- **存储名与 `AvatarModule` 解耦**（用户要求）：
  - 用户把 `AvatarModule` 改为分层取值后，原先以 `AvatarModule.MEMORY/PERSONA/MCP.value` 为名的 Workspace 目录会随之改名，已有的 `graph/memory/`、`data/indexes/{memory,persona,mcp}/` 不再被读取，系统会静默新建空库。
  - voice、router、persona、memory、mcp、deepresearch、rag 七个有存储的插件各自新增 `namespace.py`，其中 `NAMESPACE = __name__.split(".")[2]`，由包名推导，不写字面量。loop、context、provider、status、character 没有自己的存储，所以没有加。
  - 使用处一律引用该常量：
    - Workspace 的 graph/indexes；
    - 模型缓存路径的第一级；
    - deepresearch 和 rag 的会话 artifacts。这两处路径改为 `artifacts/<NAMESPACE>/tavily`、`artifacts/<NAMESPACE>/rag_anything`，比原来多一级目录，见第 8 节；
    - memory 和 persona 的 provider 请求元数据 `"plugin"`；
    - runner 读取启动输入的 `config_for(NAMESPACE)`。
  - 推理配置快照不再写死键：memory、persona、mcp 的配置段各自给出 `runner_config()`，`snapshot_inference_config` 按 `plugin_packages()` 推导出的插件名组装。
  - Doctor 的 `_stores` 同样按 `plugin_packages()` 推导，配置段带有 `vdb_config` 即视为向量库；隔离路径用插件自己的 `NAMESPACE`。去掉 `== "default"` 后，自定义插件的显式 LanceDB 路径也会被重定向，远端 Qdrant 也会被判为无法隔离，比原来更保守。
  - 结果：磁盘目录取值不变（`graph/memory/` 等），`AvatarModule` 只作注册表和日志标识。

### 3. 1B 打包：CI 构建的版本化 Linux x86_64 参考安装包

- **安装集合**：根 `pyproject.toml` 新增依赖组 `reference-bundle`，即 `config init` 参考 bundle 所选的能力：
  - `alpha-avatar-host[livekit]`、`alpha-avatar-agents[vdb]`；
  - context、loop、`provider[langchain,openai]`、voice、status、router、memory、persona。
  - 不含 character、deepresearch、mcp、rag。
  - `build` 组加入 `cmake`、`ninja`、`scikit-build-core`，锁定版本分别为 4.4.4、1.13.2、0.12.2，用来按现有流程（导出 `build` 组作为构建约束）编译 llama-cpp-python。
  - `uv.lock` 只多了这三个包和分组清单，用 uv 0.10.0 生成；`uv lock --check` 通过（339 个包）。
- **`packaging/linux/build.sh`**：CI 和本地都调用它。产物是一个可整体搬移的目录，打成 `.tar.gz`，旁边附 `.sha256`。
  - 内容：
    - uv 安装并校验的 CPython 3.13.12，拷贝进 `python/`；
    - 锁文件中第三方依赖的 wheel，按哈希安装；
    - 本 commit 用 `uv build --no-sources --build-constraints` 构建的 12 个 AlphaAvatar wheel，与 Quality CI 相同；
    - 自带的 `bin/alphaavatar` 启动器：用 `python -I` 运行，不受调用者的 PYTHONPATH 和用户 site-packages 影响；
    - 改写后可搬移的 console script。
  - 三处按平台和能力决定的替换：
    1. torch、torchaudio 换成 CPU 版：清单在 `packaging/linux/torch-cpu.txt`，固定 URL 和 SHA-256，构建时核对版本必须与锁文件一致（2.9.0）。PyPI 的 Linux torch 会带约 3 GB CUDA 库，而参考 bundle 只有 speaker 的 fbank 用到 torch，在 CPU 上运行。CUDA 留给真正用得上的能力：RAG 的 MinerU 在开发环境里仍是原来的 CUDA 版。
       - 先试过在 lock 里按分组指定来源，uv 0.10.0 对虚拟工作区根的分组 source 和 `conflicts` 都不生效，所以没有采用。
    2. llama-cpp-python 0.3.35 只有 sdist：按锁文件里的哈希下载后编译成 wheel。参数为 `GGML_NATIVE=OFF`，显式开启 AVX/AVX2/FMA/F16C/BMI2（即 x86-64-v3）；关闭 OpenMP，避免依赖系统 libgomp；关闭用不到的 llava。
    3. 不装 `opencv-python`：它是 insightface 指名的 GUI 版 OpenCV，需要 libGL、X11、glib 等 8 个系统库，干净服务器上都没有。persona 锁定的 `opencv-python-headless` 提供同样的 `cv2`。
       - 在锁文件和开发环境里两者都会装上，谁覆盖 `cv2` 不确定；上一轮实测装上的是 GUI 版，这也是导入 cv2 时会设置 `QT_*` 环境变量的原因。
       - `uv pip check` 改为严格比对：输出里只允许出现 insightface 缺 `opencv-python` 这一条，任何其他问题都让构建失败。
  - **平台下限**：扫描产物里所有 ELF 实际引用的 GLIBC 符号版本，取最大值写入 manifest，超过 `--max-glibc`（默认 2.28）就失败。CPU 要求 `avx2 fma f16c bmi2`。
  - **构建前后检查**：
    - 检出有改动时拒绝构建，除非加 `--allow-dirty`，这时 id 带 `-dirty.<时间>`；
    - `--release vX.Y.Z` 要求 tag 等于 Host 版本且指向 HEAD；
    - 打包前在 `/` 下执行 `--version`、`--help`、原生库导入探测，并在临时 home 里执行 `config init` 和 `config check`。
  - **manifest**（`share/alphaavatar/manifest.json`）记录：id、版本、commit、release、glibc、CPU、导入探测清单、Python、uv、`uv.lock` 的 SHA-256、上述替换、全部包及版本。同目录还有实际安装的 `requirements.txt`（带哈希）和本地构建 wheel 的 SHA-256。
- **CI**：
  - 新增 `.github/workflows/linux-package.yml`：可手动按 commit 构建，也可由 release.yml 调用。它在 `quay.io/pypa/manylinux_2_28_x86_64` 容器里用 uv 0.10.0 运行 `build.sh`，以 `alphaavatar-linux-x86_64-<sha>` 为名上传制品。
  - `release.yml` 增加 `linux_package` 任务（`--release <tag>`）。创建 Release 后附上包和 `.sha256`；已附的同名资产保留不覆盖，因为它的 SHA-256 可能已经有人在用。
  - Quality CI 增加对两个脚本的 `bash -n` 检查。
- **`packaging/linux/install.sh`**（薄安装脚本）：只负责下载、校验和安装制品。
  - 用法：`--version X.Y.Z`（GitHub Release）、`--file PACKAGE` 或 `--url URL`。SHA-256 来自 `--sha256`，或制品旁边的 `.sha256`。
  - 目录：`<prefix>/versions/<id>/`、`<prefix>/current`、`<bin-dir>/alphaavatar -> <prefix>/current/bin/alphaavatar`。程序目录与 `ALPHAAVATAR_HOME`（含 Workspace 和模型缓存）互不包含，否则拒绝。
  - 修正的状态边界：
    1. 命令目录是否可写、是否已被别人的同名文件占用，在下载之前检查。
    2. 每次安装用 `mktemp -d` 在 `versions/` 下建独占临时目录，EXIT trap 只删除这个目录、本次运行创建的版本目录（切换前）和本次运行暂存的命令链接。已存在、但内容不同的版本目录一律拒绝，不删除。上一轮用的是固定的 `.work`，而且会直接 `rm -rf` 不带完成标记的目标目录。
    3. 先解出 manifest，与已安装版本逐个比对；已安装的版本不再完整解包，只做检查和切换。
    4. 候选版本先在临时目录里检查（`--version`、`--help`、manifest 列出的原生库导入），通过后 rename 到最终目录再检查一次，然后准备命令入口，最后切换 `current`。经命令入口复查失败时，`current` 恢复为原值。
  - `flock` 防止并发安装。
- **DEPLOY.md** 增加"Or install the Linux package"一小节：用法、目录、硬件要求，以及 `build.sh` 也可以从源码检出构建同一个包。

### 4. 改动文件

- **1A**：
  - 移动：`scripts/` 下 7 个文件；
  - 删除：`scripts/install.sh`；
  - 改引用：`.github/workflows/quality.yml`、`.pre-commit-config.yaml`、`Makefile`、`CONTRIBUTING.md`、`DEPLOY.md`、`docs/cli/doctor.md`、`avatar-host/alphaavatar/host/doctor/samples.py`、`avatar-host/tests/doctor/test_samples.py`。
- **1B 配置（Agents）**：
  - `configs/avatar_config.py`：新增 `plugin_packages`、`section`；
  - `configs/plugins/foundation/voice_config.py`；
  - `configs/plugins/perception/{memory,persona,router}_config.py`；
  - `configs/plugins/tools/tools_config.py`；
  - `runtime/inference/bootstrap.py`：计划前导入并排序、快照按插件名组装；
  - `utils/files/__init__.py`。
- **1B 配置（Host）**：
  - `configs/loader.py`：`_check_plugin_packages`；
  - `configs/template.py`：视觉开启；
  - `doctor/doctor.py`：`_capabilities` 改用 `plugin_packages`；
  - `doctor/session.py`：`_stores` 推导、隔离路径用 `NAMESPACE`。
- **插件**：
  - 新增 7 个 `namespace.py`：voice、router、persona、memory、mcp、deepresearch、rag；
  - 修改 memory 5 个文件、persona 5 个、router 2 个、voice 1 个、mcp 1 个、deepresearch 1 个、rag 1 个。
- **测试**：
  - `avatar-host/tests/cli/test_entrypoint.py`：新增"只装 Host"的回归测试；
  - `avatar-host/tests/configs/test_bundles.py`：新增"新解释器中参考 bundle 的 runner 计划"测试，模板比对改为开启视觉；
  - `avatar-host/tests/doctor_doubles.py`；
  - `test_health.py`、`cli/test_check.py`、`cli/test_doctor.py`、`configs/test_loading.py`、`configs/test_projection.py`、`doctor/test_isolation.py`、`doctor/test_session.py`：收集阶段改为导入 persona 插件。
- **打包与 CI**：
  - 新增 `packaging/linux/{build.sh,install.sh,torch-cpu.txt}`；
  - 新增 `.github/workflows/linux-package.yml`；
  - 修改 `.github/workflows/release.yml`、`pyproject.toml`、`uv.lock`。
- **用户自己的改动**：`avatar-agents/alphaavatar/agents/runtime/plugin/module.py`（`AvatarModule` 取值），已包含在以下所有测试和制品中。
- **本日志**。

最终脚本的 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `build.sh` | `26d7ca0a…1961ee2` |
| `install.sh` | `b369b6d9…bc583e45` |
| `torch-cpu.txt` | `fc809d23…c889ccb1` |
| `linux-package.yml` | `e041757d…8c859d81` |

### 5. 验证

**仓库检查**（最终工作区）：
- 全量离线 pytest：330 passed，耗时 2 分 18 秒，其中包括用户的 `AvatarModule` 改动；
- ruff check 和 ruff format 通过；
- `scripts/quality/check_workspace.py`：16 个成员一致；
- uv 0.10.0 `uv lock --check`：339 个包；
- 对全部改动和新增文件运行 pre-commit 通过；
- `git diff --check` 无输出；
- 对 5 个 shell 脚本执行 `bash -n` 通过。

**新增测试与变异验证**：每个变异都只改一处实现，测试随后恢复原文件。

| 变异 | 结果 |
|---|---|
| 计划前不导入所选插件 | 新解释器里的计划为空，B 测试失败 |
| 去掉 `_check_plugin_packages` | 只报 `ModuleNotFoundError module=alphaavatar.plugins.context`，A 测试失败 |
| 恢复 `utils/files/__init__` 对 `url_to_pdf` 的立即导入 | `config init` 失败，A 测试失败 |
| 模板关闭视觉 | 两条测试失败 |
| status 只在启用时要求装包 | A 测试失败 |
| persona 只在 `default` 时要求装包 | A 测试失败 |
| runner 计划不排序 | `doctor/test_session.py` 中 2 条失败 |
| memory 的 `NAMESPACE` 改回 `AvatarModule.MEMORY.value` | `test_launch` 和 `test_isolation` 共 3 条失败 |
| persona 改用其他存储名 | 2 条失败 |
| 快照按配置位置而不是插件名组装 | 3 条失败 |

A 测试即 `test_init_needs_no_plugin_and_check_names_each_missing_one_where_it_is_selected`，B 测试即 `test_the_reference_bundle_sees_and_plans_its_runners_in_a_fresh_interpreter`。

**本地构建**：
- 命令：`packaging/linux/build.sh --allow-dirty --max-glibc 2.32`，在本机 Alibaba Cloud Linux 3（glibc 2.32，gcc 10.2.1）上运行；
- 耗时：3 分 06 秒；
- 产物：`alphaavatar-0.6.8-9f86a6a0df65-dirty.20261105103740-linux-x86_64.tar.gz`，686,607,275 字节（655 MiB），SHA-256 `6ec6f4f1…18f0f99ce`；
- 解开约 2.2 GiB，装好后 2.3 GB；
- manifest 中 glibc 下限为 2.32；
- 构建期间工作区没有变化，制品输入与最终工作区内容的哈希一致。

**干净机器验收**：
- 环境与上一轮相同：bubblewrap 运行的 Ubuntu 24.04.5 base，glibc 2.39，普通用户 tester。
- 确认 python、python3、node、npm、gcc、cc、g++、make、cmake、ld、uv、pip 都不存在；没有 libGL、libgobject、libgomp、libX11；CPU 支持 `avx2 bmi2 f16c fma`。
- 安装脚本和制品都通过本机 HTTP 服务下载：GitHub Release 还没有这个版本，`--url` 走的是与 `--version` 相同的下载代码路径。
- 每一步前后都记录 `current`、命令入口的 inode、`versions/` 内容，以及应用数据（`~/.local/share/alphaavatar`）的路径和内容哈希。

| 步骤（tester） | 退出码 | 结果 |
|---|---|---|
| `curl -fsSLO …/install.sh`；`bash install.sh --url …/<A>.tar.gz` | 0 | 30 s。`current -> versions/0.6.8-9f86a6a0df65-dirty.20261105103740`，命令入口指向 `current/bin/alphaavatar`，打印 PATH 提示；没有残留临时目录 |
| 登录 shell 分别在 `/srv`、`/tmp`、`/` 执行 `command -v`、`--version`、`--help` | 全部 0 | 都找到 `~/.local/bin/alphaavatar`，输出 `AlphaAvatar 0.6.8` 和完整帮助 |
| 在 `/tmp` 执行 `alphaavatar config init reference --avatar-id reference` | 0 | 写出 bundle、12 个分层 profile 和默认 bundle 设置 |
| `alphaavatar config check`，以及 `--json` | 0 | 视觉开启（vlm），8 个 runner：memory 和 persona 的 lancedb、persona 的 face.analysis 和 speaker 的 attribute/vector、router 的 semantic qwen3_0_6b 和 smart_turn_v3、voice 的 silero，与开发环境对同一 bundle 的计划一致 |
| `config check 'runtime.inference.methods={"alphaavatar.voice.vad.silero": {"workers": 2}}'` | 0 | `8 runners (workers: alphaavatar.voice.vad.silero x2)` |
| 以未选中的方法名做并行覆盖 | 2 | `fields: runtime.inference.methods.no.such.runner` |
| `config check character.plugin=airi` | 2 | `Selected plugins are not installed …`，下一行 `character.plugin: alpha-avatar-plugins-character` |
| `config check tools.deepresearch.plugin=default tools.rag.plugin=default` | 2 | 两行，分别给出配置位置和包名 |
| 包内 Python 执行 `import weasyprint` | 1 | `OSError: cannot load library 'libgobject-2.0-0'` |
| 包内 Python 在进程内跑 `config check` | 0 | `weasyprint imported: False`；导入的插件只有 context、loop、memory、persona、router、status、voice |
| 重复安装 A（`--url`） | 0 | 16 s，走"已安装"路径，没有重新解包；前后状态和数据哈希（`ae62f794…`）不变 |
| `--bin-dir ~/readonly-bin`（只读目录）、`--bin-dir ~/a-file/bin`（父路径是普通文件） | 1、1 | 下载前即拒绝，服务器收到 0 个请求，状态不变 |
| 下载在 30 MiB 处被服务器截断 | 18 | `curl: (18) transfer closed …`，临时目录已清理，状态不变 |
| 下载中途 Ctrl-C：SIGINT 发给脚本和 curl，与终端前台进程组一致 | 130 | 临时目录已清理，状态不变 |
| `--sha256 000…0` | 1 | 下载后拒绝，提示文件与 SHA-256 不符，状态不变 |
| `--bin-dir` 下已有别人的 `alphaavatar` | 1 | 拒绝；原文件的哈希不变 |
| `--prefix ~/.local/share/alphaavatar/programs` | 1 | `Keep program files … and ALPHAAVATAR_HOME … apart` |
| 两个安装同时运行 | 后启动的为 1 | 后启动的报 `Another installation … is running`；先启动的被 SIGTERM 终止（退出码未记录），自己的临时目录已清理，状态不变 |
| 晚期失败：脚本副本去掉下载前的命令目录检查，`--bin-dir` 只读 | 1 | B 通过检查并移入 `versions/`，暂存命令链接时 `Permission denied`；本次创建的 B 目录被删除，`current`、命令入口、数据都不变，没有残留 |
| 安装 B（`--url`） | 0 | `current` 切到 B，命令入口仍是同一个 inode，`alphaavatar --version` 正常，A 保留 |
| `--file ~/<A>.tar.gz`（`.sha256` 放在旁边） | 0 | 走"已安装"路径，`current` 切回 A |

- **B 包的来历**：B 是从已安装的 A 目录打包的测试包，用于切换和失败场景。manifest id 加了 `-b`，去掉了 torch、pyarrow、lancedb、scipy、transformers、cv2、onnxruntime、sympy、llama_cpp、skimage，导入探测只保留 `livekit.rtc`。这样做是为了在剩余约 1.5 GB 的磁盘上让 A 和 B 同时存在。只有 A 是完整的真实制品。
- **glibc 2.32 的来源**：超过 2.28 的只有本机编译的 llama.cpp 库，其中 `libllama.so` 需要 2.29，`libggml-cpu.so`、`libllama-common.so` 需要 2.32；锁文件中的第三方 wheel 都不超过 2.28。CI 在 manylinux_2_28 里构建，这几个文件会回到 2.28 以内。

### 6. 过程中的问题与更正

1. **构建中途改了 `build.sh`**：bash 边执行边读脚本，第一次构建在打包阶段报语法错误。此后构建期间不再改动任何构建输入；验收用的制品由最终代码一次构建完成。
2. **第一次"命令目录不可用"测试无效**：bubblewrap 根文件系统的文件都属于测试用户，`/usr/local/bin` 其实可写，安装器按可写目录正常完成了安装。之后改用只读目录和"父路径是普通文件"两种情形。
3. **磁盘写满**：当时 A、B 同时安装，重装 A 要先完整解包，tar 写满磁盘后失败（退出码 2）。临时目录被清理，`current`、命令入口和数据都没变。由此改成先只解出 manifest。随后我的恢复命令没有检查这一步的退出码就删除了 B，导致沙箱里 `current` 一度指向不存在的目录，只影响沙箱。之后整套场景都用最终脚本，在全新的根文件系统里重跑。
4. **SIGINT 发给包括 bwrap 在内的整个进程组时会留下 `.install-*`**：bwrap 退出后整个 PID 命名空间被 SIGKILL，安装器的 EXIT trap 来不及执行。这相当于 `kill -9` 或断电，见第 8 节。按真实 Ctrl-C 只发给脚本和 curl 时，临时目录会被清理。
5. **B 测试包第一次去掉了 numpy**：`livekit.rtc` 需要 numpy，B 被候选检查拒绝（退出码 1，状态不变）。这本身也验证了"坏候选不会被切换"，但晚期失败和切换没有测到，于是保留 numpy 重做 B。
6. **用户修改了 `AvatarModule` 取值**：发生在第一轮验收进行中。已改为用 `NAMESPACE` 解耦，重新构建后整套验收全部重跑，第 5 节的结果都是重跑后的。

### 7. 环境限制

- **CI 没有运行**：新工作流要等推送后才会触发。本次制品是在本机用同一个 `build.sh` 构建的，带 `--allow-dirty`，因为改动尚未提交。所以 glibc 下限是 2.32 而不是 2.28；manylinux 容器里的实际表现（`objdump`、系统 cmake 与锁定 cmake）没有实测。
- **不是虚拟机**：bubblewrap 与主机共享内核 5.10 和网络。下载来自本机 HTTP 服务，没有走 GitHub Release，因为这个版本还没有发布。
- **磁盘只有约 1.3–4.7 GB 可用**，并且被机器上其他东西持续占用。B 因此用了测试专用的精简包，构建缓存也是用完即删。
- **没有实测**：glibc 2.28/2.29 的系统、不支持 AVX2 的 CPU、真实 RTC 会话和模型下载（属于第 3、4 项）。

### 8. 待复核

1. **上一轮第 7 节各条的去向**：
   - 第 1 条（配置导入插件）：由第 2 节解决；
   - 第 2 条（构建后端未锁定）：现在由 CI 按 `build` 组的约束构建，用户机器上不再构建；
   - 第 3 条（源码 tarball 完整性）：改为制品的 SHA-256；
   - 第 4 条（`.work` 路径）：已不存在；
   - 第 5 条（重复下载、切换后复查）：改为先读 manifest 判断是否已安装，复查失败时恢复原 `current`；
   - 第 6 条（文档和 CI）：DEPLOY.md 加了一节，并新增了工作流。
2. **CI 工作流需要首次运行**：确认 manylinux_2_28 容器里 `build.sh` 能跑通、manifest 中 glibc 为 2.28，以及 release.yml 附件上传。容器里有系统 cmake 时，scikit-build-core 会优先用它，而不是锁定的 cmake 4.4.4。
3. **校验和与制品放在同一处只能防止下载损坏**，不能防篡改。发布说明里应当公布 SHA-256，供 `--sha256` 使用。
4. **锁文件里同时有 GUI 版和 headless 版 OpenCV**：insightface 指名 GUI 版。开发环境里两者都会装上，`cv2` 由谁提供不确定（也是 O-2 环境变量副作用的来源）。Linux 包只装 headless 版；开发环境是否也统一，待定。
5. **CPU torch 用固定清单替换**：没有进入 `uv.lock`。升级 torch 时，`torch-cpu.txt` 必须同步改，构建时会核对版本。另外，memory 声明了 torchaudio 依赖但代码里没用到；WeasyPrint 是 Agents 的依赖，实际只有 deepresearch 用到。是否调整依赖归属，待定。
6. **llama-cpp-python 的 wheel 在 `site-packages` 顶层多装了 `lib64/`（30 MB）和 `include/`**：与 `llama_cpp/lib` 重复，是上游在 lib64 系统上的安装布局问题。参考包要求 x86-64-v3 CPU；如果要支持更老的 CPU，需要 ggml 的多变体动态后端，目前没有做。
7. **被 SIGKILL 的安装会留下 `.install-*` 临时目录**：安装器无法确认这些目录的归属，所以不删除。安装时会持有锁，所以持锁时遇到的 `.install-*` 必然来自已经死掉的运行。是否允许下次安装清理它们，请定。
8. **Doctor 里仍然写死了它对内置插件行为的认知**：`doctor.py` 的 `_BUILT_IN`、`session.py` 的 `vision_off`（persona 人脸、router 视觉寻址）和 `start_services`（memory/persona/mcp 的 embedding）。这些不是存储名，建议在第 3 项（Doctor 验证）一并处理。`session.py` 的 `_cleanup_check(self, dev)` 有一个早先就没用到的参数，同样留到第 3 项。
9. **布局变化**：deepresearch 和 rag 的会话 artifacts 多了一级 `<NAMESPACE>` 目录。只影响新会话，旧会话的产物原地不动，现有文档也没有写过这两个目录。
10. **`plugin_packages()` 中 loop/context 仍按 entry point 名判断**（`realtime`/`default`）：自定义的 loop/context 由提供它的包注册同名 entry point。如果希望改成总是要求内置包，请定。
11. **`.gitignore` 第 31 行的 `KMS`**：目录已删除，这一行是否保留，请定。
12. **旧版本不会被清理**：`versions/` 下的旧版本会一直保留，回滚和清理属于第 5 项。

交互配置与凭据、Doctor 运行指标、启动与停止、升级失败回退，按计划在本项审查通过后依次进行。
