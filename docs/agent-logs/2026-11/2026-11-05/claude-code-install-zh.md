# AlphaAvatar v0.6.9 第 1 项：干净机器安装 — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 本文件是安装与首次配置流程第 1 项（干净机器安装）的主日志，按时间顺序追加。第 2–5 项各有独立主日志。
- 统一的 KD/O 表仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 第 1 项 | Linux x86_64 安装器：自带 Python，按 tag 或 commit 的锁文件安装 Host，版本目录验证后再切换稳定入口 | 2026-11-05 | `7564770` | 用户已提交（`9f86a6a`） | 已被返工取代：`scripts/install.sh` 已删除，第 7 节待复核的去向见返工第 8 节 |
| 第 1 项返工 | 1A 整理 `scripts/`；1B CI 构建的 Linux 参考安装包、配置三段分离、默认开启视觉、薄安装脚本 | 2026-11-05 | `9f86a6a` | 用户已提交（`124e012`） | 部分被第二轮取代：完整参考包改为基础包加 `setup`；1A、配置分段、`NAMESPACE` 保留 |
| 第 1 项第二轮 | 轻量基础包 → `alphaavatar setup` 选择 → 按能力补齐依赖 → 校验后启用；插件 extras 与 runner 依赖声明；开发分支 CI 制品与干净容器验收；发布草稿化 | 2026-11-05 | `124e012` | 用户已提交（`7c67240`） | 部分被第三轮修正：插件发现、激活事务、凭据保存、CI 三处失败 |
| 第 1 项第三轮 | 统一插件发现（能力类型 + 实现名，entry point）；安装与激活事务修复；向导凭据与自托管端点；glibc 扫描、Doctor 导入和 CI 重跑修复；短句 TTS 失败复现 | 2026-11-06 | `7c67240` | 用户已提交（`eb2404a`） | 部分被第四轮修正：自托管凭据、基础包本地安装、归属与凭据提交点、Provider runner 规划 |
| 第 1 项第四轮 | 自托管端点按服务器分开凭据并按后端规则校验地址；`install.sh --file` 先复制再校验；归属检查与凭据随设置一起提交；单一完整解析；修短句 TTS 测试 | 2026-11-06 | `eb2404a` | 用户已提交（`eee0c28`） | 部分被第五轮修正：自托管凭据绑定端点、设置一次读取、安装锁、Provider 级联与摘要 |
| 第 1 项第五轮 | 自托管凭据绑定到端点；默认 bundle 与凭据取自同一次设置读取；安装锁不经链接、不截断；runner 的多个 Provider 与级联 Provider；自定义 Memory 的摘要；URL 端口与空用户名 | 2026-11-06 | `eee0c28` | 未提交（用户提交） | 待审查 |

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

---

## 第 1 项第二轮返工（基线 `124e012`）

依据：用户对上一轮的审查意见。默认安装入口从这一轮起是「轻量基础包 → `alphaavatar setup` 交互选择 → 补齐依赖 → 校验并启用 bundle」，完整的 Linux 参考包被直接替换，不为旧包、旧安装方式或旧目录布局做兼容。`124e012` 是上一轮返工（用户已提交），其 Quality CI（run 42014311079）在 Ruff 一步失败。1A 的 `scripts/` 结构、DeepResearch 和 RAG 的新产物目录、`NAMESPACE`、配置三段分离都保留。所有改动在未暂存的工作区。

### 1. Ruff、开发分支制品与发布重试

- **Ruff I001**：`doctor.py` 的 `from packaging.requirements import Requirement` 被判为第一方导入。原因是仓库根新增的 `packaging/` 目录：Ruff 的 `src` 默认含仓库根，于是把 PyPI 的 `packaging` 当成本仓库模块。本地没报错，是因为 `.ruff_cache` 缓存了目录出现之前的结果，`ruff check --no-cache .` 可以复现。修复：
  - `[tool.ruff.lint.isort]` 加 `known-third-party = ["packaging"]`；
  - 该 TYPE_CHECKING 导入随第 2 节的重构一并删除。
- **开发分支无需 tag 即可出制品**：`linux-package.yml` 原先只有 `workflow_dispatch` 和 `workflow_call`。前者要求工作流文件在默认分支上，所以在 `dev/v0.6.9` 上只能经 tag 触发的 release.yml 运行。现在推送到 `dev/**` 即构建，并发组只取消被新推送取代的开发构建，发布构建总会跑完。
- **发布重试时归档与 SHA-256 不匹配**：原来的 release.yml 逐个上传、跳过已存在的文件，构建产物又不可复现。若第一次只上传了 tarball，重试会附上另一次构建的 `.sha256`；改成多文件之后，catalog 里的哈希和 wheel 也会来自不同构建。现在改为：
  - Release 先以草稿创建，草稿对外不可见；
  - 删除草稿里本次构建没有的文件，用 `--clobber` 上传本次构建的全部文件；
  - 核对附件的文件名和大小与本次构建一致后才发布；
  - 已发布的 Release 在重试时一个文件都不改，因为可能已有人按它的校验和安装。
  - 另外，tar 改为按名排序、使用提交时间、属主为 0、`gzip -n`，同一构建树打包结果一致。wheel 和编译产物本身仍不保证可复现，所以一致性靠草稿流程保证，而不是靠复现。

### 2. 能力：插件 extras 与 runner 的依赖声明

上一轮中，voice、router、persona 把本地推理依赖写在必选依赖里，因此「只用远端推理」也会装上 torch、llama-cpp、insightface 等。这些依赖现在改为插件的 extras：

| 分发 | 必选依赖（去掉的） | 新 extra |
|---|---|---|
| `alpha-avatar-plugins-voice` | 去掉 onnxruntime | `silero = [onnxruntime]` |
| `alpha-avatar-plugins-router` | 去掉 llama-cpp-python、onnxruntime、transformers | `semantic = [llama-cpp-python]`、`turn-taking = [onnxruntime, transformers]` |
| `alpha-avatar-plugins-persona` | 去掉 insightface、onnxruntime、torchaudio | `face = [insightface, onnxruntime]`、`speaker = [onnxruntime, torchaudio]` |
| `alpha-avatar-plugins-memory` | 去掉 torchaudio（代码未用，上一轮第 8 节第 5 条） | 无 |
| `alpha-avatar-agents` | `vdb` 拆开 | `lancedb = [lancedb]`、`qdrant = [langchain-qdrant, qdrant-client]` |

- 插件导入时本来就只在 runner 里懒加载这些库（逐个核对过）。唯一的例外是向量库：`storage/vdb/__init__.py` 会同时导入 LanceDB 和 Qdrant 两个模块，而 Qdrant 模块顶层导入 `qdrant_client`。改为每个后端只导入自己的模块（memory、persona 的 `inference.py`），`__init__` 只保留说明。
- **每个 runner 声明自己要的包**：`InferenceRunner.REQUIRES`。
  - 插件 extra 用 `plugin_requirement(NAMESPACE, "<extra>")` 生成，分发名由插件包名推导，不写死名字。
  - 向量库 runner 用 `vdb_requirement("lancedb"|"qdrant")`。
  - 共 11 个 runner 都已标注。
- **Agents**：
  - `AvatarConfig.plugin_factories()`：每个配置位置在启动时会创建哪个工厂（`AvatarModule` 和名字）；
  - `AvatarModulePlugin.registered()`：查询工厂是否已注册。
- **Host `configs/capabilities.py`**：`resolve_capabilities` 和 `check_capabilities` 按配置位置逐项求出「需要什么、缺什么」：
  - RTC 后端对应的 Host extra；
  - loop 和 context 仍按名字查找 entry point（保留按名称发现的机制），找到后加载，由它注册工厂；
  - provider 后端：从配置校验后的 task 里收集，包括默认值和 embedding 的默认后端，并记下第一个用到它的配置位置；
  - `plugin_packages()` 里的插件包；
  - 每个选中位置的工厂是否已注册；
  - runner 计划中每个 runner 的 `REQUIRES`；
  - 最后按安装元数据逐项核对版本和 extra，extra 不存在也会报出。
- **在哪里检查**：
  - `config check`：只读，`_load` 末尾检查；
  - `start` / `dev`：在准备 home 和工作区之前检查；下载、安装和校验都发生在实时会话之前；
  - Doctor 的 `packages.capabilities` 改用同一套求解。Doctor 明细的标签因此从 `rtc`、`providers` 变成了配置位置，测试断言随之更新。
- 报错示例（沙箱实测，见第 6 节）：
  `persona.plugin (runner alphaavatar.persona.face.analysis): alpha-avatar-plugins-persona[face]: insightface is not installed`。
- 开发环境的默认依赖组 `avatar-agent-all` 改为带上全部本地 extras，开发环境的内容不变。上一轮的 `reference-bundle` 组改名为 `setup-catalog`，作为 Linux catalog 的根，并加入 deepresearch 和 mcp。rag 和 character 依赖太重（docling、playwright 浏览器），暂未纳入 catalog。

### 3. `alphaavatar setup`

能力选择（平台无关）和 Linux 上的分发分开放在两层：

| 模块 | 层 | 内容 |
|---|---|---|
| `host/setup/choices.py` | 平台无关 | `Selection`：语音、视觉、本机模型、向量库（LanceDB 或自托管 Qdrant）。预设 `default`（参考 bundle）和 `remote`（除语音分段所需的 VAD 外，本机不跑任何模型）。每个选择对应：要替换的配置段、需求（PEP 508）、按后端需要的凭据、给人看的能力描述。CLI 和以后的 App 共用这一层 |
| `host/setup/plan.py` | 平台无关 | catalog 加需求得到安装计划：每个制品的版本、文件、SHA-256、大小、glibc 下限和 CPU 标志，按分发名排序。计划 ID 是计划文档的 SHA-256：同一版本、平台、基础包和需求，计划和 ID 都相同。模型权重不进计划，由 runner 下载到模型缓存 |
| `host/setup/environment.py`、`probe.py` | Linux | 在基础包的 Python 之上建虚拟环境，装入计划中的 wheel（`installer` 库），检查通过后切换 `current` |
| `cli/commands/setup.py` | CLI | 交互问答，或 `--preset` 给 CI 和无人值守部署用，两者走同一条安装路径；`--plan` 只打印计划；`--artifacts` 指定本构建自己的 wheel 所在位置 |

- **选择与实际需求对拍**：16 种选择组合下，`requirements(selection)` 都与该配置在完整环境中 `resolve_capabilities` 求出的需求完全一致（测试见第 6 节）。
  - LanceDB 选择会显式写 `url: null`。原因：运行时会从环境变量 `QDRANT_URL` 取默认值，环境里设置了它就会把向量悄悄挪到 Qdrant。
  - Qdrant 选择写 `${oc.env:QDRANT_URL}`，在加载时解析。
- **`remote` 保留 Silero VAD**：两个 STT 实现（`openai_segment`、`openai_realtime`）都按 `segment_id` 收音频，而语音片段只来自 router 的 audio activity，也就是本机 VAD。所以「只用远端推理且开语音」仍需要 onnxruntime 和一个约 2 MB 的模型。关闭语音（`--no-voice`）后，计划里就没有任何本地推理库。
- **安装事务**（`environment.install`）：
  1. 在前缀上取与 install.sh 相同的锁；
  2. 下载全部制品并按大小和 SHA-256 校验，此时环境目录还不存在；
  3. 建虚拟环境，逐个装入 wheel，本次下载的 wheel 装完即删以节省磁盘；
  4. 在新环境里先跑 `probe`：逐个导入环境自己的包中含 `.so` 的最外层包，确认本机能加载这些 native 库；
  5. 再用新环境的命令对待启用的配置（profile 内联成单文件）跑 `config check`；
  6. 写入 `plan.json` 作为完成标记，切换 `current`；
  7. 最后启用配置：先存凭据，再创建 bundle 并设为默认，失败时撤销凭据。
  - 任何一步失败或收到信号，清理按磁盘上的实际状态判断：`current` 指向新环境且尚未启用，就切回原来的版本；删除本次创建的环境和临时目录，清理期间屏蔽信号。
  - SIGTERM 和 SIGHUP 在 setup 里像 Ctrl-C 一样让程序走到清理，返回后还原原来的信号处理器。
  - 已有完整环境（`plan.json` 与计划相同）时直接复用，只再检查一次。同一计划留下的残缺目录（没有 `plan.json`）在持锁时重建。
