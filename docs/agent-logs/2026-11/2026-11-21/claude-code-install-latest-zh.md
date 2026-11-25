# 安装入口：不传来源时安装最新正式版 — Claude Code 日志

- 分支：`dev/v0.6.9`，基线 `2c64164e`；日期为 CST。
- 依据：用户 2026-11-21 的任务。
- 范围：
  - 只简化首次安装入口，不发布 release。
  - 升级继续用 `alphaavatar upgrade`，不改。
  - 改动留在工作区，由用户提交。
- 相关日志：
  - 安装器的来历见 [claude-code-install-zh.md](../2026-11-05/claude-code-install-zh.md)。那里第 1 项第一轮决定"不用 `curl | bash`，避免下载中断时执行半截脚本"，本轮改为推荐 `curl | bash`，用第 2 节的整体读入解决这个问题。
  - 安装锁、归属、中断清理和 current 切换的契约，见 [claude-code-diagnosis-zh.md](../2026-11-20/claude-code-diagnosis-zh.md) 第 12、13 节。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 默认最新版 | `install.sh` 不传来源时安装最新正式版；管道运行整体读入；README、DEPLOY 改为新入口；README 源码克隆改为默认分支 | 2026-11-21 | `2c64164e` | `b8ba1db1` | 已提交 |

## 1. 行为

| 命令 | 结果 |
|---|---|
| `bash install.sh` | 最新正式版 |
| `bash install.sh --version 0.6.9` | 该 release，与原来相同 |
| `--file`、`--url`、`--sha256`、`--prefix`、`--bin-dir` | 与原来相同 |
| 两个或三个来源同时给出 | 用法错误，退出码 2，什么都不建 |
| 来源给了空值（如 `--version ""`） | 报 `needs a value`，退出码 1，不当作"没给来源" |
| `curl -fsSL …/releases/latest/download/install.sh \| bash` | 同 `bash install.sh`；参数写在 `bash -s --` 之后 |

- 没有增加 `--latest` 开关，也没有发布渠道。

## 2. 实现

只改了 `packaging/linux/install.sh`：

- **解析一次，固定 release**：
  - 下载 `releases/latest/download/alphaavatar-linux-x86_64.manifest.json`，只下载这一次。这个文件由 build.sh 从包内 manifest 原样复制，release.yml 发布在包旁边。
  - 从中读出 `version` 和 `release`。要求 `release` 正好是 `v<version>`，版本格式与 `--version` 的校验相同。开发构建的 `release` 为 `null`，会被拒绝。
  - 之后包和 `.sha256` 都从 `releases/download/<tag>/` 下载，不再访问 `latest`。
  - 解包前先比对：包内的 manifest 必须与发布的那份逐字节相同。这样包、manifest 和 SHA-256 一定出自同一个 release、同一个构建。
  - 做法与 `alphaavatar upgrade` 的 `release()` 相同。
- **不需要 jq**：用 bash 的正则读两个字段。读错只会导致拒绝，不会装错：tag 校验和逐字节比对都会拦住。新路径没有增加命令依赖，curl 原来下载时就需要。
- **报错，不换版本**：
  - latest 没有 manifest（含没有 release、网络不通）时，报 `Cannot download …manifest.json: the latest release publishes no Linux x86_64 package, or GitHub cannot be reached`。
  - manifest 不是正式 release 时，报 `names no release of AlphaAvatar`。
  - 缺 `.sha256` 时，报 `No SHA-256 at …`；缺包时，报 `Cannot download …`；包与 manifest 不是同一构建时，报 `holds another build than the manifest published beside it`。
  - 任何一种情况都不尝试旧版本或开发版。
- **先取 `.sha256`**：`--version`、`--url` 和最新版都先下载 `.sha256` 并校验格式，再下载包。缺校验文件时，不必先下载整个包才失败。
- **输出**：解析后打印 `The latest release is vX.Y.Z`；结束时打印 `Installed AlphaAvatar <version>, build <build ID>: …`。
- **管道运行**：脚本主体包在 `{ … }` 里，bash 读完整个脚本才会执行，下载中断时什么都不运行。管道下，子进程的 stdin 也只剩 EOF。
- **契约不变**：
  - manifest 和包都下载到本次带标记的暂存目录，由原有的清理删除。
  - 锁、归属检查、`current` 切换、同构建保留 setup 环境，用的都是原来的代码。
  - 应用 home、配置、凭据、workspace 和模型缓存都不碰。

