# 2A-2a Require Explicit Avatar ID — Claude Code 实施日志

- 日期：2026-10-25（CST）
- 分支：`dev/v0.6.9`
- 基线 HEAD：`5c2c5b719b3bbfacc1b297085896f4ca7463d099`（与 `origin/dev/v0.6.9` 一致）
- 状态：已实施并验证，**未 commit、未 push**，等待用户与 ChatGPT 审计
- 授权范围：仅 2A-2a。`avatar.id` 与 `avatar` 段改为必填，移除默认 UUID；不涉及 Workspace 创建、配置导入或进程环境变量传递

## 1. 修改文件

| 类型 | 文件 | 修改 |
|---|---|---|
| 修改 | `avatar-agents/alphaavatar/agents/configs/avatar_info_config.py` | `id: str = Field(min_length=1, max_length=256)`；删除 `import uuid`；`check_id` 规则不变 |
| 修改 | `avatar-agents/alphaavatar/agents/configs/avatar_config.py` | `avatar: AvatarInfoConfig`，去掉 `default_factory` |
| 修改 | `docs/avatar-workspace-layout.md` | 删除 "An omitted ID is generated"，改为说明 `avatar.id` 必填、缺失即拒绝 |
| 新增 | `avatar-agents/tests/test_avatar_config.py` | 1 个参数化测试（2 个用例） |
| 新增 | 本日志 | |

其他生产代码、依赖、`uv.lock` 和 CI 均未改动。

## 2. 行为契约

- YAML 没有 `avatar` 段：抛出 `ValidationError`，位置为 `avatar`，类型 `missing`。
- 有 `avatar` 段但没有 `id`：位置为 `avatar.id`，类型 `missing`。
- CLI 沿用现有的 `format_error` 输出位置，实测输出为 `error: ValidationError` / `fields: avatar.id`，退出码为 2。
- 不再存在自动生成 ID 的路径。缺少 ID 时，校验在 Workspace 解析之前就失败，不创建任何目录。
- 下列内容均未改动：`work_dir` 语义、`model_post_init`、环境变量、WorkspacePaths、Host loader、restore。restore 快照中始终包含 `id`，因此不受影响。

## 3. 测试

`test_missing_avatar_identity_is_rejected_instead_of_generated[missing-avatar | missing-id]`：

- 断言错误列表恰好是 `[(location, "missing")]`。
- 断言临时 HOME 为空：被拒绝的配置不会创建 Workspace。
- 用 `mock.patch.dict(os.environ)` 隔离环境变量，并断言变化集合 ⊆ `{MEMORY_VDB_CONFIG, MEMORY_VDB_TYPE, PERSONA_VDB_CONFIG, PERSONA_VDB_TYPE}`。原因是 KD-2：Memory 和 Persona 的默认工厂即使在配置被拒绝时也会写这些变量。这里只放行已知的这几个名字，其余任何环境变量写入（例如 `AVATAR_WORK_DIR`）仍会导致测试失败。
- 配置模块在测试文件顶部导入，因为导入链中的第三方库会在导入时修改进程环境变量（见 O-2）。这只是测试层面的安排，**不代表配置校验已经没有副作用**。

### 变异验证

在 scratchpad 中复制 `alphaavatar.agents` 后修改副本，通过 `PYTHONPATH` 优先加载。仓库文件没有改动。

| 变异 | 结果 |
|---|---|
| M0 不修改（对照组） | 2 passed |
| M1 恢复 UUID 默认值 | `missing-id` 失败：`DID NOT RAISE ValidationError` |
| M2 恢复 `avatar` 的 `default_factory` | `missing-avatar` 失败：位置变成 `('id',)`，而不是 `('avatar',)` |
| M3 配置被拒绝时写入 `AVATAR_WORK_DIR` | 2 个用例都失败：变化集合超出 KD-2 白名单 |
| M4 配置被拒绝时在 HOME 下创建目录 | 2 个用例都失败：临时 HOME 不为空 |

## 4. 验证结果