- **新计划保留当前环境已有的需求**：当前环境的需求（来自 `plan.json`，且基础包相同）会并入新计划。验收中发现，新增一个远端 bundle 后，原来的默认 bundle 就无法通过检查了（第 7 节第 3 条）。合并后，新增 bundle 不会让旧 bundle 失效；若新需求不超出现有环境，就直接复用。
- **凭据**：
  - 交互模式逐项询问，秘密用 `getpass` 输入；`--preset` 时从环境读取，缺少必需项则在任何改动之前报错。
  - 保存在 `<home>/settings/credentials.env`，权限 600。写入方式是先写临时文件再整体替换，同时保留撤销手段。
  - `start`、`config check`、`doctor` 先读 `.env`（`ENV_FILE`），再读这个文件，都不覆盖环境里已有的变量。
- **`config init` 和 `config check` 的边界**：`config init` 仍然只生成 bundle 和 profile（`render_bundle`/`create_bundle` 多了可选的 `sections`、`environment`、`make_default` 参数）；`config check` 仍然只读。

### 4. 打包与 CI

- **基础包**（`packaging/linux/base.txt`）：只含 CLI、配置向导和执行安装计划所需的组件。内容为 Python 3.13.12、Host/Agents/Core 的 wheel，以及 16 个第三方分发：
  - annotated-types、antlr4、certifi、filelock、installer、numpy、omegaconf、packaging、pydantic、pydantic-core、python-dotenv、python-slugify、pyyaml、text-unidecode、typing-extensions、typing-inspection。
  - 这个集合是用导入拦截实测 `--help`、`config init`、`config check`、`doctor --list` 得出的，build.sh 每次都在这个集合上冒烟测试。
  - Host/Agents 其余的必选依赖（aiohttp、langchain、weasyprint 等）随任何计划一起安装：catalog 的 `alpha-avatar-host` 闭包包含它们，减去基础包已有的部分。
- **`packaging/linux/catalog.py`**：从 `uv.lock` 出发，按 CPython 3.13 / Linux x86_64 求值 marker，沿依赖图求出 `setup-catalog` 组每个分发、每个 extra 的闭包。每个分发只有一个制品：
  - 第三方取 lock 里 manylinux_2_28 及更老标签中最优的 wheel，带原 URL、SHA-256 和大小；
  - torch 和 torchaudio 用 `torch-cpu.txt`，大小在构建时用 HEAD 请求取得；
  - AlphaAvatar 自己的包和没有 wheel 的源码包由本次构建出 wheel，URL 为空，从本构建旁边或 Release 取得；
  - GUI 版 OpenCV、triton 和 nvidia-* 不进入闭包。
  - 它的 `base` 模式只用标准库，可以在任何东西安装之前运行。
- **`build.sh`** 输出一组平铺的文件，Release 原样附上：
  - 基础包 tarball 和它的 `.sha256`（tarball 里含 manifest 和 catalog）；
  - 本构建的 12 个 wheel：catalog 引用的 10 个插件包和 rtc，加 llama-cpp-python（x86-64-v3）；
  - `install.sh`；
  - `SHA256SUMS`。
  - 构建过程中测量 glibc 下限，并对两个预设做离线规划。
- **`install.sh`**：
  - 只装基础包，不再要求 AVX2；
  - 清理改为按 `current` 的实际指向判断：在切换之后才收到的 SIGTERM 不会删掉刚切换上的版本；
  - 首次安装失败时，不留下 `current`、命令入口和空的前缀目录；
  - 重装同一基础包时保留其上的 setup 环境；
  - 换成另一个基础包后提示需要重新 `setup`；
  - 命令入口属于另一个前缀时，说明是哪一个。
- **`linux-package.yml`**：
  - `build` job 在 manylinux_2_28 里运行 build.sh；
  - `verify` job 在 `ubuntu:24.04` 容器里，用刚上传的同一组文件走用户路径：
    1. 先确认容器里没有 python、node、cc；
    2. 校验 `SHA256SUMS`；
    3. 用 `install.sh --file` 安装；
    4. 在仓库外运行 `--version`、`--help`、`config init`，确认裸 `config check` 会指出缺什么以及 `setup`；
    5. 用 remote 计划核对没有本地模型和加速库；
    6. `setup --preset default --artifacts /srv/alphaavatar`；
    7. `config check` 和并行覆盖；
    8. 最后才装 binutils，测量 glibc 下限并要求不超过 2.28。
  - release.yml 的 `linux_package` 复用它，所以验收不过就不会发布。

### 5. 改动文件

| 文件 | 改动 |
|---|---|
| `pyproject.toml`、`uv.lock` | Ruff `known-third-party`；`setup-catalog` 组取代 `reference-bundle`；`avatar-agent-all` 带上本地 extras；lock 新增 installer 0.7.0（uv 0.10.0，340 个包） |
| `avatar-agents/pyproject.toml`、5 个插件的 `pyproject.toml`、`avatar-host/pyproject.toml` | 第 2 节的 extras；Host 新增 `certifi`、`installer` |
| Agents：`configs/avatar_config.py`、`runtime/inference/runner.py`、`runtime/plugin/{__init__,module}.py`、`utils/vdb/config.py` | `plugin_factories`、`REQUIRES`、`registered`、`plugin_requirement`、`vdb_requirement` |
| 插件：11 个 runner 文件，memory/persona 的 `inference.py`、`storage/vdb/__init__.py` | `REQUIRES`；向量库按后端导入 |
| Host 新增：`configs/capabilities.py`、`configs/credentials.py`、`setup/{__init__,choices,plan,environment,probe}.py`、`cli/commands/setup.py` | 第 2、3 节 |
| Host 修改：`cli/app.py`、`cli/commands/{config,run,doctor}.py`、`configs/{__init__,loader,template}.py`、`doctor/doctor.py` | `setup` 子命令；能力检查和凭据读取接入；`render_bundle`/`create_bundle` 的参数；Doctor 改用共享求解 |
| `packaging/linux/{build.sh,install.sh}`，新增 `base.txt`、`catalog.py` | 第 4 节 |
| `.github/workflows/{linux-package,release}.yml` | 第 1、4 节 |
| `DEPLOY.md` | Linux 一节改为基础包加 `setup` |
| 测试：新增 `tests/setup/{test_choices,test_environment}.py`、`tests/configs/{test_capabilities,test_credentials}.py`、`tests/cli/test_setup.py`；修改 `tests/cli/{test_doctor,test_entrypoint}.py` | 第 6 节 |

### 6. 验证

**本地实测：仓库检查**

- ruff check（`--no-cache`）、ruff format、`check_workspace`（16 个成员）、`uv lock --check`（uv 0.10.0）、`git diff --check`、`bash -n`、三个工作流 YAML 能解析、pre-commit（所有改动和新增文件）：全部通过。
- 全量离线 pytest：**366 passed**。上一轮 330 项，本轮新增 36 项：test_choices 18、test_environment 9、test_credentials 4、test_capabilities 1、test_setup 4。
- 新增测试：
  - **选择对拍**：16 种组合下，`requirements` 与 `resolve_capabilities` 一致，环境里设置了 `QDRANT_URL` 时也一致；两个预设都开视觉，默认 8 个 runner，remote 只有 silero 和两个 lancedb runner；
  - **真实 `uv.lock` 经 catalog 逻辑求计划**：remote 不含 torch、torchaudio、llama-cpp、insightface、transformers、onnx、tokenizers、safetensors、scikit-image、scipy，关语音后连 onnxruntime 也没有；三个计划都没有 nvidia-*、triton、GUI OpenCV，也没有基础包里已有的分发；
  - **计划确定性**：需求顺序和重复不影响计划与 ID；未知 extra、不安全的文件名、错误的格式都会被拒绝；
  - **制品来源**：目录对所有制品都先查；URL 只用于本构建自己的 wheel；
  - **安装事务**：检查发生在切换前、启用发生在切换后；检查失败、启用失败、切换后收到信号、制品损坏、下载中收到信号这五种失败，都不改 `current`，只删除本次创建的东西；锁被占用时拒绝；复用和重建残缺目录；
  - **凭据**：权限 600；引号、反斜杠、`${}` 原样往返；不覆盖已有环境变量；撤销能还原；不安全的值在文件改动之前就被拒绝；
  - **`config check` 按位置报错**：缺 insightface、关掉 face 后通过、未注册的工厂、没有的 entry point；`start` 在准备任何东西之前同样拒绝（子进程测试）；
  - **setup CLI**：在仓库检出里、没有终端也没给预设、修饰参数没配预设时都拒绝；缺凭据或 bundle 重名时什么都不写；`--plan` 输出稳定；安装失败时不写 bundle 和凭据；成功后设为默认、凭据权限 600、输出里不含秘密；新 bundle 保留当前环境的需求，基础包不同时不保留。
- **变异验证 16/16 全部被测试捕获**：face extra 漏声明；忽略 runner 的 REQUIRES；先切换后检查；不回滚 `current`；凭据覆盖环境变量；URL 对每个制品都试；LanceDB 不显式固定；保留 CUDA 库；先写 bundle 后安装；不减去基础包；不检查工厂；凭据权限 644；remote 带本机模型；复用环境时跳过检查；新 bundle 丢掉现有需求；保留另一个基础包的需求。日志在临时目录 `evidence2/mutants-final.log`。

**本地实测：构建**（与上一轮相同的本机、相同的 build.sh，`--allow-dirty --max-glibc 2.32`）

- 基础包 `alphaavatar-0.6.8-124e0125ce26-dirty.20261105132735-linux-x86_64.tar.gz`：**65,796,383 字节（63 MB）**，SHA-256 `fd8744c32267af36884951ef882f87b89807e480812f20dcd3550bac6f45dc8a`。
  - 含 19 个分发：上述 16 个第三方分发、Host/Agents/Core，以及 python-build-standalone 自带的 pip；
  - 安装后 209 MB，glibc 下限 **2.17**。
- 本构建的 wheel 共 12 个：10 个插件包（含 deepresearch、mcp）、rtc 和 llama，约 18.6 MB；默认计划用到其中 10 个。本构建 wheel 的 glibc 下限是 **2.32**：只有本机编译的 llama 库超过 2.28，CI 在 manylinux_2_28 里构建，预期为 2.28，待推送后核实。
- 构建用时约 67 秒，因为 llama 的编译结果有 uv 缓存；上一轮没有缓存时约 3 分钟。

| 计划（对新装的基础包） | 包数 | 下载量 | 其中本构建 | 最大的制品（MB） | glibc 下限（计划声明） | CPU |
|---|---|---|---|---|---|---|
| `default` | 134 | **532 MB** | 10 个，18.6 MB | torch 184、opencv-headless 54、pyarrow 48、lancedb 47、scipy 36、llama 18、onnx 18、onnxruntime 17 | 2.32（本机 llama） | avx2、bmi2、f16c、fma |
| `remote` | 115 | **237 MB** | 9 个，0.6 MB | opencv-headless 54、pyarrow 48、lancedb 47、onnxruntime 17、livekit 11 | 2.28 | 无 |

**本地实测：干净机器验收**

环境：bubblewrap，Ubuntu 24.04.5 根文件系统（glibc 2.39，没有 python、node 和编译器），普通用户 tester。基础包和本构建的 wheel 由本机 HTTP 服务提供，模拟 Release；第三方 wheel 直接从 PyPI 和 download-r2.pytorch.org 下载，即真实的用户路径。三组都在全新的根文件系统上，用最终构建运行。

默认路径：

| 步骤 | 结果 |
|---|---|
| `curl` 下载 `install.sh`，`bash install.sh --url …` | 0，3 秒；`current -> versions/<id>`；提示下一步 `alphaavatar setup` |
| 在 `/` 运行 `--version`、`--help` | 0，子命令为 `dev, start, config, setup, doctor` |
| `config init reference`、裸 `config check` | 0 / 2。检查逐行列出 9 个配置位置对应的插件包，并提示 `` `alphaavatar setup` installs them `` |
| `setup --preset default --artifacts <本机服务>`（凭据为占位值，来自环境） | 0，55 秒：下载 134 个包、532 MB，向本机服务只请求本构建的 10 个 wheel，没有 404；建环境、probe、`config check`，然后切换并启用 |
| `config check`（默认 bundle 为 `avatar`）、`config check reference` | 都是 0；视觉开启（vlm），8 个 runner |
| 覆盖 `runtime.inference.methods={"alphaavatar.voice.vad.silero": {"workers": 2}}` | `8 runners (workers: alphaavatar.voice.vad.silero x2)` |
| 覆盖一个未被选中的方法 | 被拒绝：`fields: runtime.inference.methods.alphaavatar.router.unknown` |
| 安装结果 | `credentials.env` 权限 600；默认 bundle 为 `avatar`；环境 1.8 GB，含 134 个分发；实测 glibc 下限 2.32，不计本机编译的 llama 库为 2.28 |

