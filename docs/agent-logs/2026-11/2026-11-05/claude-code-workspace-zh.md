# AlphaAvatar v0.6.9 Workspace — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 本文件记录 Workspace 从 Core 迁出及后续 review 收尾，按时间顺序追加。
- 统一的 KD/O 表仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| Workspace 迁出 Core | 运行时路径和目录准备迁到 Agents，应用路径和连续性检查迁到 Host | 2026-11-05 | `36ba7f6` | 未提交（用户提交） | 待复核。只做模块迁移和引用调整 |

---

## Workspace 迁出 Core（基线 `36ba7f6`）

- 同批的 Context 回归收尾见 `2026-11-04/claude-code-context-zh.md` 第 10、11 节。两部分分开存放：Context 部分在暂存区，本部分在工作区未暂存。
- 函数体、数据类字段、错误类型和错误消息都没有改。`check_workspace_continuity` 抛出的仍是 `WorkspaceMigrationRequired`，现由 Agents 定义。
- 路径选择和目录创建的调用点不变：
  - Host 继续按平台和配置解析根目录（`host/configs/paths.py`、`loader.py`）；
  - `alphaavatar dev/start` 在 `prepare application paths` 阶段调用 `check_application_paths`，再准备应用目录和 Workspace；
  - `AvatarHost._serve` 经 `asyncio.to_thread(activate_paths)` 准备目录；
  - `create_execution` 经 `asyncio.to_thread(prepare_paths)` 调用 `prepare_session_path`。
  - 原来的延迟导入仍是延迟导入。`AvatarRuntime.create()` 仍由 Host 注入 `WorkspacePaths` 和 `SessionPath`，多端沿用这个注入点。

### 1. 迁移映射

| 原位置（`alphaavatar.core.workspace`） | 新位置 | 内容 |
|---|---|---|
| `paths.py` | `alphaavatar.agents.workspace.paths` | 整个文件原样移动：`path_key`、`absolute_root`、`WorkspacePaths`、`UsersPaths`／`UserPath`、`SessionsPaths`／`SessionPath`、`GraphPaths`、`MemoryPaths`、`MemoryExportPaths`、`EpisodesPaths`、`ContextsPaths`、`IndexesPaths`、`ArtifactsPaths`、`DataPaths` 等 |
| `operations.py` 的 Workspace 部分 | `alphaavatar.agents.workspace.operations` | `WorkspaceMigrationRequired`、`check_legacy_identity`、`prepare_workspace`、`prepare_user_path`、`prepare_session_path` |
| `operations.py` 的应用部分 | `alphaavatar.host.workspace.operations` | `check_workspace_continuity`、`prepare_application` |
| `application.py` | `alphaavatar.host.workspace.application` | `ApplicationPaths`、`ConfigPaths`、`CachePaths`；只改了一行导入 |
| `__init__.py` | 两个包各自的 `__init__.py` | 各自导出上述名称。`absolute_root` 和原来一样不在包级导出，调用方从 `.paths` 导入 |

- `avatar-core/alphaavatar/core/workspace/` 已删除。
- 依赖方向：
  - Core 和 RTC 中没有 Agents、Host 或插件的导入；Core 里出现的 `alphaavatar.plugins.mcp` 是日志来源名字符串，基线就有；
  - Agents 不导入 Host；
  - 插件只引用 `alphaavatar.agents.workspace`；
  - `alphaavatar.agents.workspace` 只依赖标准库；
  - `alphaavatar.host.workspace` 只依赖 `alphaavatar.agents.workspace`。

### 2. 引用调整

- 生产代码 23 个文件：
  - Agents 5 个：`configs/avatar_info_config.py`、`runtime/runtime.py`、`runtime/inference/runner.py`、`runtime/modules/participants/runtime.py`、`utils/files/model/model_files.py`；
  - Host 10 个：`application/application.py`、`application/bootstrap.py`、`cli/commands/run.py`、`configs/application.py`、`configs/bundles.py`、`configs/loader.py`、`configs/paths.py`、`configs/template.py`、`doctor/doctor.py`、`doctor/session.py`；
  - 插件 8 个：Persona `storage/store.py`、`storage/runtime_state.py`、`storage/vdb/lancedb.py`，Memory `storage/markdown/export.py`、`storage/vdb/lancedb_runner.py`，MCP `runner/lancedb_runner.py`，RAG `rag_anything.py`，DeepResearch `tavily.py`。