| 项目 | 结果 |
|---|---|
| 完整 pytest（CI 方式：`-p no:cacheprovider --basetemp`）×3 | 3 次均为 23 passed，原有 21 个 + 新增 2 个，约 4.71 s；basetemp 中 0 个文件 |
| 检出目录（`git status --porcelain --ignored`） | 前后一致 |
| `ruff check .` / `ruff format --check .` | 通过 / 625 个文件已格式化 |
| `scripts/check_workspace.py` / `uv lock --check` | 16 个成员一致 / 通过 |
| 5 个示例 YAML（每个在独立进程中执行 `load_application`，临时 HOME，禁网） | 全部解析成功，路径为 `<base>/<id>`，无联网尝试 |
| 去掉 `avatar.id` 的 demo.yaml 交给 `alphaavatar start` | 拒绝，输出 `fields: avatar.id`，exit=2，HOME 下没有新文件 |

## 5. 剩余风险

- **测试耗时增加**：pytest 总耗时从约 2.9 s 增加到约 4.7 s，原因是收集阶段导入了配置包（torch、cv2 等）。
- **R3（KD-1 中仍未解决的部分）再次复现**：在同一进程里依次加载 5 个示例时，Workspace 路径逐级嵌套：`alphaavatar_tools/alphaavatar_demo/alphaavatar_airi/…`。原因是上一次校验写入的 `AVATAR_WORK_DIR` 被下一次当成 base 使用。每个示例单独一个进程加载时都正确。按授权，本批不修复，留给 2A-2b。
- **本批不保证的事项**：合法配置在校验时仍会创建 Workspace 并写入环境变量；Memory 和 Persona 仍可能在校验时构造 QdrantClient 并联网。

## 6. 已知缺陷（延续 2A-1，只记录不修复）

| ID | 问题 | 归属 |
|---|---|---|
| KD-1 | `AvatarConfig` 校验时创建 Workspace、写入 `AVATAR_WORK_DIR`/`AVATAR_TIMEZONE`；同一进程内重复校验会让 ID 重复追加（R3）；没有 base 时会写探测 `/var/lib/<id>`。**本批已移除随机 UUID** | 2A-2b / 2A-2d |
| KD-2 | Memory 和 Persona 配置在校验时写 `*_VDB_*` 环境变量（配置被拒绝时也写），并构造 QdrantClient。`check_compatibility=True` 会在构造时发出 HTTP 版本请求，Host 和执行子进程各执行一次，客户端从不关闭 | 需单独授权 |
| KD-3 | Tools 配置把解析后的 secret 写入 `MCP_*` 环境变量 | 需单独授权 |
| KD-4 | Persona LanceDB 查询中 `user_id` 直接拼接、未转义，不安全 | Persona 批次 |
| KD-5 | Persona VDB 保存失败的错误没有被正确处理 | Persona 批次 |
| KD-6 | Memory Passive Recall 的具体完成状态没有完整传播到 Turn-level diagnostics（已按审计更新：不是 MemoryStore 无法区分检索错误与空结果） | Memory 诊断批次 |
| KD-7 | ToolPolicy 的默认审批策略与部分示例文档不一致。**未授权修改默认行为**；需要另行审查工具权限模型、执行授权和用户确认策略，不能损害合理的自主执行能力 | 独立审查 |
| KD-8 | Health 服务默认暴露在网络上，`/status` 没有鉴权 | Host 批次 |
| KD-9 | `host/diagnostics.py` 没有任何引用，且与 core 的 diagnostics 重复，并会和计划中的 `host/diagnostics/` 包同名冲突 | 2A-C1（待授权） |
| O-1 | 初始化期间取消 Runner，要先等满 `close_timeout`（默认 5 s）才发 SIGTERM | 仅记录 |
| O-2 | 导入 `alphaavatar.agents.configs` 会立即加载全部插件和 torch、cv2、weasyprint、openai 等（约 1.7 s）；导入期间第三方库会改写 `LD_LIBRARY_PATH`、`QT_QPA_*`、`OPENBLAS_MAIN_FREE` 等变量 | 仅记录 |

## 7. 未做事项（按授权）

没有修改 Workspace 创建、配置导入或环境变量传递；没有实施 ApplicationPaths、2A-2b、2A-C1；没有修复任何 KD/O 项；没有 commit 或 push。