已安装后的失败场景。每一步后都核对：`current`、命令入口、`--version`、`config check`，以及应用主目录全部文件的哈希（预先放了一个工作区数据文件作为替身）：

| 场景 | 退出码 | 结果 |
|---|---|---|
| `setup --preset remote` 第 3 秒 SIGTERM。remote 在默认环境之内，计划复用它，信号落在重新检查期间 | 143 | 状态和数据哈希都不变，没有新环境和临时目录，「nothing was enabled」 |
| `install.sh` 下载被截断（服务只发 5 MB） | 18 | 不变 |
| 重装同一基础包 | 0 | 「already installed」，`current` 仍指向 setup 环境 |
| 安装 B：在替换 `current` 的 `mv` 之前发 SIGTERM（用 PATH 中的替身 `mv` 精确卡点） | 143 | 不变，B 已删除 |
| 安装 B：`mv` 完成后立即 SIGTERM | 143 | `current -> versions/B`，B 完整保留并可运行；A、setup 环境和数据都在，数据哈希不变。由于 B 是裸基础包，`config check` 返回 2，并指出缺什么 |
| 第二个前缀共用同一个 `bin-dir` | 1 | 下载前即拒绝：「…/bin/alphaavatar runs the AlphaAvatar installed in …/.local/lib/alphaavatar」；第二个前缀目录不存在 |
| `setup --preset remote` 完整运行 | 0 | 提示保留当前环境的 4 项本机模型需求，「installed already: nothing to download」；`remote` 成为默认 bundle（3 个 runner，视觉开启），原 `avatar` bundle 仍然通过检查 |

首次安装失败，以及只装了基础包时的 setup 失败：

| 场景 | 退出码 | 结果 |
|---|---|---|
| `--sha256` 不匹配 | 1 | 前缀、`bin`、home 都为空 |
| 要求 glibc 9.99 的包 | 1 | 「Needs glibc 9.99 or newer; found 2.39」，同上为空 |
| 命令目录不可写 | 1 | 下载前即拒绝，同上为空 |
| 下载或解包时 SIGTERM | 143 | 同上为空 |
| 首次安装成功后，首次 `setup` 拿不到本构建的 wheel | 1 | 「Cannot get alpha_avatar_plugins_context…: URLError」；`current` 仍是基础包，没有 `envs`，没有 home |
| 首次 `setup` 缺凭据 | 1 | 列出缺少的 4 个名字，没有任何改动 |
| 首次 `setup` 在第 3、10、18、24 秒被 SIGTERM | 143 ×4 | 分别停在下载第 51、73、99 个包，以及第 24 秒的「下载完、正在安装或检查」；每次都没有 `envs`，没有 home，`current` 仍是基础包 |
| 首次 `setup` 第 6 秒 Ctrl-C | 130 | 停在下载第 61 个包，同上 |
| 首次 `setup --preset remote` 完整运行 | 0 | 26 秒，115 个包、237 MB；环境 733 MB，第 2 节列出的重型库中只有 onnxruntime；`config check` 通过，3 个 runner，视觉开启 |

**推送后待 CI 验证**

本机无法推送，CI 只会在推送后用同一提交的制品运行：
- linux-package.yml 的 `build` 能否在 manylinux_2_28 里跑通（含 `dnf install unzip`），本构建 wheel 的 glibc 下限是否 ≤ 2.28；
- `verify` 在 `ubuntu:24.04` 容器（没有 python、node、cc，也没有系统 CA 证书，HTTPS 走 certifi）里的全部步骤，以及 CI 里实测的基础包大小、默认方案额外下载量和 glibc 下限；
- release.yml 的草稿发布流程。

本地的制品由同一个 build.sh 构建，但标记为 dirty，且编译用的是本机 glibc 2.32，所以不能代替 CI 结果。

### 7. 过程中的问题与更正

1. **Ruff 在本地没报错**：被 `.ruff_cache` 掩盖，见第 1 节。此后 Ruff 一律加 `--no-cache` 运行。
2. **Ctrl-C 测试第一次无效**：非交互 shell 的后台任务会忽略 SIGINT，setup 因此没被打断，装完了 remote 计划（顺带验证了远端方案的实装：733 MB，只有 onnxruntime）。改用 `perl -e '$SIG{INT}="DEFAULT"; exec …'` 恢复默认处置后，再测得退出码 130。
3. **新增 bundle 会让旧 bundle 失效**：用 remote 新增 bundle 后，`current` 切到只含远端依赖的新环境，原默认 bundle 的 `config check` 返回 2，正确指出缺 torchaudio、insightface、llama-cpp-python、transformers。这是设计问题，不是检查的问题。已改为新计划保留当前环境的需求（第 3 节），并加了测试和变异 M15、M16。
4. **`--artifacts URL` 对每个第三方制品都先请求本机服务**：产生 124 次 404。改为 URL 只用于本构建自己的 wheel，目录则对所有制品都先查。
5. **连接失败时错误信息多出一行「not the planned file」**：现在只有确实收到了内容才报这一行。
6. **残留与提示**：
   - 首次 setup 失败会留下空的 `envs/`，首次安装失败会留下空的前缀目录和锁文件：都已改为只删除本次创建、而且为空的目录；
   - 「能力属于旧版本」的提示原来在切换前打印，切换前被打断时也会出现：已挪到切换成功之后；
   - 复用已有环境时摘要仍写「532 MB to download」：已改为「installed already: nothing to download」，这时也跳过磁盘空间检查。
7. **本机构建默认 `--max-glibc 2.28` 时失败**：本机编译的 llama 需要 2.32，这正是该检查应有的行为。本地构建改用 `--max-glibc 2.32`，CI 仍是 2.28。
8. **一次清理命令被安全检查拦下**：命令先 `cd` 再对 `*` 执行 `rm -f`，没有执行。改为对绝对路径用 `find -delete`。
9. **磁盘一度只剩 981 MB**：沙箱里同时有默认环境和远端环境。之后每组验收结束就删除对应的根文件系统，构建产物只保留最终一份。

### 8. 环境限制

- CI 没有运行（见第 6 节「推送后待 CI 验证」）。
- 测试环境是 bubblewrap 沙箱，不是虚拟机，与主机共享内核 5.10 和网络；基础包从本机 HTTP 服务下载。
- B（切换用）和 C（要求 glibc 9.99）是从最终基础包派生的测试包，只改了顶层目录名和 manifest 里的 id、glibc。
- 磁盘约 1–5 GB 可用；用户的 `~/.cache/uv` 没有清理，只被构建读取。
- 没有实测：glibc 2.28 的系统、不支持 AVX2 的 CPU、真实凭据下的 RTC 会话和模型下载（属于第 3、4 项）。

### 9. 待复核

1. **CI 首次运行**：见第 6 节。另外，开发分支每次推送都构建，并在 GitHub 上做一次约 530 MB 的 PyPI 下载和安装。如果频率太高，可以改为按路径过滤或手动触发。
2. **基础包只装 Host 依赖的子集**：
   - Host、Agents、Core 以 `--no-deps` 加 `base.txt` 安装，其余依赖随计划补齐；
   - 所以在裸基础包里，Doctor 的 `packages.alphaavatar` 会报告 Host 依赖未装齐。这如实反映了现状，但它给出的处理建议是「装入当前环境」，而不是 `setup`；
   - Agents 的重依赖（langchain-community、weasyprint、mcp 等）本身是否该移到用到它们的插件里，仍待定（上一轮第 8 节第 5 条）。
3. **每个新计划都会重新下载全部制品**：环境之间不共享 wheel 缓存。旧环境和旧版本不会被清理；换基础包后需要重新 `setup`。这些属于第 5 项（升级与回退）。
4. **setup 只增不减**：新计划保留当前环境的需求。想精简，需要第 5 项的清理能力。
5. **remote 仍含 onnxruntime**：原因见第 3 节。如果语音分段将来能来自远端（例如服务端 VAD），remote 就可以去掉它。
6. **凭据**：
   - 保存为明文，靠 600 权限保护；
   - `--preset` 会把环境里给的凭据写入该文件，CI 里写的是占位值；
   - `ENV_FILE` 仍然存在，去掉它属于第 2 项。
7. **`config init` 的「Next」提示**：在裸基础包里仍然建议 `alphaavatar dev`，没有提示 `setup`。
8. **catalog 不含 rag 和 character**：它们依赖太重；`config check` 会照常指出缺包，但 `setup` 装不了它们。
9. **llama 的 `lib64/` 重复**（上一轮第 6 条）仍然存在。x86-64-v3 现在只是 semantic addressing 的要求：基础包不再要求 AVX2，含 llama 的计划会在下载前检查 CPU 标志。
10. **上一轮仍待定的事项**：
    - SIGKILL 留下的 `.install-*`，以及 setup 留下的 `.setup-*`（同一计划的残缺环境目录会在持锁时重建，其他残留仍不清理）；
    - Doctor 写死的内置插件知识；
    - loop/context 按名字查找；
    - 开发环境中 OpenCV 两个版本并存；
    - `.gitignore` 的 `KMS` 行。

### 10. 追加：Agents 依赖归位与 Doctor 提示（用户对第 9 节第 2 条的决定）

用户决定：
- 只装了基础包时，Doctor 的处理建议改为提示 `alphaavatar setup`；
- Agents 的重依赖移到真正用到它们的插件里。

**依赖归位**：先逐个盘点 Agents 声明的依赖在全仓库的实际导入情况。

| 依赖 | 实际用处 | 处理 |
|---|---|---|
| weasyprint、markdown、requests | 只被 `agents/utils/files/url_to_pdf.py` 用到，而这个模块只被 deepresearch 调用 | 模块原样（`mv`）移到 `alphaavatar/plugins/deepresearch/url_to_pdf.py`，三个依赖改由 deepresearch 声明；`tavily.py` 仍在保存时才导入 |
| mcp | 只有 mcp 插件用，它已声明 `mcp>=1.24` | 从 Agents 移除 |
| langchain-core | 只有 provider 的 `langchain` extra 用，它已声明 | 从 Agents 移除 |
| langchain-community、livekit-blingfire | 全仓库没有任何代码导入 | 移除 |
| omegaconf | 只有 Host 用，Host 已声明 | 从 Agents 移除 |
| numpy | Agents 自己在模块层导入（`utils/__init__` → `numpy_utils`，以及 `persona/schemas/user_profile`），过去是靠 langchain-community 间接带进来的 | Agents 显式声明 `numpy>=1.26,<3` |
| huggingface-hub、filelock、jsonschema、referencing、python-slugify、python-dotenv | Agents 自己的代码在用 | 保留 |

- 锁文件（uv 0.10.0）从 340 个包降到 332 个，移除的是 langchain-community、langchain-classic、langchain-text-splitters、sqlalchemy、marshmallow、dataclasses-json、typing-inspect、livekit-blingfire。
- 开发环境用 `uv sync --inexact` 同步，没有删除 `.venv` 里不再被锁定的包；全量测试在拦截这些模块导入的情况下运行（见下）。
- `docs/cli/doctor.md` 里「导入配置时 WeasyPrint 会探测 native 库」那句已失效，删掉了。
- `agents/utils/files/__init__.py` 的说明也同步更新。

**新增回归**：`avatar-agents/tests/test_dependencies.py` 用 AST 收集 Agents 代码里的第三方导入，要求：
- 模块层导入的都在必选依赖里；
- 函数内导入的在必选依赖或 extras 里（`gpu_available()` 对 torch 的探测除外）；
- 声明的依赖都被 Agents 自己的代码用到。

**Doctor 提示**：`packages.alphaavatar` 和 `packages.capabilities` 的处理建议由 `_install()` 生成：在安装包里（`Installation.running()` 成立）为「Run `alphaavatar setup`; it installs …」，在源码检出或其他 Python 环境里仍是「Install into this Python environment: …」。`test_doctor` 两种情形都断言了。

**验证（本地实测）**

