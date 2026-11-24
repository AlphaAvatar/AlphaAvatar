# 0.6.9 发布准备第一步：统一版本与发布文档 — Claude Code 日志

- 分支：`dev/v0.6.9`，基线 `dd47be2e`（用户告知 CI Quality 通过）；日期为 CST，2026-11-24。
- 依据：用户的任务：统一版本为 0.6.9，编写 `docs/releases/v0.6.9.md`，更新 README 和 ROADMAP，集中检查。
- 范围：
  - 不运行 `make release`、`scripts/maintenance/release.sh` 等有上传、提交、打 tag 副作用的脚本；
  - 不重跑付费模型调用、通话、长时间压力测试和手工安装验收；
  - 改动留在工作区，不暂存、不提交、不推送、不合并、不打 tag、不发布。

## 1. 版本

- 16 个包的 `version.py` 由 `0.6.8` 改为 `0.6.9`。各包用 hatch 动态版本，读自这个文件。
- `uv.lock` 不记录可编辑工作区成员的版本，内部依赖也不带版本约束，所以锁文件无需改动：`uv lock --check` 通过。
- `avatar-host/alphaavatar/host/service/sessions/manager.py` 的 docstring 和错误文字写的是当前版本的行为（单次 attachment、不重新绑定），同步改为 v0.6.9。
- 保留 `0.6.8` 的地方：
  - 历史日志和旧 release notes；
  - `docs/cli/cli.html` 与 `scripts/docs/cli_preview.py` 中录制时的构建号；
  - `publish-pypi.yml` 中以已有 tag 举例的 `v0.6.8`。
- 本地 `.venv` 的工作区包要 `--reinstall-package` 才会刷新元数据：普通的 `uv sync` 不会重建已安装的可编辑包，元数据仍是 0.6.8。

## 2. 文档

- `docs/releases/v0.6.9.md`：结构沿用 v0.6.8，按主题写；不罗列 KD 编号。
  - 事实来源：当前源码、包 README、`docs/cli/*`、`docs/bugs-zh.md` 和本阶段日志。先由子代理整理带出处的事实表，所有承诺性说法再逐条对照源码和日志核对。
  - 核对时更正的说法：
    - Doctor 输出边界只替换凭据、去掉控制字符，不处理路径；
    - runner 重启次数用完时，Host 报错退出（`Shared inference service failed`），而不是只停掉该 method；
    - 模型权重在 runner 首次初始化时下载，不在 Setup 计划内；
    - glibc 2.28 是构建下限，实际安装只在 2.39 上做过；
    - Qdrant 的多 Host 登记只用 qdrant-client 内存模式验证过。
  - 证据分四类：离线测试、合成压力、真实 Doctor、用户人工验收。延迟只写诊断日志 §11.2 认定的两段确定收益，端到端不作收益，各阶段中位数不相加。
  - 明确不包含：回滚／降级、App／TUI、默认流式 STT、首个短句即合成、预建连接、持久 Episode、自动迁移、`alphaavatar test`。
- README：Latest News 增加 0.6.9 一条。安装说明与当前实现一致，未改。
- ROADMAP：
  - PLAN OVERVIEW 增加 Installation & Diagnostics（v0.6.9 完成）；
  - Agent Core、Runtime、Router、Memory、Persona 各增加 2026-11 的完成项；
  - NEXT STEPS 的 v0.6.9 标为完成，并把 replicas 改为实际的 workers 设置；
  - 延迟优化的后续项（流式 STT、首个短句即合成、预建连接、提前做召回 embedding）写进 Runtime TODO 原有的延迟一行，仍为 Planned。
- `AGENTS.md`、`AGENTS-zh.md` 的文档索引增加 `releases/v0.6.9.md`，按指南要求两份同步。

## 3. 验证

| 项 | 结果 |
|---|---|
| `uv lock --check`、`check_workspace.py` | 通过；16 个成员 |
| 已安装元数据、`alphaavatar --version` | 16 个包都是 0.6.9；`AlphaAvatar 0.6.9` |
| `uv build --all-packages --no-sources --build-constraints`（按 CI，uv 0.10.0，输出到仓库外） | 16 个包 32 个文件都是 0.6.9；Twine 7.0.0 全部 PASSED |
| `packaging/linux/build.sh --allow-dirty --max-glibc 2.32`（本机不是 manylinux，CI 为 2.28） | 构建成功，含包内 `alphaavatar --version` 自检；manifest id `0.6.9-dd47be2e0eab-dirty.…`，manifest、catalog 和 wheel 均为 0.6.9；SHA256SUMS 通过 |
| ruff check、ruff format --check、`git diff --check`、pre-commit（改动文件） | 通过；hook 没有改动文件 |
| 相对链接与锚点（改动的 5 个 Markdown） | 新增链接都能解析。另有 16 个旧锚点不在本次改动的行内（ROADMAP 目录指向 emoji 开头的标题、指向 README 的 HTML 标题），未改 |
| 离线全量（`PYTHONDONTWRITEBYTECODE=1 ALPHAAVATAR_MODEL_OFFLINE=1`） | 1219 passed，397 s |