- 测试 15 个文件：Agents 3 个，Host `test_host_lifecycle.py`，Persona 3 个，Memory 2 个，Router 3 个，Loop 1 个，Context 2 个。只改导入。
- 文档：`docs/identifiers-zh.md` 的源码链接；`avatar-agents/README.md` 和 `avatar-host/README.md` 的包结构树。Core README 的结构树本来就没有列 workspace。

### 3. 迁移前后逐项核对

做法：
- 用 `git archive 36ba7f6` 把基线的包导出到 scratchpad，经 `PYTHONPATH` 优先加载（编辑安装用的是普通路径条目），让新旧两边跑同一个探针脚本。
- 探针输出 JSON，临时根目录统一替换为占位符后逐字比较：**完全一致**。
- 探针确实跑到了实际行为：其中的错误项都是预期的拒绝或保护。

| 项 | 覆盖 |
|---|---|
| `path_key` | 23 个标识：安全键、大小写、设备名（`con`、`COM1`、`lpt9.log`）、128／129 字符、中文、Unicode 组合字符、`/`、`.`／`..`、`~id-` 前缀；首尾空白、空串、换行被拒 |
| 磁盘路径 | `WorkspacePaths` 完整树，以及用户、图、Memory 导出（含非法 owner kind）、Episode、Context、Session（含 manifest）、索引后端、Artifact；`ApplicationPaths` 完整树、独立 `cache_root`、`workspace(avatar_id)`、`cache.avatar()`；`absolute_root` 拒绝相对路径和 `..` |
| 平台默认根目录 | `platform_application_root` 在 linux、darwin、win32 下，分别带 `XDG_DATA_HOME`、带 `LOCALAPPDATA` 或都不带 |
| 配置优先级 | 走真实的 `load_application`，控制 `HOME` 和环境变量：平台默认、`XDG_DATA_HOME`、`ALPHAAVATAR_HOME`；文件里的 `application.home` 优先于环境变量；覆盖项优先于文件；`application.cache_root`、`avatar.workspace_root`；`previous_workspace_roots`；`AVATAR_WORK_DIR`、`ALPHAAVATAR_MODEL_CACHE` 被拒及其消息 |
| 旧数据保护 | `check_application_paths`：大小写变体目录（`Alice`）、旧版净化目录名（`Avatar_1`）、旧默认 Workspace 含 `users/` 时拒绝；无旧数据、旧目录为空、只有本键目录、显式 `workspace_root` 时通过。另测 `check_legacy_identity` 和 `prepare_user_path` 的冲突检查 |
| 目录准备 | `prepare_application`、`prepare_workspace`、`prepare_user_path`、`prepare_session_path` 之后的 41 个目录 |
| 会话日期 | 走真实的 `create_execution`，固定 `SessionRuntime.created_at`，在 `prepare_session_path` 处截取 `SessionPath`。03:00Z：UTC 为 2026-01-01，Asia/Shanghai 为 2026-01-01，America/Los_Angeles 为 2025-12-31，Pacific/Kiritimati 为 2026-01-01。20:30Z：UTC 为 2026-01-01，Asia/Shanghai 为 2026-01-02，America/Los_Angeles 为 2026-01-01，Pacific/Kiritimati 为 2026-01-02 |

- 全模块导入扫描：基线 664 个模块，迁移后 666 个（Core 的 4 个文件拆成 Agents 3 个、Host 3 个），两边都是 0 失败。

### 4. 验证

- 全量（CI 同方式，`pytest -p no:cacheprovider --basetemp=…`，含两部分改动的工作区）：328 passed、0 failed，用时 2 分 29 秒；运行前后 `git status --porcelain --ignored` 一致，磁盘剩余 11 GB。
- 只含 Context 部分时，全量同为 328 passed、0 failed，用时 2 分 29 秒。
- 用户说上次在同环境对照父提交 `00004378` 时，Context 以外有相同的失败项，其中有 `/tmp` 空间不足导致的错误。本次两次全量都没有失败，也没有遇到空间或其他环境问题。
- 相关子集：Context、Loop、Host 配置、生命周期与 CLI 共 81 项，Doctor 19 项，均通过。

- ruff、ruff format、`uv lock --check`、`scripts/check_workspace.py`、`pre-commit validate-config`，以及 `alphaavatar --help`／`--version` 均通过。

### 5. 待复核

- 仓库原本就没有直接测试 `path_key`、旧数据保护和目录准备的用例，全量测试只间接用到 `WorkspacePaths`。本次靠一次性探针核对，脚本未入库。是否另开批次把探针转成正式回归，由用户决定。