- 全量 pytest 在拦截上述 8 个分发的导入时运行：**367 passed**（新增 Agents 依赖测试 1 项）。
- 变异验证 **19/19 全部被捕获**，在第 6 节 16 个的基础上新增 3 个：Agents 不声明 numpy；Agents 重新声明 weasyprint；Doctor 不再提示 setup。
- 重新构建：基础包 65,790,796 字节，SHA-256 `354d040a4533325fdd0f5c39ab4c94560bafdbc85e5d22ccb1d3308e7c665a89`，glibc 2.17，内容与 `base.txt` 相同。

| 计划（对新装的基础包） | 改前 | 改后 |
|---|---|---|
| `default` | 134 个包、532 MB | **105 个包、514 MB**（本构建的 wheel 10 个、18.6 MB）；环境 1.8 GB → **1.7 GB**，含 105 个分发 |
| `remote` | 115 个包、237 MB | **85 个包、212 MB**；环境 733 MB → **635 MB**，本地推理库只有 onnxruntime |

- 三组沙箱验收在新构建、全新根文件系统上重跑，结论与第 6 节相同：
  - 默认路径：`setup` 用时 53 秒；`config check` 通过，视觉开启，8 个 runner，`silero x2` 并行覆盖生效；环境里已经没有 langchain-community、sqlalchemy、weasyprint、mcp；glibc 下限实测 2.32（不计本机编译的 llama 为 2.28）。
  - 安装后的失败场景：`current`、命令入口和数据哈希逐项不变。
  - 首次安装失败：前缀、`bin`、home 都为空。
  - 首次 setup：在第 3、10、16 秒（下载中）和第 20 秒（安装中）被 SIGTERM，第 6 秒 Ctrl-C，都没有留下 `envs` 和 home；完整运行 remote 用时 23 秒。
  - 新增一步：在只装了基础包的机器上跑 `doctor --json`，`packages.alphaavatar` 为 FAIL，处理建议是「Run `alphaavatar setup`; it installs 'alpha-avatar-host'」。
- 计时上的一处更正：remote 变小后，原来第 24 秒的 SIGTERM 到达前 setup 已经装完（退出码 0），后两步因此撞上「bundle 已存在」。打断时间点改为 3、10、16、20 秒后，这一组重跑。
- CI 部分仍待推送后验证，同第 6 节。

### 11. 追加：Linux 制品的 CI 触发范围（用户决定第 9 节第 1 条）

用户决定：
- dev 分支按路径自动触发；
- 保留手动补跑；
- 正式发布始终跑完整验收；
- 触发路径要比 `packaging/**` 宽，覆盖打包与发布工作流、`uv.lock`、Python 版本与依赖声明、`setup` 和 catalog、默认 bundle／profiles、安装验收，以及实际装入制品的运行时代码。

| 场景 | CI 行为 |
|---|---|
| 推送到 `dev/**`，改动命中触发路径 | `linux-package.yml` 构建基础包和 wheel，再在 `ubuntu:24.04` 干净容器里用同一提交的制品走完安装、`setup` 和 `config check` |
| 只改文档、开发日志、测试、Quality 工作流或 `scripts/quality` | 不构建 Linux 制品；Quality 照常运行 |
| 正式 tag | release.yml 通过 `workflow_call` 调用，路径过滤对它不生效，总是完整构建并验收；通过后才以草稿上传资产并发布 |
| 手动补跑 | 保留 `workflow_dispatch`。GitHub 要求该工作流文件已在默认分支上，所以在合入 main 之前，dev 分支只能靠推送触发 |

`push.paths` 的触发路径，以及各自覆盖的内容：

| 路径 | 覆盖 |
|---|---|
| `.github/workflows/linux-package.yml`、`.github/workflows/release.yml` | 打包、验收和发布流程本身 |
| `.python-version`、`uv.lock`、`pyproject.toml` | Python 版本、锁文件、根依赖组（含 `setup-catalog`） |
| `packaging/**` | `build.sh`、`install.sh`、`catalog.py`、`base.txt`、`torch-cpu.txt` |
| `avatar-*/pyproject.toml`、`avatar-plugins/*/*/pyproject.toml` | 每个包的依赖声明和 extras |
| `avatar-*/alphaavatar/**`、`avatar-plugins/*/*/alphaavatar/**` | 装入制品的全部代码，包括 `setup`、能力求解、默认 bundle 模板和 Doctor 样例 |

- 插件代码按目录模式整体纳入。不进 catalog 的 rag、character 改动也会触发一次构建；宁可多构建，也不漏。
- 举例：把 PDF 依赖从 Agents 移到 DeepResearch，改动的是 `avatar-agents/pyproject.toml` 和插件代码，安装脚本没动，但仍会触发构建。
- **防止以后漏掉**：`scripts/quality/check_workspace.py`（Quality 的 lint job 会运行）从工作流里读出这些路径，要求以下内容都被覆盖：每个 workspace 成员的 `pyproject.toml` 和 `alphaavatar/` 代码、`uv.lock`、`.python-version`、根 `pyproject.toml`、`packaging/` 下的每个文件，以及这两个工作流。
- **验证（本地实测）**：
  - 依次删掉 10 条路径中的任意一条，或者删掉整段 `paths`，检查都会失败，并指出哪些路径不再触发构建（11/11）；
  - 只改日志、DEPLOY.md、README、测试、`quality.yml` 或 `scripts/quality` 时，按同样的匹配规则判断为不触发；改 `url_to_pdf.py`、`avatar-agents/pyproject.toml`、模板、`setup`、`catalog.py` 时会触发；
  - Ruff、格式、`check_workspace`、`uv lock --check`、pre-commit 都通过。
- **推送后重点核对**：本次推送改动了 `linux-package.yml` 本身，所以一定会触发。要看的是：
  - manylinux_2_28 能否构建成功；
  - 实际的 glibc 下限是否 ≤ 2.28；
  - 干净容器里的整套验收能否通过。
  - 草稿发布流程要等第一次打正式 tag 时才会运行。

### 12. 追加：合并到 `main` 也按同一套路径规则触发（用户决定）

用户决定：`push.branches` 设为 `["main", "dev/**"]`。上一节只写了 `dev/**`，合并到 `main` 本身不会触发 Linux 打包验收。

| 场景 | CI 行为 |
|---|---|
| 合并到 `main`，改动命中第 11 节的路径 | 用 `main` 上合并后的 SHA 构建，并在干净容器里验收。即使 dev 已经通过，这次验的是实际进入 `main` 的代码；只产出 CI 制品，不发布 |
| 只合并文档或日志 | 跳过 Linux 制品，照常跑 Quality |
| 正式 tag | 不变：完整构建、验收，通过后经草稿发布 |
| 手动补跑 | 工作流进入默认分支 `main` 之后，`workflow_dispatch` 可用 |

- **并发**：dev 分支上，新推送仍会取消正在跑的旧构建；`main` 上不取消，每个合并进来的 SHA 都跑完并留下结果；发版本来就不取消。对应设置为 `cancel-in-progress: ${{ inputs.release == '' && github.ref != 'refs/heads/main' }}`。
- **防误改**：`check_workspace.py` 要求推送分支同时包含 `main` 和 `dev/**`。本地实测：去掉其中任一个，检查都会失败（2/2）。
- DEPLOY.md 同步改为「`main` 和 `dev/**` 上每次改动了制品内容的推送」。

Doctor 运行指标、启动与停止、升级失败回退，按原顺序在本项审查通过后进行。

## 第 1 项第三轮（基线 `7c67240`）

依据：Codex 对 `7c67240` 的审查和用户的三项要求。远端 CI（Linux package run 42042146953）已跑通默认方案的安装和 `config check`，只在 glibc 扫描一步失败；Quality（run 42042146666）在单独 Host wheel 读 Doctor 样例和短句 TTS 测试两处失败。所有改动在未暂存的工作区。

### 1. 统一插件发现

**规则**：每个插件选择都按「能力类型 + 实现名」解析。`voice.stt.plugin: openai_segment` 就是 `("voice.stt", "openai_segment")`。已安装的包在 entry point 组 `alphaavatar.<类型>` 里用实现名声明它，值指向该实现现有的 factory 类（`AvatarModulePlugin` 子类）。内置插件也一样，在各自 `pyproject.toml` 里声明；原先为发现实现而写死的 `import_module("alphaavatar.plugins.<包>")` 全部删除。

| 能力类型（`AvatarModule` 的值） | 配置字段 | 内置实现 |
|---|---|---|
| `loop`、`context` | `loop.plugin`、`context.plugin` | `realtime`、`default` |
| `provider.llm`、`provider.embedding` | 各插件设置里 `ProviderTaskConfig.backend` | `openai`、`langchain`；`langchain` |
| `voice.vad`、`voice.stt`、`voice.tts` | `voice.*.plugin` | `silero`；`openai_realtime`、`openai_segment`；`openai`、`voiceai` |
| `router`、`status`、`memory`、`persona`、`character` | `*.plugin` | `default`；`airi` |
| `tools.deepresearch`、`tools.rag`、`tools.mcp` | `tools.*.plugin`（MCP 还看 `enabled`） | `default` |

**接口**（Agents `runtime/plugin/resolution.py`，新增；数据类 `ResolvedPlugin`、`PluginSelection` 在 `runtime/plugin/schemas/`）：

- `resolve_plugin(类型, 名字)`：找唯一的 entry point，加载 factory 类并实例化，每个进程只加载一次。没有、多个包重名、加载失败或不是 `AvatarModulePlugin` 子类，都抛 `PluginError`；重名时列出各个包名，加载失败时带上声明它的包。
- `resolve_plugins(配置, providers=...)`：先按 `AvatarConfig.plugin_factories()` 解析每个被选中的插件，再由这些插件的 factory 给出它们用的 runner（`inference_runners`），然后才规划 worker。带 `providers` 时，还会用插件自己的 schema（`settings`）校验 `init_config`，错误定位到 `loop.init_config.model` 这样的字段；再解析设置里每个 `ProviderTaskConfig` 的后端，以及 runner 声明的 Provider（`InferenceRunner.PROVIDERS`，向量库 runner 声明默认后端的 embedding）。未关闭的部分才算选中：`voice.vad.plugin: null`、`tools.mcp.enabled: false` 不会被解析。
- factory 上新增两个可选方法：`settings(init_config)` 和 `inference_runners(config)`。原来各包 import 时注册的 runner 引导函数（`register_inference_runner_bootstrap`）和全局注册表删除，runner 逻辑原样挪到 factory 方法里，去掉了 `if plugin != "default"` 这类按名字的门控。
- `ResolvedPlugin.namespace` 由 factory 所在包得出（`alphaavatar.plugins.memory` → `memory`），runner 设置快照和 Doctor 的存储隔离都改用它，不再用写死的包名表 `plugin_packages()`（已删除）。
- `voice.*.plugin` 由 `Literal[...]` 改为字符串，其他包的实现也能被选中。

**共用**：`config check`、Doctor 和 `start` 都经同一条路径：加载配置时解析插件并规划 runner；`validate_plugin_settings` 和 `resolve_capabilities` 再带上 Provider。缺失、重名、加载失败和依赖不足都定位到选中它的字段。在安装包里，缺失的实现会注明 `setup` 能否安装（见第 3 节）。会话子进程恢复配置时同样先解析和加载选中的插件；Provider 模型在插件初始化（`validate_tasks`）时创建，都在实时会话开始前。移动端以后可以换掉 `resolve_plugin` 背后的发现来源（例如 App 构建清单），接口不变；这一轮只实现了 Python entry point 这一种来源。


### 2. 安装与激活事务

- **current、默认 bundle 和凭据一致**：切换 `current` 和启用（写凭据、写 bundle、替换 `settings.yaml`）合成一步：期间收到的 SIGINT／SIGTERM／SIGHUP 先记下，这一步结束后再按原处理方式生效。最初用 `pthread_sigmask` 实现，测试证明不够：进程里只要有别的线程，信号就会投递到那个线程，Python 仍在主线程执行处理函数。现在改为在 Python 层临时换成「记录」处理函数，与线程无关。`settings.yaml` 替换是提交点；替换之后若出现非信号错误，按已启用处理，不再撤回凭据和 `current`。
- **命令入口原子、禁止覆盖**：install.sh 改用 `ln -sT`（不带 `-f`），只有该位置为空时才创建，原先的「临时链接再 `mv -Tf`」会覆盖别人刚建的入口。创建前先记下「入口是本次的」，信号恰好落在链接刚出现时也能清理；清理只删仍指向本前缀的入口。
- **归属不明的路径不碰**：
  - setup 和 install.sh 都要求 `current` 是指向本前缀 `versions/` 或 `envs/` 的链接，否则拒绝并原样保留；
  - setup 建的目录（暂存区、环境）都带 `.alphaavatar-setup` 标记，环境目录先在暂存区建好标记再改名到位；同一计划的残留目录只有带标记且不被 `current` 引用时才重建，否则拒绝；
  - 被强杀留下的暂存区（setup 的 `envs/.setup-*`、install.sh 的 `versions/.install-*`，后者标记为 `.alphaavatar-install`）在下次持锁时清理，没有标记的不动。
