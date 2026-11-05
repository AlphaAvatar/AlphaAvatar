# AlphaAvatar v0.6.9 第 1 项：干净机器安装 — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 本文件是安装与首次配置流程第 1 项（干净机器安装）的主日志，按时间顺序追加。第 2–5 项各有独立主日志。
- 统一的 KD/O 表仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 第 1 项 | Linux x86_64 安装器：自带 Python，按 tag 或 commit 的锁文件安装 Host，版本目录验证后再切换稳定入口 | 2026-11-05 | `7564770` | 未提交（用户提交） | 待审查。只新增 `scripts/install.sh` 和日志 |

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