## 3. 文档

- `README.md`：
  - 首页安装改为 `curl … | bash` 加 `alphaavatar setup`、`doctor`、`start`。
  - 注明需要 Bash，且最新 release 要发布了 Linux 文件（从 v0.6.9 起）；指定版本、本地包和镜像见 DEPLOY。
  - 源码克隆去掉 `--branch v0.6.9`，改为默认分支。写明默认分支包含尚未发布的改动，上面的安装包则是最新正式版；release 源码见 DEPLOY。
- `docs/DEPLOY.md`：
  - 开头给出按 release tag 克隆的示例 `git clone --branch v<version> …`。
  - Linux 包一节的推荐入口改为 `curl … | bash`，并说明解析和校验方式、不回退旧版、整体读入。
  - 保留 `--version`、`--file`、`--url` 示例，补充 `--sha256` 和 `bash -s --` 的用法。
- 其他含安装指令的位置：`docs/cli/README.md`、`setup.md`、`upgrade.md`、`cleanup.md` 只链接 DEPLOY 或引用 `install.sh --version`、`--file`，原文仍然成立，没有改。

## 4. Release 资产核对

- 静态核对：
  - `build.sh --release vX.Y.Z` 产出 `alphaavatar-<version>-linux-x86_64.tar.gz` 及其 `.sha256`、`alphaavatar-linux-x86_64.manifest.json`（`cp` 自包内）、`install.sh`、`SHA256SUMS`。
  - `linux-package.yml` 把整个输出目录作为构建产物上传。
  - `release.yml` 把这些文件全部挂到 release，并核对文件名、大小和 SHA-256，最后才发布。
  - 名称与 install.sh 用的一致。release 以草稿创建再发布，不标记为预发布。
- 线上现状：
  - 当前 latest 是 v0.6.8，没有任何资产。`releases/latest/download/install.sh` 会 302 到 `v0.6.8/install.sh`，然后 404。
  - 因此新入口要等 v0.6.9 发布这些文件后才能用。
- 真实 GitHub 的失败路径：用 `curl file://…/install.sh | bash -s -- --prefix … --bin-dir …` 在会话临时目录运行。
  - 打印 `Finding the latest release`，curl 报 404，随后是第 2 节的报错，退出码 1。
  - 临时前缀里只留下锁文件。

## 5. 验证

- `avatar-host/tests/setup/test_install_script.py` 新增 19 个，原有 22 个不变、全部通过，共 41 个。
- 本机 HTTP 替身按 GitHub 的布局提供文件：`/download/<tag>/` 下放各 release 的文件，`/latest/download/<文件>` 302 跳到最新 tag 的同名文件。
- PATH 上的 curl 包装把 GitHub release 的 URL 改写到替身，拒绝其他远程 URL，不依赖线上 latest 是什么。
- 测试的包 manifest 改为 build.sh 的写法：indent 2，含 `release` 和 `platform`。

| 测试 | 覆盖 |
|---|---|
| `test_with_no_source_the_latest_release_is_installed_from_that_release_alone` | 无参数：请求依次是 latest manifest、它跳到的 v9.9.9 manifest、v9.9.9 的 `.sha256`、包，没有其他请求；不碰旧版 v9.9.8；输出版本和 build ID |
| `test_a_given_source_installs_its_package_and_asks_no_latest_release` × 3 | `--version`、`--url`（镜像路径）、`--file`：latest 更新时仍装指定的包；不请求 latest；`--file` 不发任何请求 |
| `test_sources_are_one_at_most_and_the_latest_only_when_none_is_given` × 7 | 4 种来源冲突（退出码 2）；3 种空值（退出码 1）；都不建目录、不发请求 |
| `test_a_latest_release_that_cannot_be_installed_is_refused_and_no_other_is_tried` × 5 | 没有 release、开发构建的 manifest、缺包、缺 `.sha256`（在下载包之前报错）、包与 manifest 不是同一构建：报错明确；不请求旧版；current、命令和数据不变；不留暂存 |
| `test_the_latest_release_being_the_build_current_runs_keeps_its_setup_environment` | current 指向 setup 环境，同构建复装后仍指向它，不提示重新 setup |
| `test_piped_to_bash_it_runs_once_whole_and_a_script_cut_short_runs_nothing` × 2 | 截掉一半、只缺最后的 `}`：语法错误退出，不建目录、不发请求；完整脚本通过管道安装最新版 |