- **锁内复核**：取得安装锁后重读 `current` 的基础版本和当前环境的依赖。基础版本变了就拒绝；当前环境多出计划里没有的依赖（另一个 setup 在本次规划之后完成），就把它们并入重新规划。依赖仍然只增不减。
- **本地 `--artifacts`**：先复制到本次独占的暂存区再校验，安装的就是校验过的那份；URL 下载本来就落在暂存区。

### 3. 向导和 CI

- **凭据**：`--preset` 只从环境读取，不再写 `credentials.env`，结束时提示 start 从环境或 `.env` 读取哪些变量。交互模式下先问是否保存（默认否）；已保存的同名变量值不同时再单独确认是否替换（默认否），不替换就保留原值并说明。`ENV_FILE` 的移除留在第 2 项。
- **自托管端点**：交互模式「逐项选择」里可以把模型和语音分别指向自己的 OpenAI 兼容服务：
  - 模型：对话模型走 `openai` 后端（Responses API，loop 需要流式），记忆和画像任务、embedding 走 `langchain` 的 OpenAI 实现，三者都写 `extra.base_url`；
  - 语音：`voice.stt.base_url`／`model`、`voice.tts.base_url`／`model`／`speaker`；
  - 远端语音保留本机 Silero VAD，依赖集合与选 OpenAI 时相同。
- **如实提示 setup 能装什么**：catalog 新增 `plugins` 表（类型 → 实现名 → 安装它的需求），由构建出的 wheel 的 entry point 生成。安装包里缺某个实现时，`config check` 和 Doctor 会在该行注明「`alphaavatar setup` installs it (…)」或「this release's `alphaavatar setup` does not offer it」；源码检出里不提 setup。RAG、Character 仍不进 catalog。
- **基础包上的 `config init`**：下一步提示改为 `alphaavatar setup`，说明它会另建一个带所选能力的 bundle，刚生成的这个保持原样。
- **glibc 扫描**：CI 原先把 `bin/` 里的 shell 启动器也交给 `objdump`，xargs 退出 123。新增 `packaging/linux/glibc-floor.sh`：按 ELF 魔数挑文件，objdump 读不了真正的 ELF 时仍然失败；build.sh 和 CI 共用，build.sh 原来的 `|| true` 吞错也随之去掉。
- **Doctor 顶层导入**：`doctor.py` 从 `configs.capabilities` 导入 `HOST`，连带导入 Agents，单独安装 Host wheel 时读样例失败。分发名改放 `host/version.py`。
- **CI**：
  - `main` 上每个提交独占一个并发组，互不排队也不互相取代；`dev/**` 仍是新推送取消旧构建；
  - 两处 `upload-artifact` 加 `overwrite: true`，整轮重跑不再因同名制品失败；
  - 发布前从草稿重新下载全部附件，核对 `SHA256SUMS` 与本次构建一致、逐个校验通过、归档与其 `.sha256` 一致；已公开的 Release 仍一个文件都不改；
  - 干净容器验收新增：基础包上的 `config init` 提示、`config check` 的 setup 提示和 RAG 行；glibc 扫描改用新脚本，并要求结果非空。

### 4. 短句 TTS 的 `FINISHED`／`PROGRESS` 失败（单独复现，未修）

- **现象**：router 插件的 `test_back_to_back_short_sentences_keep_pcm_and_final_alignment_exact` 期望最后一条播放回执是 `FINISHED`，实际是 `PROGRESS`。Quality 在 `9f86a6a`（run 41994655368）和 `7c67240`（run 42042146666）都因它失败，断言相同。
- **原因**：测试里的假播放器 `Player._receipt` 先 `await output.publish(FINISHED)`，返回后才把回执追加到 `receipts`。发布 `FINISHED` 本身就会让字幕定稿，测试等到 `transcript_finalized` 醒来时，追加可能还没执行，读到的 `receipts[-1]` 仍是上一条 `PROGRESS`。这是测试替身的时序问题，不涉及产品代码。
- **确定性复现**：pytest 插件 `widen_receipt.py` 只把 `FINISHED` 回执的追加推迟 20 ms，其余不变。当前工作区和 `9f86a6a` 的源码都必然失败，断言与 CI 相同。`9f86a6a` 与当前的合成、输出链路代码相同（`avatar-core/.../output` 和 router 合成处理器没有差异）。
- **自然复现（16 核全部占满）**：

| 运行 | 失败／次数 |
|---|---|
| 当前工作区 | 36／60，26／30 |
| 交替运行：当前工作区 对 `9f86a6a` | 19／25 对 3／25 |
| 交替运行：当前工作区 对 `7c67240` | 13／15 对 11／15 |

  空载下这一轮 4 次全量测试都通过。当前工作区与 `7c67240` 接近，说明本轮改动没有影响；频率在 `9f86a6a` 到 `7c67240` 之间升高，pytest 配置和这条链路的代码都没变，原因没有查明。
- **未修**：按要求只复现和记录。修法是一行：在测试替身里先追加回执再发布。见第 8 节第 1 条。

### 5. 改动文件

| 文件 | 改动 |
|---|---|
| `avatar-agents/.../runtime/plugin/resolution.py`、`schemas/`（`resolved_plugin.py`、`plugin_selection.py`） | 新增：`resolve_plugin`、`resolve_plugins`、`PluginError`、`UnavailablePlugins`；数据类 `ResolvedPlugin`、`PluginSelection` 放在 `schemas/`，`check()` 在调用时才导入 `UnavailablePlugins`，因为 `resolution` 导入 `schemas` |
| `avatar-agents/.../runtime/plugin/module.py`、`__init__.py` | `AvatarModule` 的值改为能力类型，加 `group`；去掉全局注册表，`create` 经解析；factory 加 `settings`、`inference_runners` |
| `avatar-agents/.../runtime/inference/bootstrap.py`、`__init__.py`、`runner.py` | 删除 runner 引导注册；`plan_inference_runners` 先解析再规划；快照按 namespace；`InferenceRunner.PROVIDERS` |
| `avatar-agents/.../configs/avatar_config.py`、`configs/plugins/**` | 删除 `plugin_packages()`；各配置段去掉写死的包导入和 `_load_*`；voice 实现名改为字符串 |
| `avatar-agents/.../avatar/provider/factory.py`、`utils/vdb/config.py` | Provider 经解析创建；`vdb_embeddings()` |
| `avatar-agents/.../configs/plugins/foundation/provider_config.py`（由 `avatar/provider/schemas/task_config.py` 改名移来）、`configs/__init__.py` | Provider 的配置模型（`ProviderTaskConfig`、`ProvidersConfig`、`ProviderTraceConfig`、`DEFAULT_BACKEND`）归入 foundation 配置段，31 个导入改到新路径，`provider.schemas` 不再导出它们；`configs` 包改为按需导出 `AvatarConfig`，否则 Provider 模块导入新路径时会经 `AvatarConfig` 绕回 runtime，形成循环导入 |
| `avatar-agents/.../runtime/runtime.py` | `AvatarRuntime.foundation` 归入 agent-level 分组；dataclass 加 `kw_only=True`，带默认值的字段才能排在必填的 `inference` 之前（所有构造本来就用关键字） |
| 12 个插件的 `pyproject.toml` 和包 `__init__`／factory | 声明 `alphaavatar.<类型>` entry point；删除 import 时注册；runner 和设置校验挂到 factory；voice 的 `inference.py` 删除；向量库 runner 声明 `PROVIDERS` |
| `avatar-host/.../configs/capabilities.py`、`loader.py` | 基于 `resolve_plugins` 的能力检查；`MissingCapabilities`、`offered()`、`unavailable()`；`validate_plugin_settings` 改由插件 schema |
| `avatar-host/.../doctor/doctor.py`、`session.py`、`host/version.py` | 分发名移到 `version.py`；去掉「未验证的 Provider」；外部服务和存储隔离改用解析结果；缺插件时的操作提示 |
| `avatar-host/.../setup/environment.py`、`choices.py`、`cli/commands/setup.py`、`config.py` | 第 2、3 节的事务、凭据、自托管端点、`config init` 提示 |
| `packaging/linux/install.sh`、`build.sh`、`catalog.py`、`glibc-floor.sh`（新增） | 入口、归属、暂存区清理；共用 glibc 扫描；catalog 的 `plugins` 表 |
| `.github/workflows/linux-package.yml`、`release.yml` | 第 3 节 CI |
| `avatar-plugins/README.md`、`DEPLOY.md` | 插件解析规则；setup 的凭据和自托管说明 |
| 测试 | 新增 `avatar-host/tests/configs/test_discovery.py`；改 `test_capabilities`、`test_setup`、`test_environment`、`test_choices`、`test_entrypoint`、`test_doctor`、Doctor 替身与会话／隔离测试、`test_host_lifecycle`、Agents `test_launch`；10 个 Host 测试把收集期导入改为 `alphaavatar.plugins.persona.factory`（包 `__init__` 不再导入 factory） |

### 6. 验证

**本地实测**

- 最终工作区上：Ruff（`--no-cache`）、格式、`check_workspace.py`（16 个成员）、`uv lock --check`（332 个包）、`git diff --check`、`bash -n`、工作流 YAML、pre-commit（120 个改动和新增文件）全部通过。
- 全量测试 377 项通过；拦截被移除的包后再跑一遍，也是 377 项通过（最终工作区上两种都重跑过）。
- `provider_config.py` 移动后：全量测试 377 项通过；Agents 和插件的 492 个模块各自在全新进程里导入都通过。把 `configs/__init__.py` 改回直接导入 `AvatarConfig`，`test_entrypoint` 在全新进程的 `start` 里因循环导入失败，说明按需导出是必需的，而且已有测试覆盖。
- 数据类移到 `runtime/plugin/schemas/` 后：全量测试 377 项通过，495 个模块各自导入都通过；把 `check()` 里的延迟导入改成一个不存在的名字，Host 的配置与 `config check` 测试有 29 项失败，说明这条路径有测试覆盖。
- `AvatarRuntime` 改为 `kw_only` 后：全量测试 377 项通过。
- 变异：本轮 19 个全部被抓到（插件解析 9 个，事务与凭据 10 个），上一轮的「runner 依赖没算进需求」在新代码上重做也被抓到；install.sh 的两个变异（`ln -sfT` 覆盖入口、入口创建后才标记）在宿主机的竞争和中断检查里都被抓到。
- Doctor 样例（复现 Quality 的「只装 Host wheel」步骤）：修复前退出 1，`No module named 'alphaavatar.agents'`；修复后退出 0。
- glibc 扫描：旧写法对 `.venv/bin` 退出 123；新脚本给出 2.28；对伪造的坏 ELF 仍退出 123。
- 本机构建（`--max-glibc 2.32`，62 s）：基础包 65,801,944 字节，SHA-256 `6a34014c169b7e42255a0b04c11660f2e5337a3e7bc9fd3d4634677989289292`，glibc 2.17；12 个 wheel；catalog 的 `plugins` 表列出 13 种类型，没有 RAG 和 Character。
- **时间先后**：上面的本机构建和下面的干净沙箱结果，都来自三处追加调整（`provider_config.py`、`runtime/plugin/schemas/`、`AvatarRuntime` 的 `kw_only`）之前的工作区，制品 00:22 构建。追加调整之后，只从最终工作区单独构建了 Agents wheel，确认 `provider_config.py`、`runtime/plugin/schemas/` 的三个文件和 `resolution.py` 都在，`task_config.py` 不在。没有重建全部制品，也没有重跑沙箱。

**干净沙箱（Ubuntu 24.04 rootfs，bubblewrap，最终构建）**