## 4. 发现，未改

- `docs/cli/doctor.md` 第 204 行仍写 KD-17 "stays open"，KD-17 已修复；第 318 行写 `completion_wait_sec`，实际设置是 `speech_completion_wait_sec`。
- `examples/README.md` 第 38 行说 demo 保留 `consolidated_lookup`；`demo.yaml` 实为 `union`（`voice-minimal` 是 `consolidated_lookup`）。
- 模板和示例的 `transcript_wait_sec: 3.0` 等于 `transcript_timeout_sec`，观察点与期限重合，观察提示在期限前不会出现；schema 默认 0.75。只影响观察提示，不影响提交。
- `docs/bugs-zh.md` 的 O-33 已于 2026-11-23 处理，仍列在"观察与延期"中。
- CONTRIBUTING 的发布流程图只有 Quality → Notes → Release，缺少 release.yml 中的 Linux 安装包构建和资产上传。

## 5. 下一步

- 用户 review 后提交、推送，核对该 SHA 的 CI。
- 第 4 节各项由用户决定修复或保留。

## 6. 文档收尾（基线 `a81e2022`）

用户提交第一步为 `a81e2022`，该 SHA 的 CI 通过：Quality 45466679418（lint、build、install），Linux package 45466679412。本轮只改文档，生产代码和默认配置不变。

| 项 | 改动 | 依据 |
|---|---|---|
| 安装后的 PATH | README、release notes 的安装命令单独成块。说明安装器会询问是否接着运行 Setup；之后按 `Next` 或新开终端，再运行 Doctor、start；只有跳过或没完成 Setup 时才手动运行。没有加固定路径或 export | `install.sh` 只为新终端写 PATH，当前终端靠 `Next` 中的 `source` 行（KD-51） |
| embedding 预检 | release notes、ROADMAP：在打开存储时检查；Setup 只依据已有的本地 LanceDB 记录提前拒绝；Qdrant、实际维度和记录判断不了的情况，在存储打开时检查 | `space.recorded_conflicts()` |
| 已有 Bundle 的 Setup | release notes：不再询问能力、模型和凭据；终端里仍展示摘要并询问 `Install and enable?`，没有终端时无人值守。setup.md 选项表的 `BUNDLE` 一格同步 | `cli/commands/setup.py`：`terminal = sys.stdin.isatty()` |
| Doctor 的临时数据 | 会话数据和本地向量存储放在临时 workspace，结束后删除；首次下载的模型留在配置的模型缓存；远端测试存储中写入的内容不随临时目录删除 | doctor.md 的 Storage 一节 |
| 第 4 节的五处 | doctor.md 的 KD-17 改为按当前期限、notice 和迟到结果处理来写；`completion_wait_sec` → `speech_completion_wait_sec`；examples/README 分别写 Demo 为 `union`、voice-minimal 为 `consolidated_lookup`；bugs-zh 把 O-33 移到已修复的 Host 一节，保留两份日志的链接；CONTRIBUTING 的发布流程补上 Linux 安装包和资产上传、校验、发布 | `release.yml`、`linux-package.yml`、`build.sh --release` |
| README 精简（用户追加） | 删去安装器那段说明（需要 Bash、从 v0.6.9 起发布 Linux 文件、指定版本或镜像），源码一段只留 "For development, from source"；其他版本、镜像和 release 源码并入末尾 DEPLOY.md 链接的说明 | DEPLOY.md 开头讲 release 源码，安装一节讲 `--version`、`--file`、`--url` |
| 观察点与硬期限 | release notes、Router README、identifiers-zh：schema 中观察点默认 0.75 s；`demo.yaml` 和 Setup 模板为 3.0 s，与硬期限重合，期限前不报 pending。默认值不变 | `coordinator._wait_transcript()` 的计时为 `min(wait, timeout)` |

核对：

- 改动文档中反引号里的设置名都能在源码或配置中找到。例外只有 Upgrading 一节有意写的旧名（`max_hold_sec`、`policy.commit_threshold`、`max_turn_candidates`），以及未改动行里规划中或已删除的名称。
- 相对链接共 170 个，都能解析；另有 14 个 ROADMAP 目录锚点（emoji 开头的标题）是原有的，未改。
- `git diff --check` 和 pre-commit（改动文件）通过。
- 按用户要求，没有重跑测试、模型调用、构建和安装验收。

尚存：`make release` 结束时仍提示 "Quality checks, generate notes and create the Release"，没有提到 Linux 安装包。这只是 Makefile 的输出文字，本轮没有改。