- 变异（脚本在会话临时目录 `latest/mutate.py`，跑完已恢复）：10 个全部被发现。
  - 包改从 `latest/` 下载；
  - 去掉 manifest 比对；
  - 允许两个来源；
  - 先下载包再取 `.sha256`；
  - 不校验 SHA-256 格式；
  - 不要求 release tag；
  - 同构建不保留环境；
  - 空值当作没给来源；
  - 给了来源也解析最新版；
  - 去掉 `{ }`：首尾一起去掉后，两个截断管道的测试失败。
- 离线全量：按 Quality 的方式运行，900 passed（309.68 s；原 881 加新增 19）。工作区前后对比，只多出测试期间写的这份日志和安装日志的链接行，测试没有留下文件。
- 仓库规范：
  - `ruff check .` 通过，`ruff format --check .` 791 个文件已格式化；
  - `check_workspace.py` 一致，`pre-commit validate-config` 通过；
  - `bash -n` 通过 build.sh、install.sh；
  - 改动文件的 pre-commit 通过。
- 没有重跑之前的 240 次中断注入。原有的信号测试（建暂存、`mv -T`、切换 × 三种信号，建命令链接，清理旧暂存）在新脚本上都通过。
- shellcheck 没有跑：本机没有，从 PyPI 临时获取被权限拒绝。仓库 CI 也只做 `bash -n`。

## 6. 未验证的边界

- **真实 release 的成功路径**：v0.6.9 还没发布。真实 GitHub 上的成功路径要等 release 发布后才能验证：latest 跳转到资产存储、真实文件内容、`curl | bash` 装完。线上只验证了跳转和 404。
- **"最新"由 GitHub 决定**：
  - `releases/latest` 是 GitHub 标记的最新 release，默认是最近发布的非预发布版本，不一定是最高版本号。
  - 例如在 0.7.0 之后再发布 0.6.x 的补丁，latest 会指向补丁。`alphaavatar upgrade` 的默认目标也是这样。
- **两次请求**：`curl …/latest/download/install.sh` 和安装器解析 latest 是两次请求。两次之间恰好发布了新版时，会由旧 release 的安装器安装新 release。包、manifest、SHA-256 仍是同一个 release。
- **同构建复装仍会下载包**：要读出包内 manifest 才知道是不是同一构建，这与原来的 `--version` 相同。upgrade 只读发布的 manifest，所以不用下载。本轮没有改。
- **干净 Linux**：CI 的 verify 任务（ubuntu:24.04，无 Python／Node）仍用 `--file` 安装，最新版路径没有在干净容器里跑过。新路径没有增加命令依赖。
- **PATH（原有问题，未改）**：
  - 首次安装前 `~/.local/bin` 不存在，Ubuntu 的 `~/.profile` 登录时不会把它加进 PATH。
  - 于是同一个 shell 里，紧接着的 `alphaavatar setup` 可能找不到命令；安装器会打印 `export PATH=…` 的提示。
  - README 原来的五行也有同样的问题。

## 7. CI

`b8ba1db1`（本批的提交）：Quality 44893122247 通过；Linux package 44893122264 通过（这次改了 `packaging/`，在其 paths 范围内）。

## 8. 证据

会话临时目录 `latest/`：
- `mutate.py`：变异脚本；
- `real/`：真实 GitHub 失败路径的临时前缀；
- `full.txt`：离线全量输出；
- `checkout-diff.txt`：测试前后工作区对比。