| 组 | 结果 |
|---|---|
| 用户路径 | 基础包上 `config init` 提示 `setup` 会另建 bundle；裸 `config check` 和 Doctor 逐行写明 `` `alphaavatar setup` installs it (…) ``，选 RAG 时写明本版本 setup 不提供；默认预设 53 s，105 个包、514 MB，环境 1.7 GB，不写 `credentials.env`；`config check`、`silero x2`、未选中覆盖被拒都与上一轮一致 |
| 安装包内的插件发现（每次全新进程） | 往环境里装一个带 entry point 的包：自定义 Loop 加 `workers=2` 得到 `probe.loop.echo x2`，自定义 Memory 也被选中；MCP 关闭且名字不存在时通过；再装一个也声明 `voice.vad silero` 的包，`config check` 和 `start` 都报出两个包名，`router.plugin=absent` 同时报出 |
| 已有安装上的失败 | 与上一轮相同：各种中断后 current、入口和数据哈希都不变；切换后收到 SIGTERM 则 B 完整可用；远端预设复用默认环境，默认 bundle 仍通过 |
| 重叠的 setup | 交互式远端 setup 停在确认提示，期间默认预设完成；恢复后在锁内发现另一个 setup 装了 4 项依赖，并入后复用同一环境，两个 bundle 都通过，`credentials.env` 为 600；预先放一个无标记的环境目录，setup 拒绝且原样保留；带标记的残留暂存区被清理，无标记的保留；`current` 是目录时 setup 和 install.sh 都拒绝且原样保留 |
| 命令入口 | 两个前缀同时安装到同一命令目录：一个成功，另一个报「appeared meanwhile and runs …」，它的前缀被完整移除；首次安装在入口刚建好时被 SIGTERM：退出 143，入口和前缀都不留；`current` 是目录或指向 `/etc` 时拒绝且不动 |
| 首次安装 | 与上一轮相同：各种首次失败什么都不留；首次 setup 在 3／10／16／20 s 收到 SIGTERM、6 s 收到 SIGINT，都不留环境；远端预设 23 s，环境 636 MB，本地推理库只有 onnxruntime |

glibc 下限（新脚本实测）：基础包 2.17；远端环境 2.28；默认环境 2.32，只来自本机编译的 llama-cpp（CI 在 manylinux_2_28 里编译）。

凭据替换后注入 SIGTERM 由 pytest 覆盖：用真实的 `install()` 建空环境、真实的 `setup` 命令，分别在 `credentials.env`、`settings.yaml` 替换之后立即向自己发 SIGTERM，结果都完整落在新状态（current、默认 bundle、凭据一致），命令退出 143 并说明 bundle 已启用；`settings.yaml` 替换后抛错也保持新状态。

**推送后待 CI 验证**

- manylinux_2_28 构建；用新脚本实测的 glibc 下限不超过 2.28，且结果非空；
- 干净容器里新增的检查：基础包上 `config init` 的提示、`config check` 的 setup 行和 RAG 行；
- `main` 上的逐提交并发组；整轮重跑时制品覆盖；
- 草稿发布的重新下载与校验，要等第一次打正式 tag。

### 7. 过程中的问题与更正

- **`pthread_sigmask` 不够**：只屏蔽调用线程，pytest 进程里有别的线程，SIGTERM 投递到别处，Python 仍在主线程执行处理函数，测试因此失败。改为在 Python 层延后处理，见第 2 节。
- **向量库 embedding 的归属**：先写成「有 `vdb_config` 的配置段都需要默认后端」，Doctor 会话测试里不用向量库的替身插件也被算进去。改为由向量库 runner 自己声明 `PROVIDERS`。
- **收集期导入**：插件包 `__init__` 不再导入 factory 后，测试里 `import alphaavatar.plugins.persona` 不再提前触发 OpenCV 改环境变量，单独运行某个测试时被环境守卫拦下，改为导入 `factory`。
- **会话子进程恢复配置**：曾让 `restore_application` 也校验插件设置并加载 Provider，最小配置的恢复因此失败。Provider 模型本来就在插件初始化时创建，已撤回。
- **构建自检**：build.sh 的基础树不在 `versions/` 下，按新规则不提 setup，原先 grep「setup installs them」的自检失败，改为检查定位到字段的缺失行，并检查 catalog 的 `plugins` 表。
- **install.sh 拒绝时留下空目录**：拒绝陌生 `current` 前就建了 `versions/`，已调整为检查通过后再建。
- **验收脚本**：入口竞争的假 `ln` 起初只匹配 `/bin/alphaavatar`，没有真正卡住两个安装，修正后重跑。

### 8. 待复核

1. **短句 TTS 测试**：是否在测试替身里改为先追加回执再发布。这一轮未修，Quality 仍可能偶发失败。
2. **`AvatarModule` 的值**：从 `avatar.perception.memory` 这类名字改为能力类型（`memory`、`voice.stt`、`provider.llm`）。它们只用作注册、日志和 entry point 组名，不是存储名。
3. **向量库 embedding 的定位**：从 `memory.vdb_config.embedding` 变为 `memory.plugin (runner alphaavatar.memory.vdb.lancedb)`，因为后端由 runner 决定，配置里没有可改的字段。
4. **自托管端点只在交互的「逐项选择」里**：预设没有对应参数。无人值守部署可以在生成后改 profile，或者另加参数。
5. **SIGKILL**：无法拦截。若恰好落在切换之后、`settings.yaml` 替换之前，`current` 已是新环境，默认 bundle 仍是旧的；新环境包含旧环境的全部依赖，所以旧 bundle 照常可用。
6. **追加调整的两处写法**：`PluginSelection.check()` 在调用时才导入 `UnavailablePlugins`，也可以改为把 `PluginError`、`UnavailablePlugins` 移到 `runtime/plugin/errors.py`（同 `avatar/provider/errors.py`）；`AvatarRuntime` 整个类用 `kw_only=True`，也可以只给 `foundation` 用 `field(default=None, kw_only=True)`。
7. **仍按原计划后移**：setup 只增不减和旧环境清理（第 5 项）；Doctor 里按 `default` 名字判断的内置行为（`vision_off`、`start_services`，第 3 项）；移动端的 App 构建清单来源；去掉 `ENV_FILE`（第 2 项）。

证据（会话临时目录，不入库）：`/tmp/claude-1000/-home-ecs-user-AlphaAvatar/d9cabb34-bdee-4efc-bdcb-b5c422533d57/scratchpad/evidence3/`。

---

## 第 1 项第四轮（基线 `eb2404a`）

依据：Codex 对 `eb2404a` 的审查。远端 Quality（run 42094128016）和 Linux package（run 42094127960）都已通过，制品在 Ubuntu 24.04 干净容器完成基础安装、默认 `setup` 和 `config check`（8 个 runner、Silero x2），但第 1 项尚未验收：三处 P1、一处 P2。审查同时定了第三轮的待定项：修 TTS 测试；接受 `AvatarModule` 的值改为能力类型；接受 embedding 缺失定位到 runner；无人值守的自托管参数放到第 2 项，与凭据来源一起设计；`check()` 的延迟导入和 `AvatarRuntime` 类级 `kw_only=True` 保留；其余按原计划。所有改动在未暂存的工作区。

### 1. 自托管端点的凭据与地址（P1）

- **问题**：向导可以分别把模型和语音指向自己的服务，却只收集 `OPENAI_API_KEY`，两种混搭都会把它发给自托管服务。此外，LangChain 的 embedding 不认 `api_key_env`，语音 STT/TTS 只读 `OPENAI_API_KEY`。
- **每台服务器各用各的变量**：
  - 自己的模型服务读 `ALPHAAVATAR_MODELS_API_KEY`，写进 loop、记忆和画像任务、embedding 的 `extra.api_key_env`；
  - 自己的语音服务读 `ALPHAAVATAR_SPEECH_API_KEY`，写进 `voice.stt.api_key_env`、`voice.tts.api_key_env`；语音和模型是同一个地址时共用模型那一个；
  - 只有用到 OpenAI 官方服务的部分才读、才问 `OPENAI_API_KEY`。
- **后端支持指定变量**：
  - 语音配置段新增 `api_key_env`，只在设置了时才传给插件，不影响第三方实现；
  - OpenAI 的两种 STT、OpenAI 和 Voice.ai 的 TTS 都按它取密钥，默认仍是各自原来的变量；
  - LangChain 的 OpenAI embedding 也按 `api_key_env` 取；变量缺失时直接报错，不再让客户端自己去读 `OPENAI_API_KEY`。
- **地址校验与后端规则一致**：
  - `choices.server_problem()` 用在交互提示和 `Models`/`Speech` 的构造上（以后 App 也会构造这两个类）；
  - 规则：http(s) API 根地址，不得带凭据、查询串或片段；语音服务不在本机时必须用 HTTPS，这是 OpenAI TTS 的规则；
  - 测试逐个 URL 检查向导规则与真实后端（`OpenAIClientConfig`、`OpenAITTS`）的判断一致；
  - 结果：TTS 启动时会拒绝的地址，在启用配置之前就被拒绝。

### 2. 基础包本地安装先复制再校验（P1）

`install.sh --file` 先把包复制到本次独占的暂存区（`--url` 本来就下载到那里），再对这份副本校验 SHA-256、读 manifest 和解包。校验后源文件被替换，装上的仍是校验过的那份。

### 3. 归属检查与凭据提交点（P1）

- **复用和切换之前先确认归属**：
  - `Installation.reached()`：路径必须正是本前缀的 `versions/<名>` 或 `envs/<名>`，途中不经过任何链接；
  - `reusable(plan)` 还要求带 setup 标记且 plan.json 一致；
  - `current()` 用同一条规则；`envs` 本身是链接时直接拒绝；
  - 指向前缀外、带匹配 plan.json 的链接环境，不再被当作可复用，也不会被切换过去，提示「exists and is not setup's; left as it is」。
- **install.sh 的同类检查**：`current` 必须不经链接落在本前缀内，`envs/` 下的还要带 setup 标记；`versions` 本身是链接时拒绝。
- **凭据随设置一起提交**：
  - 不再原地替换 `credentials.env`，改为在设置锁里把合并后的凭据写进新的私有文件 `credentials-<16 位十六进制>.env`；
  - 同一次 `settings.yaml` 替换写入 `default_bundle` 和 `credentials: <文件名>`，提交后再删掉不再被引用的旧文件；
  - 在这次替换之前被 SIGKILL：设置仍指向旧文件，所有 bundle 照旧读旧凭据；新写的文件没人引用，下次持锁时清掉；
  - 用一个真实被 SIGKILL 的子进程验证过。
- **设置文件不可读时**：设置里写的文件名不合规或 YAML 损坏时，`load_credentials` 一个已存值也不读。这样保住了「设置损坏不影响指定名字的 bundle」这一已有约定，Doctor 的 home 检查会报告要修什么；setup 一开始就会拒绝这样的设置。
- **剩下的窗口**：SIGKILL 落在切换 `current` 之后、提交设置之前时，`current` 已是新环境，默认 bundle 和凭据都还是旧的。新环境包含旧环境的全部依赖，旧 bundle 照常可用。

### 4. 单一完整解析（P2）

- **问题**：`plan_inference_runners` 和 `snapshot_inference_config` 只解析配置段，能力检查却带上了 Provider。其他包的 Provider 声明的 runner 因此被能力检查看到，但启动规划看不到，合法的 `workers=2` 被报为 `unselected_runner`。
- **只留一种解析**：
  - `resolve_plugins` 去掉 `providers` 开关，始终完整解析：插件、插件设置、Provider 后端，以及所有 runner；
  - 加载（含会话子进程恢复）、`config check` 的 worker 校验、能力检查、Doctor、start 的规划和快照都用它；
  - 加载时就按插件 schema 校验设置，报错位置不变（如 `loop.init_config.model`）。
- **只读配置段的地方**：快照和 Doctor 的向量库遍历只看 `plugin_factories()` 里的配置段位置；Provider 的位置不是配置段。

### 5. 短句 TTS 测试

按审查结论修：测试里的假播放器先记录回执，再发布 `FINISHED`，断言不变，产品代码不动。

### 6. 改动文件

| 文件 | 改动 |
|---|---|
| `avatar-host/.../setup/choices.py`、`cli/commands/setup.py` | 每台服务器各自的密钥变量；`server_problem()`；`Models`/`Speech` 构造时校验；交互提示用同一规则；凭据随 `create_bundle` 提交 |
| `avatar-agents/.../configs/plugins/foundation/voice_config.py` | STT、TTS 配置段的 `api_key_env` |
| `avatar-plugins-voice` 的 `stt/openai_segment.py`、`stt/openai_realtime.py`、`tts/openai.py`、`tts/voiceai.py`、`tts/__init__.py`、`README.md` | 按 `api_key_env` 取密钥 |
| `avatar-plugins-provider/.../langchain/embeddings/models.py` | embedding 按 `api_key_env` 取密钥，缺失即报错 |
| `avatar-host/.../configs/credentials.py`、`template.py` | 凭据文件由设置指定，写入新文件后由同一次设置替换提交，提交后清理；不可读的设置不读任何已存值 |
| `avatar-host/.../setup/environment.py` | `reached()`、`reusable()`；`current()` 和复用前的归属检查；`envs` 不得是链接 |
| `packaging/linux/install.sh` | `--file` 先复制再校验；`current` 的归属与链接检查；`versions` 不得是链接 |
| `avatar-agents/.../runtime/plugin/resolution.py`、`runtime/inference/bootstrap.py`、`avatar-host/.../configs/loader.py`、`capabilities.py`、`doctor/doctor.py`、`doctor/session.py` | 单一完整解析；快照和 Doctor 的向量库只读配置段 |
| `DEPLOY.md` | 每台服务器的密钥、语音的 HTTPS、凭据与设置一起提交、加载即完整解析 |
| 测试 | 新增 `avatar-host/tests/setup/test_install_script.py`（用假包跑真实 install.sh）；`test_choices` 新增按 HTTP 请求核对密钥的四种组合和 URL 规则一致性；`test_credentials` 重写，含真实 SIGKILL；`test_environment` 新增链接环境；`test_discovery` 新增 Provider runner；`test_setup` 对应新提交点；router 的 TTS 测试；21 个用了「不可能启动」配置（缺 loop 模型）的测试补上模型；投影测试的恶意键名移到 Provider 的 `extra` |

### 7. 验证

**本地实测**

- 静态检查（最终工作区）：Ruff（`--no-cache`）、格式、`check_workspace.py`（16 个成员）、`uv lock --check`（332 个包）、`git diff --check`、`bash -n`、工作流 YAML、pre-commit（34 个改动和新增文件）全部通过。
- 全量测试 400 项通过；拦截已移除的包后再跑一遍，也是 400 项通过。
- 变异：Python 20 个、install.sh 5 个，全部被抓到（`evidence4/mutants4.log`、`install-mutants.log`）。

  | 编号 | 变异 |
  |---|---|
  | C1–C10 | 各处不写或不读 `api_key_env`；embedding 回落到 OpenAI 的密钥；接受远端 http 语音地址；总是问 `OPENAI_API_KEY`；同一台服务器用两个变量 |
  | O1–O3 | 只凭 plan.json 复用；经链接的 `envs`；经链接的 `current` |
  | K1–K3 | 提交前就删掉被替换的凭据；读最新的而不是设置指定的凭据文件；预设也保存凭据 |
  | P1–P3 | 不规划 Provider 的 runner；worker 校验只看配置段的 runner；Doctor 把 Provider 位置当配置段 |
  | T1 | 假播放器在发布后才记录回执 |
  | E3、E3b | 校验副本却解包源文件；不复制直接校验并解包源文件 |
  | E4a–E4c | 接受经链接的 `current`；接受未标记的环境；接受是链接的 `versions` |

- **按请求核对密钥**（`test_choices`）：本机起假服务器，任何请求都返回 400，但记下请求带的密钥；然后让真实后端各发一个请求。四种组合（模型自托管、语音自托管、两者分开托管、两者同一台）里：
  - loop 的 Responses 请求、画像任务的请求、转写和合成，各自只带所属服务器的密钥，从不带 `OPENAI_API_KEY`；
  - embedding 拿到的是所属服务器的密钥；
  - 用 `-W error::ResourceWarning` 跑也通过。
- **TTS 测试**：
  - 把回执记录推迟 20 ms 的确定性复现，修复前必定失败，修复后 5/5 通过；
  - 16 核全部占满时自然运行 15 次，0 次失败；第三轮同样条件下是 13/15 失败。
- **本机构建**（`--max-glibc 2.32`，63 s）：
  - 基础包 65,806,052 字节，SHA-256 `f0eba72707cb92c3260d670070ab2964c1fbdf058e1cb38142149783f31e5473`，glibc 2.17；
  - 12 个 wheel，glibc 2.32（本机编译的 llama-cpp）；
  - 默认计划 105 个包、514 MB；远端计划 85 个包、212 MB。

**干净沙箱（Ubuntu 24.04 rootfs，bubblewrap，本轮构建）**

| 场景 | 结果 |
|---|---|
| 默认预设 | 53 s，105 个包，环境 1.7 GB；设置目录只有 `settings.yaml` 和锁文件，没有凭据文件；`config check` 8 个 runner；另装一个包含 `provider.llm` 的包，`loop.init_config.model.backend=probe` 加 `workers=2` 时 `config check` 显示 `probe.provider.echo x2`（9 个 runner），Doctor 的 `config.load` 为 PASS，`models.runners` 列出该 runner；Doctor 9 项通过、0 项失败 |
| 交互式自托管（模型 127.0.0.1:18811，语音 127.0.0.1:18812） | 先输入的 `http://speech.invalid:8001/v1` 被拒绝并提示改用 https；只问两台服务器各自的密钥和 LiveKit，不问 `OPENAI_API_KEY`（环境里虽有）；确认后凭据存为权限 600 的 `credentials-c9a7….env`，`settings.yaml` 写着 `default_bundle: own` 和它；用安装好的环境让四个后端各发一个请求，模型服务器的 `/v1/responses` 和 `/v1/chat/completions` 只收到模型密钥，语音服务器的 `/v1/audio/transcriptions` 和 `/v1/audio/speech` 只收到语音密钥；embedding 拿到模型服务器的密钥 |
| `install.sh --file`，校验后源文件被替换 | 用 PATH 上的 `sha256sum` 包装，算完就换成另一个会留下标记的包；安装成功，装上的是校验过的那份，替换包的命令没有运行 |
| `current` 指向 `versions/linked`，而它是指向前缀外的链接 | 拒绝，退出码 1；`current`、外部目录和命令目录都没变 |
| 远端预设，实际安装 | 23 s，环境 636 MB，本地推理库只有 onnxruntime，`config check` 3 个 runner |
| setup 的计划环境是指向前缀外的链接，里面有匹配的 plan.json 和标记 | 拒绝（「exists and is not setup's; left as it is」），`current`、链接和外部目录都不变，没有新建 bundle，原默认 bundle 检查通过 |

- **实测 glibc 下限**（用 `glibc-floor.sh`）：基础包 2.17，远端环境 2.28，默认环境 2.32。2.32 只来自本机编译的 llama-cpp（`libggml-cpu`、`libllama-common`），CI 在 manylinux_2_28 里编译。
- **磁盘空间检查**：在默认沙箱里第一次做「链接环境」探针时，因为它不再算可复用，setup 先做了磁盘空间检查，报沙箱里空间不足，同样没有切换。修复前它会被当成已安装，跳过这项检查。远端沙箱下载量小，在那里走到了归属拒绝。

**推送后待 CI 验证**

- manylinux_2_28 构建，以及默认环境的实测 glibc 下限不超过 2.28；
- Quality 里新增的 `test_install_script.py`（只在 Linux x86_64 运行）和按请求核对密钥的测试；
- 远端预设在 CI 里仍只检查安装计划，实际安装只在本机沙箱做过；
- 草稿发布的校验要等第一次打正式 tag。

### 8. 过程中的问题与更正

- **加载变严后的 22 个测试**：加载时完整解析，就会按插件 schema 校验设置。其中 21 个的配置缺 loop 模型，真实 start 本来就不会接受，改法是补上 `config_samples.LOOP`，断言不变；另 1 个是投影测试，它的恶意键名原本放在 context 设置里，现在会被 schema 拒绝，移到了 Provider 的 `extra`。
- **Provider 位置不是配置段**：完整解析后，快照和 Doctor 的 `_stores` 对 Provider 位置调用 `config.section()`，抛出 AttributeError，Doctor 会话的 8 个测试因此失败。改为只遍历配置段位置。
- **`current()` 不再返回解析后的路径**：回滚时的两处比较原先用 `environment.resolve()`，已改为直接比较。
- **提示不准**：开头的检查起初把「环境路径本身是链接」也报成「envs 不是本安装的目录」，已改为只检查 `envs` 本身。
- **凭据位置依赖设置**：Doctor 的「设置损坏不影响指定名字的 bundle」测试失败，于是定下第 3 节里不可读设置时的语义，并加了测试。
- **测试工具**：本机假服务器要用 conftest 的 `owned_endpoints` 登记才能连；假包的 manifest 要列出至少一个要检查的模块，否则 install.sh 的第二个 `read` 读到 EOF。真实包总会列出。

### 9. 待复核

1. **加载变严**：插件设置在加载时就按 schema 校验，报错位置和文字不变，但现在由加载这一步报出，不再是后面单独的一步。
2. **设置不可读时不读任何已存凭据**：指定名字的 bundle 照常加载；此时若缺密钥，会由 Provider 报「某变量 is required」。
3. **变量名**：`ALPHAAVATAR_MODELS_API_KEY`、`ALPHAAVATAR_SPEECH_API_KEY`；同一个地址共用模型那一个。
4. **凭据存储格式**：由 `settings.yaml` 的 `credentials:` 指定 `credentials-<16 位十六进制>.env`。旧的 `credentials.env` 只出现在 `7c67240`、`eb2404a` 的开发安装里，不再读取，没做兼容。
5. **剩下的 SIGKILL 窗口**：落在切换 `current` 之后、设置提交之前时，`current` 是新环境，默认 bundle 和凭据都是旧的；旧 bundle 依靠新环境包含旧依赖照常可用。
6. **未验证的观察**：LangChain 的 `OpenAIEmbeddings` 默认先用 tiktoken 切分文本，测试里没让它真正发请求。它是否在首次使用时联网下载编码表、自托管 embedding 服务是否接受它发的 token 数组，都没有验证，留给第 3 项 Doctor 实跑。
7. **按计划后移**：无人值守的自托管参数和凭据来源（第 2 项）；setup 只增不减和旧环境清理（第 5 项）；Doctor 里按 `default` 名字判断的内置行为（第 3 项）；移动端的 App 构建清单来源；去掉 `ENV_FILE`（第 2 项）。

证据（会话临时目录，不入库）：`/tmp/claude-1000/-home-ecs-user-AlphaAvatar/d9cabb34-bdee-4efc-bdcb-b5c422533d57/scratchpad/evidence4/`（测试、变异、构建、TTS）和 `/tmp/claude-1000/-home-ecs-user-AlphaAvatar/d9cabb34-bdee-4efc-bdcb-b5c422533d57/scratchpad/accept4/`（沙箱脚本与记录）。

---

## 第 1 项第五轮（基线 `eee0c28`）

依据：Codex 对 `eee0c28` 的审查。远端 Quality（run 42182137448）和 Linux package（run 42182137506）都已通过，全量 400 项；同一提交的制品在 Ubuntu 24.04 干净容器完成了默认 `setup`，基础包与完整环境的 ELF 扫描下限分别是 glibc 2.17 和 2.28。默认安装路径已通过验收，但第 1 项还不能关闭：三处 P1、一处 P2。

审查对上轮待定项的结论：
- 接受加载时按 schema 校验插件设置；
- 接受「设置损坏时跳过已存凭据、显式指定的 bundle 仍可选择」，但要补上非法 UTF-8 和读不了的设置文件这两种情况，同时保持选默认 bundle 和 `setup` 的严格校验；
- 接受版本化凭据文件，旧 `credentials.env` 不做兼容；自托管的变量名要随端点绑定一起定；
- 接受 SIGKILL 后暂时处于「新环境、旧默认 bundle、旧凭据」，但要如实记录残留的同名 bundle 文件；完整的强杀恢复放到第 5 项；
- 自托管 embedding 的实际请求和编码表的首次下载留给第 3 项 Doctor；
- URL 预检要补非法端口和空用户名。

所有改动在未暂存的工作区。

### 1. 自托管凭据绑定到端点（P1）

- **问题**：所有自托管模型共用 `ALPHAAVATAR_MODELS_API_KEY`，所有自托管语音共用 `ALPHAAVATAR_SPEECH_API_KEY`。为服务器 B 建 bundle 时按 Enter 会沿用 A 的密钥；若保存了 B 的密钥，旧 bundle A 反过来会用 B 的密钥。
- **改法**：每台自托管服务器的密钥变量由它的端点派生，`choices.server_key(url)` 生成 `ALPHAAVATAR_SERVER_KEY_<12 位十六进制>`。
  - 端点按「协议 + 主机 + 端口 + 路径」规范化：主机大小写、默认端口、结尾斜杠都不影响结果。
  - 只有同一个端点得到同一个变量，所以只有同一端点能沿用已存的值；端口、路径、协议或主机任何一处不同，变量就不同。
  - 向导提问时写明变量名和对应地址；bundle 的 `api_key_env` 指向这个变量。原来的 `MODELS_KEY`、`SPEECH_KEY` 两个全局变量已删除。
- **URL 预检**：`server_problem()` 现在拒绝任何用户信息（包括空用户名）和非法端口（越界、为 0、不是数字）。`OpenAIClientConfig` 和 TTS 的 `PCMHTTPProvider` 也加上同样的端口与用户信息判断；一致性测试新增 6 个 URL，向导与两个后端的判断逐个一致。

### 2. 默认 bundle 与凭据取自同一次设置读取（P1）

- **问题**：`start`、`config check` 和 Doctor 都是先 `load_environment()` 读一次设置（取凭据），再 `select_configuration()` 读一次（取默认 bundle）。两次之间若有 setup 提交，就会拿旧凭据配新 bundle；读取方拿到旧凭据的文件名后，若该文件被写入方回收，就读不到凭据。
- **改法**：`credentials.read_stored()` 一次读出设置和它指定的凭据，返回快照 `bundles.Settings`。
  - 快照包含 `values`、`credentials`（`repr=False`，不会出现在任何输出里）和 `error`。
  - 凭据文件只写一次、从不修改，而且设置不再引用它之后才会被回收。所以打开时发现它已经不在了，就说明设置已被替换，重读一遍即可；已打开的文件在被删除之后仍能读完。
  - `load_environment()` 返回这份快照，`select_configuration(target, overrides, settings)` 从同一份快照取默认 bundle。`start`、`config check` 和 Doctor 都这样传递。
- **设置读不了时**：
  - `read_settings` 把非法 UTF-8 和其他读取错误（权限不足、路径是目录等）都转成 `ConfigReferenceError`；
  - 显式指定的 bundle 照常加载，只是不读已存凭据；
  - 选默认 bundle（`Settings.checked()`）和 `setup` 照样严格报错。

### 3. 安装锁不经链接、打开时不截断（P1）

- **问题**：`install.sh` 用 `exec 9> "$prefix/.install.lock"` 打开锁，这一步在检查归属之前，会跟随链接并截断目标。Codex 把锁链接到前缀外的文件，即使安装以退出码 1 结束，那个文件也已被清成 0 字节。
- **改法**：Shell 和 Python 用同一条规则。
  - 锁必须是本前缀里的普通文件，是链接或不是普通文件就拒绝并原样保留。
  - Shell 先检查再用 `>>` 打开：即使检查之后被换成链接，追加打开也不截断任何内容。
  - Python 用 `O_APPEND | O_NOFOLLOW` 打开，打开时原子地拒绝链接，并用 `fstat` 确认是普通文件。
  - 已经存在的锁文件，内容在打开前后不变。

### 4. 自定义插件的两处缺口（P2）

- **一个 runner 声明多个 Provider**：原先它们共用一个位置，后一个覆盖前一个。现在每个 Provider 的位置写明「哪个 runner 需要它」，例如 `loop.plugin (runner probe.two.providers needs provider.llm 'first')`。
- **Provider 的 runner 再声明下游 Provider**：`resolve_plugins` 改为循环，直到不再出现新的 Provider；下游 Provider 被解析，它的 runner 也参与规划。
- **自定义 Memory 有自己的 schema**：`config check` 的摘要只报告该 schema 里确实存在的开关，不再按内置字段取值。

### 5. 强杀后的现状（如实记录）

实测：在 `settings.yaml` 替换之前 SIGKILL setup，默认 bundle 和凭据保持旧值，但新 bundle 的文件（如 `configs/bundles/beta.yaml` 和它的 profile）会留在磁盘上。用同一个名字重试，setup 会报「Bundle 'beta' exists …; choose another --name」，`create_bundle` 抛 `FileExistsError`。只能换一个名字，或手工删除这些文件。按审查意见，完整的强杀恢复放到第 5 项。

### 6. 改动文件

| 文件 | 改动 |
|---|---|
| `avatar-host/.../setup/choices.py` | `server_key()`；按端点生成凭据；`server_problem()` 加端口与用户信息判断 |
| `avatar-host/.../configs/bundles.py`、`credentials.py` | `Settings` 快照；`read_stored()` 在凭据文件被回收时重读；`read_settings` 的 UTF-8 与读取错误；`select_configuration` 接受快照 |
| `avatar-host/.../cli/commands/run.py`、`config.py`、`doctor/doctor.py` | 默认 bundle 取自加载凭据的同一份快照 |
| `packaging/linux/install.sh`、`avatar-host/.../setup/environment.py` | 安装锁不经链接、不截断 |
| `avatar-agents/.../runtime/plugin/resolution.py` | runner 的 Provider 各有唯一位置；循环解析到不再出现新的 Provider |
| `avatar-host/.../configs/view.py` | 摘要只读 schema 里存在的开关 |
| `avatar-plugins-provider/.../openai/llms/config.py`、`avatar-plugins-voice/.../tts/codec/pcm.py` | 拒绝非法端口；Responses 客户端也拒绝空用户名 |
| `DEPLOY.md` | 端点绑定的密钥变量；默认 bundle 与凭据同一次读取 |
| 测试 | `test_setup`：两台服务器的四步复现；`test_credentials`：快照、回收重读、四种读不了的设置、三个命令在子进程里并发提交；`test_bundles`：非法 UTF-8 与读不了的设置；`test_install_script`、`test_environment`：锁；`test_discovery`：两个 Provider、级联 Provider、自定义 Memory schema；`test_choices`：端点变量与新增 URL |

### 7. 验证

**本地实测**

- 静态检查：Ruff（`--no-cache`）、格式、`check_workspace.py`（16 个成员）、`uv lock --check`（332 个包）、`git diff --check`、`bash -n`、pre-commit（20 个改动和新增文件）全部通过。
- 全量测试 418 项通过；拦截已移除的包后再跑一遍，也是 418 项通过。
- 变异 20 个，全部被抓到（`evidence5/mutants5.log`）。

  | 编号 | 变异 |
  |---|---|
  | S1、S2 | 所有服务器共用一个变量；变量只按主机生成 |
  | R1–R6 | 选默认 bundle 时重读设置；凭据文件被回收时当作没有凭据；`config check`、`start`、Doctor 分别不传快照；快照的 repr 带出凭据 |
  | B1、B2 | 非法 UTF-8、读不了的设置原样抛出 |
  | L1–L3 | Shell 用 `>` 截断打开；Shell 不检查链接；Python 跟随链接打开 |
  | P4、P5 | runner 的多个 Provider 共用位置；只解析一轮 Provider |
  | V1 | 摘要按内置字段读取任何 schema |
  | U1–U4 | 向导接受空用户名；向导、Responses 客户端、TTS 分别接受任意端口 |

  首轮有两个变异存活：S2，因为路由测试里两台服务器只有端口不同，却没检查变量名；R6，因为断言用的密钥含引号，repr 会转义它。补了端点变量的规范化测试、改用不含特殊字符的值之后，两个都被抓到。
- **本机构建**（`--max-glibc 2.32`，63 s）：基础包 65,812,841 字节，SHA-256 `5909ddcbcfdd4acf122171f8cdc030babba2d3a74a2b03af38ef62daaf6f8362`，glibc 2.17；12 个 wheel。

**干净沙箱（Ubuntu 24.04 rootfs，bubblewrap，本轮构建）**

| 场景 | 结果 |
|---|---|
| `.install.lock` 是指向前缀外文件的链接，安装一个不存在的包 | 退出码 1，报「…/.install.lock is not a lock file this script or setup made; it is left as it is」；外部文件仍是 15 字节，内容不变 |
| 远端预设 | 实际安装，环境 642 MB；之后的自托管 bundle 都复用这个环境 |
| bundle a，服务器 A（127.0.0.1:18821）：输入并保存密钥 | 提问 `ALPHAAVATAR_SERVER_KEY_C5CD10BDFB01`，不问 `OPENAI_API_KEY`；保存 |
| bundle b，服务器 B（127.0.0.1:18822）：在密钥处按 Enter | 提问 `ALPHAAVATAR_SERVER_KEY_CEB85A8A1EBD`，提示里没有「Enter keeps」；退出码 1，报「Missing credentials: …CEB85A8A1EBD」 |
| bundle b：输入并保存 B 的密钥 | 只保存 B 的变量，A 的不变 |
| bundle c，服务器 A：按 Enter | 提示「(set; Enter keeps it)」，沿用 A 的密钥 |
| 用安装好的环境，分别从 bundle a、b、c 发 loop 和记忆任务的请求 | 服务器 A 的 `/v1/responses` 和 `/v1/chat/completions` 各收到 2 次，都是 `key-a`（来自 a 和 c）；服务器 B 各收到 1 次，都是 `key-b` |
| 安装包里，一个 runner 声明两个 Provider；某个 Provider 的 runner 声明下游 Provider | 两个缺失的 Provider 各自报在「…needs provider.llm 'first'」「…needs provider.embedding 'second'」；下游缺失报在「loop.init_config.model.backend (runner probe.provider.chain needs provider.embedding 'downstream')」 |
| 安装包里，自定义 Memory 带自己的 schema | `config check` 摘要为 `{'plugin': 'schema', 'vdb': None}`，退出码 0 |

实测 glibc 下限：基础包 2.17，远端环境 2.28。

**推送后待 CI 验证**

- 同一提交的制品在干净容器里的默认 `setup`，以及默认环境的 glibc 下限不超过 2.28；
- Quality 里本轮新增的测试；
- 远端预设在 CI 里仍只检查安装计划，实际安装只在本机沙箱做过；
- 草稿发布要等第一次打正式 tag 才会实跑。

### 8. 过程中的问题与更正

- **快照的 repr 会带出凭据值**：断言失败的输出里已经能看到，改为 `repr=False` 并加了测试。
- **测试构造错误**：
  - 非法 UTF-8：`f"…\xff".encode()` 得到的是字符 ÿ 编码后的合法字节，改为拼接 `b"\xff"`。
  - 读不了的设置：用目录占住 `settings.yaml` 的路径，不依赖是否以 root 运行。
- **进程内跑 `start`**：报错走的是 HostLog 的日志，capsys 截不到，还触发了环境守卫。三个命令的并发用例都改在子进程里运行，替换 `load_environment` 后在读完凭据的那一刻提交新的默认 bundle。
- **O-2 导入副作用**：`test_setup` 里调用 `load_application` 会导入 persona 的 OpenCV，它会改进程环境变量。改为在收集阶段先导入 `alphaavatar.plugins.persona.factory`，与其他 Host 测试一致。

### 9. 待复核

1. **变量名形式**：`ALPHAAVATAR_SERVER_KEY_<sha256(端点) 前 12 位，大写>`。名字本身看不出是哪台服务器，向导提问时写明了地址；无人值守时要知道这个名字，会和第 2 项的凭据来源一起设计。
2. **端点的界定**：协议、主机、端口、路径任何一处不同都算另一台服务器。同一台机器换个路径，比如 `/v1` 换成 `/openai/v1`，也要单独的密钥。
3. **重读的次数**：凭据文件被回收时最多重读 16 次；仍然在变就报「Settings … kept changing while read」。
4. **仍按计划后移**：强杀后的完整恢复（第 5 项）；自托管 embedding 的实际请求和首次编码表下载（第 3 项）；无人值守的自托管参数与凭据来源（第 2 项）；Doctor 里按 `default` 名字判断的内置行为（第 3 项）。`config check` 摘要里的 `vdb` 也仍按 `plugin == "default"` 判断，同属这一类。

证据（会话临时目录，不入库）：`/tmp/claude-1000/-home-ecs-user-AlphaAvatar/d9cabb34-bdee-4efc-bdcb-b5c422533d57/scratchpad/evidence5/`（测试、变异、构建）和 `/tmp/claude-1000/-home-ecs-user-AlphaAvatar/d9cabb34-bdee-4efc-bdcb-b5c422533d57/scratchpad/accept5/`（沙箱脚本与记录 `r5.log`）。
