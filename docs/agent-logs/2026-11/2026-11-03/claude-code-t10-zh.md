# AlphaAvatar v0.6.9 安装、升级回滚与 Doctor 阶段 — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 本阶段（T-10 起）的批次都记录在本文件，按时间顺序追加。
- 2A 阶段及 T-1～T-9 的记录，以及统一的 KD/O 表，仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`；本文件不复制 KD 表。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| T-10A | profile／bundle 配置公共能力：拆分配置生成、选择规则、引用解析 | 2026-11-03 | `62af558` | `de480ad`、`3c40fda`、`85d7fcf` | **已验收**（验收提交 `85d7fcf`）：本地 294 passed（CI 方式 ×1）；review 环境（filelock 3.20.0）收集 294 项、原生选跑 232 项通过，多进程互斥通过；Ruff、格式、workspace、lock 通过；原生 IPC 全量未独立复跑 |
| T-10A1 | 共享 `locked_directory` 的最小缺陷修复：拒绝符号链接锁文件 | 2026-11-03 | `85d7fcf` | `b46c4ea` | **已验收**（验收提交 `b46c4ea`）：filelock 3.20.0；helper 与 Memory 两条路径共 14 项回归通过；review 环境收集 308 项，原生选跑 246 项通过 |
| T-10T | 测试整理（只改测试）：按职责调整目录，合并重复、减少绑定实现细节的断言 | 2026-11-03 | `85d7fcf` | `b46c4ea` | **已验收**（验收提交 `b46c4ea`）：原有 294 个参数化用例全部保留，新增 14 项，无重复收集；另有 20 项推理测试在回环 TCP 适配下通过；原生 IPC 全量未独立复跑 |
| KD-16 | Host 日志关闭时丢失最后一条诊断 | 2026-11-03 | `84f2c6d` | 未提交 | 已修复，待复核：确定性竞态用例在原逻辑上 10/10 失败，修复后 30/30 通过；验证后按 T-10T2 规则移出项目；移出后本地 287 passed |
| T-10T2 | 只为修小 BUG 的测试移出项目 | 2026-11-03 | `84f2c6d` | 未提交 | 待 review：移出 13 个测试函数（23 个用例）；本地 287 passed（CI 方式 ×1） |

---

## T-10A profile／bundle 配置公共能力

- 基线：`62af558`（T-9 验收提交 `69813df` 之后的最新提交），工作区开始时干净。
- 范围：配置公共服务（选择、引用解析、组合、覆盖、生成），`config init` 改为生成拆分配置，`config check`、`start`、`dev` 接入同一选择规则，补测试和文档。
- 顺延：基础 Doctor 移到下一批。

### 1. 结构与引用语法

| 文件 | 内容 |
|---|---|
| `<home>/configs/bundles/<name>.yaml` | `avatar`、`host`、`runtime`（以及任何内联段），加上 `profiles` 引用 |
| `<home>/configs/profiles/<目录>/<name>.yaml` | 一个插件段的内容（段名由 bundle 的引用决定） |
| `<home>/settings/settings.yaml` | `default_bundle` 与其他用户设置 |

```yaml
profiles:
  voice: my-avatar/voice   # <home>/configs/profiles/my-avatar/voice.yaml
```

- **引用只有一层。** `profiles` 把插件段映射到 profile 名。可引用的段由 `AvatarConfig` 的字段推导：除 `avatar`、`runtime` 外的全部插件段，不在 Host、CLI 中硬编码。
- **不会形成循环。** profile 文件只是段内容，自身不能再含 `profiles`，否则报错，所以引用链不可能成环。"循环引用"的测试就是 profile 引用自身的情形。
- **同一段只能有一个来源**：要么写在 bundle 里，要么来自一个 profile；两边都写会报错。
- **名称规则**：
  - bundle 名为 1–64 位小写字母、数字、`-`、`_`；profile 名由同样的段用 `/` 连接。
  - 名称不是路径，也没有 `.`，因此不能跳出目录，也不会和文件路径混淆。
  - 只解析到 Home 下的 `configs/` 内，不受工作目录影响。
- **单文件配置**：外部路径规则不变（显式文件路径、`client_path`、`workspace_root` 等），单文件也可以使用 `profiles`。
- **跨文件不用 YAML anchor。** 生成的 profile 直接写出原模板 anchor 展开后的值。`${...}` 插值在组合之后解析，与单文件一致。

### 2. 选择与覆盖规则

| 参数 | 含义 |
|---|---|
| 含路径分隔符或带扩展名（如 `./a.yaml`、`a.yaml`） | 显式文件，相对路径按工作目录解析 |
| 其他字符串（如 `my-avatar`） | `<home>/configs/bundles/my-avatar.yaml`；名称不合法直接报错 |
| 省略 | settings 中的 `default_bundle`；未设置时报错，并提示 `config init` |

- **只按参数写法判断。** bundle 不存在时直接报错，不会改去找同名文件；反之亦然。
- **`KEY=VALUE` 一律是覆盖。** 例如 `config check voice.tts.speed=1.2` 检查的是默认 bundle。
- **显式参数优先于默认 bundle。**
- **覆盖的作用对象分两类：**
  - `profiles.<section>=<name>` 改变引用；
  - 其余覆盖作用于组合后的配置，与原单文件语义一致。
- **Home 解析不变**：依次看 `application.home` 覆盖、`ALPHAAVATAR_HOME`、平台默认。
  - settings 不参与 Home 选择。
  - 命名 bundle 若写了不同的 `application.home`，会报错：它属于存放它的那个 Home。
- **只读**：选择和解析不创建目录，不写 settings 或环境变量，也不构造客户端。
- **快照**：组合后仍得到原有的 `ApplicationConfig` 和 payload；`profiles` 已展开。会话和 Runner 子进程通过 `restore_application(payload)` 使用快照，不再读磁盘。

### 3. 生成与失败边界（`config init <name> --avatar-id <id>`）

- 先渲染全部文本，并用 `AvatarConfig` 校验，确认 ID 原样保留；先读取 settings，不合法就拒绝。这两步都在写任何文件之前。
- 已有的 bundle 或任一目标 profile 文件：拒绝，不覆盖。已有目录照常复用。
- 先逐个创建所需目录和文件，用 `open("x")`，并记录本次新建了什么；全部配置文件写完后再处理默认 bundle。
- 默认 bundle：
  - 未设置时设为本次的 bundle。没有 `default_bundle` 键时，在原文本末尾追加一行，其他设置和注释原样保留；已有 `default_bundle: null` 时整体重写数值。
  - 已设置时保持不变，settings 一个字节都不写。
- 写 settings 时，先在同目录写临时文件并 `fsync`；若原文件存在，沿用其权限；最后用 `os.replace` 原子替换。
- 任一步失败，按创建的逆序删除本次新建的文件和空目录；已有的文件、共享 profile 和 settings 保持原样，临时文件也会删除。
- 成功输出只列 bundle 路径、profiles 目录（含段名）和默认选择状态，外加原有的凭据变量和下一步提示。

生成示例（`ALPHAAVATAR_HOME=/data/aa`，`config init my-avatar --avatar-id my-avatar`）：

```text
/data/aa/configs/bundles/my-avatar.yaml
/data/aa/configs/profiles/my-avatar/{loop,voice,vision,memory,persona,tools}.yaml
/data/aa/settings/settings.yaml          # default_bundle: my-avatar
```

```yaml
# configs/bundles/my-avatar.yaml（省略头部注释）
avatar:
  id: "my-avatar"
  name: Assistant
  introduction: You are a helpful voice AI assistant.

profiles:
  loop: my-avatar/loop
  voice: my-avatar/voice
  vision: my-avatar/vision
  memory: my-avatar/memory
  persona: my-avatar/persona
  tools: my-avatar/tools
```

```yaml
# configs/profiles/my-avatar/memory.yaml（省略头部注释）
vdb_config:
  collection_name: memory
  embedding: {provider: openai, model: text-embedding-3-small}
init_config:
  conversation:
    provider:
      gateway:
        tasks:
          memory.conversation_delta: {provider: openai, model: gpt-4o, temperature: 0.1}
  tool:
    provider:
      gateway:
        tasks:
          memory.tool_delta: {provider: openai, model: gpt-4o, temperature: 0.1}
```

### 4. 错误与脱敏

- **选择和引用错误**统一抛 `ConfigReferenceError`。
  - 消息只由固定文本、校验过的名称、段名和路径组成，不含文件内容或被拒绝的值。
  - 例如：`Bundle 'my-avatar': profiles.voice references missing profile 'my-avatar/voice': <路径>`。
- **为什么不用字段位置表示**：`format_error` 只显示由标识符组成的字段位置，`my-avatar` 这样的名称会显示成 `?`，看不出是哪个 bundle 或 profile。
- **输出路径**：新增 `format_failure`，只对这类错误附上经过 `Redactor` 的消息（环境变量里的凭据、URL、控制字符都会被处理），其余错误仍用 `format_error`。`config check` 的文本和 JSON、`start`/`dev` 的启动失败、`config init` 都走它。
- **profile 的 YAML 解析错误**不转述解析器文本，因为那段文本会引用原行。
- **`config check` 摘要**新增 `config` 项（bundle 名、是否默认、文件），和其他字段一起经过同一个脱敏边界，`describe_summary(config, source)`。

### 5. 修改文件

| 文件 | 改动 |
|---|---|
| `avatar-host/alphaavatar/host/configs/bundles.py`（新增） | `select_configuration`、`application_paths`、`read_settings`、`compose_profiles`、`ConfigSource`、`ConfigReferenceError`、`format_failure` |
| `configs/loader.py` | `load_application` 接受路径或 `ConfigSource`；按上面的顺序组合 profiles 并应用覆盖；命名 bundle 的 Home 检查 |
| `configs/template.py` | 单文件模板改为 bundle 和 6 个 profile 的文本；`render_bundle`、`create_bundle`（不覆盖、只回滚本次创建、原子更新 settings）；移除 `render_template`、`write_template` |
| `configs/view.py`、`configs/__init__.py` | 摘要加入 `config`；`describe_error` 使用 `format_failure`；导出新接口 |
| `cli/app.py`、`cli/commands/config.py`、`cli/commands/run.py` | 配置参数可省略；第一个参数含 `=` 时视为覆盖；`config init <name>`；`check`、`start`、`dev` 共用选择规则；`start`/`dev` 失败时显示引用错误的消息 |
| `avatar-host/tests/test_config_commands.py` | 新增 bundle 测试（见 §6）；原有 check 用例加上 `config` 行或键；console 用例改为 bundle 流程 |
| `docs/cli/config.md`、`start.md`、`dev.md`、`README.md`、`avatar-host/README.md` | 结构、引用语法、选择与覆盖规则、默认 bundle 行为、生成与失败边界、新的命令写法 |

没有改动 Memory、Persona 的 runtime、processor 或 store，也没有改 Agents/Core 的配置模型。

### 6. 测试（全部离线，`avatar-host/tests/test_config_commands.py`）

| 用例 | 覆盖 |
|---|---|
| `test_init_splits_the_minimal_template_into_a_bundle_and_profiles_that_load_unchanged` | 只创建配置文件和它们的目录（无缓存、工作区、日志）；输出只有位置和默认状态；每个文件都没有 anchor 或 alias，不含机器路径和凭据；按名称、默认、显式 bundle 路径三种方式加载，payload 与旧单文件模板（含 anchor）逐值相等 |
| `test_selection_follows_the_argument_spelling_from_any_directory` | 默认、名称、`KEY=VALUE` 单独出现、显式路径；在两个工作目录下结果相同；工作目录里有同名 `.yaml` 时，只有写成文件形式才读取它；不存在的 bundle 不回退到文件；非法名称报错；`profiles.voice=…` 与段覆盖的叠加顺序 |
| `test_without_a_default_bundle_selection_fails_clearly_and_settings_never_choose_the_home` | 三种未设置默认的情形：settings 不存在、值为 null、带有 home 字样的设置，报错都指出 settings 路径和创建命令，且不创建任何东西；settings 里的 home 字样被忽略，相关键保留；默认 bundle 缺失、名称非法、settings 不是映射或不是合法 YAML 都会报错，且不回显值 |
| `test_reference_errors_locate_the_bundle_and_profile_without_values`（12 种） | 缺失 profile；非法名称（`..`、绝对路径、大写、带扩展名）；非插件段；`profiles` 不是映射；内联与引用重复；自引用（循环）；profile 是列表；YAML 错误且含凭据；命名 bundle 改 Home。文本和 JSON 都指出 bundle 与引用位置，不回显值，不改动任何文件 |
| `test_bundles_share_profiles_and_an_accepted_snapshot_stays_frozen` | 第二个 bundle 引用第一个的 profile；修改磁盘上的 profile 后，新的加载会生效；删除 profiles 目录后，已接受的 payload 仍能原样还原 |
| `test_checking_a_bundle_reads_only_and_hides_profile_credentials` | profile 里含 VDB 密钥和 MCP 凭据；按名称和默认、文本和 JSON 检查都不泄露；文件树、环境变量不变，不构造客户端；payload 中的凭据完整保留 |
| `test_init_never_overwrites_reuses_directories_and_keeps_an_existing_default` | 追加 default 后原有注释和设置逐字保留；已有 profile 目录中的其他文件不受影响；已有 bundle、已有 profile 目标都拒绝，文件树逐字节不变；已有默认时保持不变，settings 不改一个字节；非 ASCII ID `助手-1` 能还原；非法名称、ID 或 settings 在创建任何东西之前就失败 |
| `test_a_failed_init_removes_only_what_it_created`（4 种） | 第 3 个文件写入失败（ENOSPC）、profile 目录创建失败（EACCES）、settings 原子替换失败（EIO），以及全新 Home 上替换失败；全部回到初始状态，逐字节比较，已有 bundle、共享 profile 和 settings 保留 |
| `test_console_commands_run_without_the_host_log_socket`（改） | 真实入口：`config init`、按名称和默认 `config check`，只生成配置文件；`start absent` 以退出码 2 失败，且不创建工作区 |

既有回归保持通过：
- 单文件 YAML／JSON 加载、Home 选择优先级、平台默认根目录、payload 还原（`test_application_config.py`）；
- `config check` 的覆盖、脱敏、配色、错误输出、并行配置；
- CLI 入口拒绝凭据。

### 7. 变异验证（文件临时替换后按 SHA-256 恢复）

| 变异 | 结果 |
|---|---|
| B1 bundle 不存在时回退到工作目录文件 | 被杀死 |
| B2 扩展名不算文件写法 | 被杀死 |
| B3 profile 静默替换内联段 | 被杀死 |
| B4 profile 可以再引用 profile | 被杀死 |
| B5 profile 名允许 `.` | 被杀死（`..` 逃逸） |
| B6 覆盖在组合之前应用 | 被杀死 |
| B7 init 总是覆盖默认 bundle | 被杀死 |
| B8 settings 原地写入、不做原子替换 | 被杀死 |
| B9 回滚时保留新建目录 | 被杀死 |
| B10 命名 bundle 可以改 Home | 被杀死 |
| B11 `KEY=VALUE` 被当成配置参数 | 被杀死 |
| B12 `config` 项放在脱敏边界之外 | 第一版变异写错了（仍在边界内），重写后被杀死 |
| B13 追加改为整体重写（注释丢失） | 被杀死 |
| B14 去掉"目标已存在"的预检查 | **存活**：等价变异。`open("x")` 仍会拒绝覆盖，失败后的回滚使结果相同；预检查只是让拒绝发生在动磁盘之前，作为防御保留 |

### 8. 运行结果

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`--basetemp`、检出前后对比）×1 | **283 passed**，45.8 s；检出目录前后一致 |
| `avatar-host/tests` ×5 | 0 失败（每轮 72 passed） |
| Ruff、格式、`scripts/check_workspace.py`、`uv lock --check`、对改动文件运行 pre-commit | 全部通过 |

- 环境限制：
  - console 用例在子进程里运行 `start`，需要 AF_UNIX（Host 日志 socket），与既有的 CLI 端到端用例相同；
  - 没有在 Windows、macOS 或移动端验证路径行为，名称规则和路径拼接只依赖 `ApplicationPaths`。

### 9. 限制与仍待处理

- `.env` 仍按工作目录查找（`ENV_FILE`，默认 `.env`），这是原有行为。如果 `ALPHAAVATAR_HOME` 只写在某个目录的 `.env` 里，在不同目录启动会选到不同的 Home。引用解析本身不受工作目录影响。
- settings 中已有 `default_bundle: null` 时，设置默认值会整体重写 settings，那时原有注释不保留；没有该键时用追加方式，注释保留。
- 拒绝覆盖时只报告遇到的第一个已存在文件。
- `config check` 的输出新增了 `config` 一行和 JSON 的 `config` 键；其他字段不变。
- 没有新增配置展示命令，也没有 profile 的列表或删除命令。

### 10. 未做事项

- Doctor、安装器、升级回滚、App、TUI、Agent 集成。
- 没有迁移或删除已有单文件配置、cache 或 Avatar 工作区。
- 首轮修改随 `de480ad` 提交。

### 11. `de480ad` review 收尾（基线 `de480ad`）

- review 结论：配置拆分、统一入口和启动快照符合约定；4 处 P2 修复前不验收；另有 1 处文档问题。
- review 环境：成功收集 283 项；其他回归 184 项、配置命令 37 项通过；1 条入口测试受 AF_UNIX 权限限制，替换 HostLog 边界后通过；Ruff、格式、workspace、lock 通过。

#### 11.1 问题与修复

| 问题 | 原因 | 修复 |
|---|---|---|
| P2 settings 提交后被取消，留下悬空的默认值 | `os.replace()` 成功后，异常清理仍删除了 bundle 和 profiles | settings 替换就是提交点。用同目录的临时文件判断：它还在，说明替换没有生效，全部回滚（临时文件一并删除）；它已经不在，说明已提交，保留完整配置，取消或异常照常向上传播 |
| P2 并发初始化覆盖刚设置的默认值 | 读取、判断、替换之间没有一致性保护 | 用仓库已有的 `locked_directory`（filelock）锁住 settings 目录。锁内重新读取 settings；此时已有默认值就保持不变，否则写入并替换。锁外的第一次读取只用于在已有默认值时快速返回，不加锁也不写文件 |
| P2 命名引用经符号链接越出约定目录 | 只校验了名称并拼接路径，没有检查真实位置 | 新增 `check_inside`：解析符号链接后，命名 bundle 必须位于真实的 `configs/bundles` 下，profile 必须位于真实的 `configs/profiles` 下，而这两个目录本身必须在真实 Home 内。读取（选择、组合）和 `config init` 的全部目标（bundle、profiles、settings）都做这项检查，生成时在写入任何文件之前检查。两侧都解析，所以通过别名访问 Home、在 Home 内部的链接仍然有效；显式文件不受限制 |
| P2 部分合法的 settings 格式导致初始化失败 | 追加后的文本解析失败时，没有进入重新序列化的回退 | 追加后的文本解析失败（`YAMLError`）或值不一致时，保留原有字段，重新序列化后原子替换 |
| 文档 | `config.md` 说会保留 settings 注释，但 `default_bundle: null` 等情况会重写 | `config.md` 写明：只有普通块映射会追加并保留注释，其余形式按原值重写、不保留注释；同时写明锁文件、提交边界和真实路径规则 |

- 锁文件：`settings/.write.lock` 按锁库和仓库约定保留，不手动删除，否则正在等锁的进程可能锁住一个已删除的文件。由此带来的行为变化：全新 Home 上如果在 settings 这一步失败，会留下 `settings/` 目录和其中的锁文件，其他新建内容全部清理。

#### 11.2 回归测试（`test_config_commands.py`，新增 9 项）

| 用例 | 覆盖 | 在 `de480ad` 代码上 |
|---|---|---|
| `test_cancelling_init_undoes_it_before_the_settings_commit_and_keeps_it_after[after-commit]` | 真实 `os.replace` 成功后立即抛出 `KeyboardInterrupt`：取消传给调用方；settings 指向完整 bundle，可以按默认 bundle 加载 | 失败（bundle 被删除，默认值悬空） |
| 同上 `[before-commit]` | 替换前被取消：除锁文件外逐字节回到原状，原 settings 不变 | 失败，原因只是新增的锁文件预期；原代码在这一路本来就能正确回滚 |
| `test_concurrent_inits_never_both_become_the_default` | 两个线程：alpha 即将提交时，beta 已读到"没有默认值"，用事件确定这个交错。之后 alpha 提交，beta 在锁内重新读取，保留 alpha；两者都报告 alpha 是默认 | 失败（两者都报告自己是默认） |
| `test_the_default_joins_any_valid_settings_and_keeps_their_values`（5 种） | 块映射、无结尾换行（追加，原文和注释保留）；流式映射、带 `...` 文档结束标记、`default_bundle: null`（按原值重写）。原有键值都保留 | 流式、文档结束 2 种失败（`ParserError`、`ComposerError`） |
| `test_named_references_and_init_targets_stay_inside_the_real_home` | 通过别名访问 Home、Home 内部的 profile 链接：check 和 init 正常。bundle 文件链接到外部、profile 目录链接到外部：都报错并指出位置。init 时 profile 目录或 bundles 目录链接到外部：都在写入前拒绝，文件树逐字节不变。外部的显式单文件仍可加载 | 失败（越界的 bundle 通过了检查） |

既有用例更新：
- 生成的文件清单、console 用例的文件清单加入 `settings/.write.lock`；
- 全新 Home 上替换失败时，预期留下锁文件和它所在的目录。

#### 11.3 变异验证（文件临时替换后按 SHA-256 恢复）

| 变异 | 结果 |
|---|---|
| C1 提交后仍回滚 | 被杀死（after-commit） |
| C2 settings 已暂存就不回滚 | 被杀死 |
| C3 锁内不重新检查默认值 | 被杀死（只被并发用例发现） |
| C4 去掉 settings 锁 | 被杀死（并发用例，以及锁文件预期） |
| C5 不检查 bundle 的真实路径 | 被杀死 |
| C6 不检查 profile 的真实路径 | 被杀死 |
| C7 不检查生成目标 | 被杀死 |
| C8 追加后解析失败时不回退 | 被杀死（flow、document-end） |
| C9 不解析 Home 别名 | 被杀死（别名 Home） |

（第一版 C3 把 settings 整个清空，作用过宽，因此重写为 C3'，只去掉锁内的重新检查；表中记录的是重写后的结果。）

#### 11.4 运行结果

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`--basetemp`、检出前后对比）×1 | **292 passed**，45.9 s；检出目录前后一致 |
| 新增用例与失败回滚用例（13 项）×30 | 0 失败 |
| `avatar-host/tests` ×5 | 0 失败（每轮 81 passed） |
| Ruff、格式、`scripts/check_workspace.py`、`uv lock --check`、对改动文件运行 pre-commit | 全部通过 |

- 修改文件：`configs/bundles.py`、`configs/template.py`、`avatar-host/tests/test_config_commands.py`、`docs/cli/config.md`、本日志。
- 并发用例用同一进程内的两个线程；filelock 在 Linux 上用 flock，不同的打开文件描述之间互斥。没有做多进程或 Windows 上的锁验证。
- 本轮修改随 `3c40fda` 提交。

### 12. `3c40fda` review 收尾（基线 `3c40fda`）

- review 结论：
  - §11 的四项主要修复成立。
  - 持久保留 `settings/.write.lock`、失败后留下 settings 目录和锁文件，都可以接受。
  - 两个独立进程的互斥已在 review 环境验证：两边最终都保留第一次设置的默认 bundle。
  - 剩两处路径边界和一处测试屏障，修复前不验收。
- review 环境：成功收集 292 项，原生选跑 230 项全部通过；提交前后取消、合法 settings 格式、真实多进程互斥通过；Ruff、格式、workspace、lock 通过。

#### 12.1 问题与修复（`configs/template.py`）

| 问题 | 原因 | 修复 |
|---|---|---|
| P2 锁文件本身是符号链接时，会清空它指向的文件 | 打开锁（filelock 3.20.0）会截断锁文件；进入锁之前没有检查 `.write.lock` | 进入锁之前，`.write.lock` 是符号链接就拒绝（`ConfigReferenceError`），指向 Home 内的链接也一样，例如指向 `settings.yaml`。此时尚未提交，本次已写的配置全部回滚。正常的锁文件照常保留 |
| P2 生成与读取的目录边界不一致 | 生成时 bundle 和 profile 的目标只按整个 `configs` 校验，读取时却分别要求在 `configs/bundles`、`configs/profiles` 内 | 生成时 bundle 按 `bundles_dir`、profile 按 `profiles_dir`、settings 按 `settings_dir` 校验，与读取用同一组目录，生成的默认配置一定能加载 |
| 测试屏障 | 并发用例在真正读取 settings 之前就发出"读取完成"事件，存在变异误通过的窗口 | 改为先读取，记录读到的默认值，再发出事件；用例另外断言 beta 第二次读取时确实没有默认值。加强后，"锁内不重新检查"这个变异 10 次全部被发现 |

- 观察（不在本批范围）：agents 的 `locked_directory` 还被 Memory 的导出和 graph 存储使用，锁文件位于工作区目录，同样没有检查符号链接。本批只在 settings 的入口检查。

#### 12.2 回归测试

| 用例 | 覆盖 | 在 `3c40fda` 代码上 |
|---|---|---|
| `test_a_linked_settings_lock_is_refused_and_what_it_points_to_is_kept[outside]` | `.write.lock` 链接到 Home 外的文件：init 以退出码 2 拒绝；目标文件内容、settings 和整个文件树逐字节不变 | 失败（目标文件被截断） |
| 同上 `[settings]` | `.write.lock` 链接到 `settings.yaml` 本身：拒绝，settings 不变 | 失败 |
| `test_named_references_and_init_targets_stay_inside_the_real_home`（扩展） | `profiles/zeta` 链接到 `configs/bundles/shared`：init 拒绝并指出 `zeta/loop` 越界，文件树不变 | 失败（init 成功，生成的配置无法加载） |
| `test_concurrent_inits_never_both_become_the_default`（加强） | 屏障改为在读取之后发出；断言 beta 第二次读取时没有默认值 | 通过（修复本身原已成立） |

#### 12.3 变异验证

| 变异 | 结果 |
|---|---|
| D1 不拒绝符号链接锁文件 | 被杀死（两种情形） |
| D2 生成目标按整个 `configs` 校验 | 被杀死 |
| C3' 锁内不重新检查（只运行并发用例，重复 10 次） | 10/10 被杀死 |

#### 12.4 运行结果

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`--basetemp`、检出前后对比）×1 | **294 passed**，46.9 s；检出目录前后一致 |
| 并发、锁文件链接、真实路径、取消等相关用例（6 项）×30 | 0 失败 |
| `avatar-host/tests` ×5 | 0 失败（每轮 83 passed） |
| Ruff、格式、`scripts/check_workspace.py`、`uv lock --check`、对改动文件运行 pre-commit | 全部通过 |

- 修改文件：`configs/template.py`、`avatar-host/tests/test_config_commands.py`、`docs/cli/config.md`（写明生成目标的目录规则和对锁文件链接的拒绝）、本日志。
- 本轮修改随 `85d7fcf` 提交。

### 13. `85d7fcf` 复核与验收

- 结论：**T-10A 已验收**，验收提交 `85d7fcf`，没有新增阻断。
- 复核确认：
  - `.write.lock` 指向 Home 内外的目标时都被拒绝，目标内容和文件树不变；
  - profile 跨到 bundles 子树时，init 在写入前拒绝；合法的内部链接、Home 别名、外部单文件仍正常；
  - 并发屏障已修正；单独撤掉锁内重新检查后，测试能发现。
- 持久保留 `settings/.write.lock` 的做法被接受。
- review 环境（filelock 3.20.0）：收集 294 项，原生选跑 232 项全部通过；Ruff、格式、workspace、lock 通过，仓库无修改；原生 IPC 全量仍未独立复跑。
- 遗留（既存问题，不阻塞本批）：Memory 的导出和 graph 存储共用 `locked_directory`，存在同样的锁文件符号链接风险。review 建议下一批先只修共享的 `locked_directory` 及必要的调用回归，再进入基础 Doctor。

---

## T-10A1 共享 `locked_directory` 的最小缺陷修复

- 基线：`85d7fcf`（T-10A 验收提交）。开始时工作区有一处未提交的改动，即本日志里 T-10A 的验收收口（§13），已保留。
- 依赖：`uv.lock` 锁定 filelock 3.20.0，`.venv` 实际安装的也是 3.20.0（`uv pip list`），测试全部用这个版本运行。
- 范围：只改共享锁工具，补 helper 和 Memory 两条真实调用路径的回归。Memory 的抽取和存储逻辑、配置结构都不变。

### 1. 缺陷与修复

filelock 3.20.0 在 Unix 上获取锁时，按路径用 `O_RDWR | O_TRUNC` 打开锁文件（路径不存在时再加 `O_CREAT`），之后执行 `fchmod`，打开时会跟随符号链接。用这个版本直接实测（不经过 helper）：

| 预置的 `.write.lock` | 直接用 `FileLock` 的结果 |
|---|---|
| 链接到已有文件（权限 0640） | 目标内容被截断为空，权限被改成 0644 |
| 悬空链接 | 在链接指向的位置新建了文件 |

settings 在 T-10A 已经单独防护，但 Memory 的 Markdown 导出（`storage/markdown/export.py`）和 graph 存储（`storage/graph/graph_store.py`）仍走未防护的共享工具。

修复（`avatar-agents/alphaavatar/agents/utils/files/atomic.py`）：
- `locked_directory()` 在打开锁之前检查 `.write.lock`，只要它是符号链接就拒绝，抛出 `OSError(ELOOP, …, filename=<锁文件路径>)`。指向目录内、目录外的链接和悬空链接都拒绝，不改动链接本身和它指向的文件。
- 正常的锁文件照常持久保留，不手动删除。
- 超时、互斥、异常时释放锁、只在线程里同步使用的约定都不变。

上报：
- Markdown 导出和 graph 存储直接抛出这个 `OSError`。
- `MemoryExportSink` 把两者的失败汇总成 `ExceptionGroup("Memory export failed")` 上报，这是原有行为。

settings 的入口保留自己的检查，所以那里仍然先给出 `ConfigReferenceError` 的提示。

已知限制：检查和打开之间存在很短的竞态窗口。如果有人恰好在这段时间里换入链接，仍然拦不住。要完全消除，需要锁库以 `O_NOFOLLOW` 方式打开，这超出本批"最小修复"的范围。本修复挡住的是事先就存在的链接，比如残留的、从备份恢复的或同步工具带来的链接。

### 2. 回归测试（全部用隔离的临时目录和离线数据）

`avatar-agents/tests/test_locked_directory.py`（新增，7 项）：

| 用例 | 覆盖 |
|---|---|
| `test_a_held_lock_excludes_others_and_its_file_stays_after_release` | 持锁期间，同一进程内另一次获取会等到超时而不会进入；释放后锁文件仍在，可以再次获取 |
| `test_leaving_the_lock_by_an_exception_releases_it`（`RuntimeError`、`KeyboardInterrupt`） | 异常离开后锁已释放，以零超时就能再次获取 |
| `test_a_linked_lock_file_is_refused_and_left_as_it_was`（目录内、目录外、悬空） | 抛出 `ELOOP`，带锁文件路径，受保护的代码块没有执行；链接和指向不变；目标内容和权限（0640）不变；悬空的目标没有被创建 |
| `test_two_processes_exclude_each_other` | 另一个独立解释器持锁（就绪和释放都用文件闸门）：本进程获取超时；放开闸门后能获取 |

`avatar-plugins/perception/avatar-plugins-memory/tests/test_memory_export_locks.py`（新增，7 项）：

| 用例 | 覆盖 |
|---|---|
| `test_each_export_writes_under_the_lock_and_keeps_its_file`（markdown、graph） | 连续两次导出，正常写出文档和 JSONL，锁文件保留 |
| `test_a_linked_lock_stops_an_export_before_any_protected_write`（markdown、graph） | 锁文件链接到外部文件：抛出 `ELOOP`；外部文件、链接、已有的 `memories.jsonl` 和整个文件树逐字节不变，没有任何新的写入 |
| `test_the_export_sink_reports_both_refusals` | `MemoryExportSink` 以 `ExceptionGroup` 上报两个 `ELOOP`，两个目录都没有写入 |
| `test_a_failed_graph_export_releases_its_lock` | 损坏的 JSONL 让导出在锁内失败；修好文件后再次导出成功（锁如果没释放，第二次会等满超时后失败） |
| `test_a_cancelled_export_finishes_under_another_processs_lock_then_releases_it` | 另一个进程持有 Markdown 目录的锁。graph 已完成后，Markdown 没有任何写入；此时取消 sink、放开闸门：取消的调用方等受保护的写入完成后才收到取消；随后的导出正常，锁文件保留 |

`avatar-agents/tests/lock_holder.py`（新增辅助模块）：在独立解释器中持锁，直到测试打开闸门，并在 `finally` 中回收子进程。

settings 已有的回归（锁文件链接两种情形、并发默认值、提交前后取消、失败回滚 4 种）全部通过。

### 3. 反向验证

- 把 `atomic.py` 的检查临时改成 `if False:`，运行上面两个新文件和 settings 的锁文件链接用例：
  - 6 个与链接相关的用例全部失败：helper 的目录内、目录外、悬空 3 种，Markdown 和 graph 导出 2 种，以及 sink 上报 1 种；
  - settings 的 2 个用例仍然通过，因为 settings 有自己的检查；
  - 其余 8 项通过。
- 随后逐字节恢复文件，用 `cmp` 确认一致。

### 4. 运行结果

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`--basetemp`、检出前后对比）×1 | **308 passed**，51.2 s；检出目录前后一致 |
| 新增 14 项和 settings 锁回归 9 项（共 23 项）×20 | 0 失败 |
| Memory 插件测试和 Host 测试 | 112 passed |
| Ruff、格式、`scripts/check_workspace.py`、`uv lock --check`、对改动和新增文件运行 pre-commit | 全部通过 |

- 修改文件：`avatar-agents/alphaavatar/agents/utils/files/atomic.py`；新增 `avatar-agents/tests/lock_holder.py`、`avatar-agents/tests/test_locked_directory.py`、`avatar-plugins/perception/avatar-plugins-memory/tests/storage/test_export_locks.py`；本日志。
- 测试按领域放置（用户补充要求）：Memory 的导出与 graph 存储回归放在 `memory/tests/storage/test_export_locks.py`，最初的位置是 `tests/test_memory_export_locks.py`。共享 helper 的测试只有一个文件，按"小目录保持简单"留在 `avatar-agents/tests/` 顶层；`lock_holder.py` 被两个包的测试共用，留在已配置的 pythonpath 根目录。移动后又做了一次反向验证：去掉保护后 6 项失败，恢复后全部通过。
- 验证限制：
  - 只在 Linux 上验证（filelock 用 flock）；没有验证 Windows 或移动端，Windows 版 filelock 的打开方式不同，未测；
  - 跨进程只用同一台机器上的两个解释器；
  - 原生 IPC 全量不在本批范围。
- 未做：Doctor、凭据管理、安装升级、App。
- 本批修改没有 commit 或 push。

---

## T-10T 测试整理（只改测试）

- 基线：`85d7fcf`；与 T-10A1 的改动同在一个工作区，但文件互不重叠。T-10A1 只涉及 `atomic.py` 和它新增的 3 个测试文件，其余都属于本批。
- 本批不改任何生产代码，也不新增生产接口。
- 依据：用户要求测试按职责整理，并只保留必要测试。分两步：第一步只调整结构、覆盖不变；第二步审查必要性。

### 第一步：结构整理（覆盖不变）

| 原位置 | 新位置 | 说明 |
|---|---|---|
| `avatar-host/tests/test_config_commands.py`（1042 行） | `configs/test_bundles.py` | bundle、profile、默认 bundle：选择、生成、失败边界、快照冻结 |
| 同上 | `configs/test_projection.py` | 安全投影、凭据不改写固定字段、推理计划校验与快照 |
| 同上 | `cli/test_check.py` | `config check` 的摘要、失败输出、配色、各输出流 |
| 同上（console 用例）与 `test_cli_entrypoint.py` | `cli/test_entrypoint.py` | console 入口：导入开销、凭据不外露、收敛后的命令 |
| `avatar-host/tests/test_application_config.py` | `configs/test_loading.py` | 加载、Home 选择、快照还原 |
| 原文件中共用的样例和辅助函数 | `avatar-host/tests/config_samples.py` | 虚构凭据样例、`CONFIG`、`SECTIONS`、`write`、`files` |
| 原文件中共用的 fixture | `avatar-host/tests/conftest.py` | `sandbox`、`credentials`；只在一个文件里用的 fixture 留在原处 |
| `avatar-agents/tests/test_inference_parallel.py`、`test_inference_runtime.py`、`test_runner_launch.py`、`test_runner_process.py`、`test_runner_stress.py` | `runtime/inference/test_parallel.py`、`test_runtime.py`、`test_launch.py`、`test_process.py`、`test_stress.py` | 推理进程、Runtime、并行、启动输入、压力 |
| `inference_runner_samples.py`、`launch_runner_samples.py` | `runtime/inference/` | 模块名不变，spawn 子进程按原名导入 |
| `avatar-agents/tests/test_runtime_lifecycle.py` | `runtime/test_lifecycle.py` | AvatarRuntime 生命周期，不属于推理 |

- `pyproject.toml` 的 pythonpath 增加 `avatar-agents/tests/runtime/inference`（Runner 样例）和 `avatar-host/tests`（`config_samples`）。根 `conftest.py` 的环境、网络、进程、任务隔离守卫不变。
- 其他目录（Core、Persona、Router、Context、Loop、Memory 其余文件）每个只有 1～7 个文件，职责已经清楚，保持原样，不为单个文件加一层目录。
- 拆分方法：用脚本按 AST 取出每个顶层定义的原文（连同装饰器和紧挨着的注释）原样拼接，导入部分手写；没有改动任何函数体。

核对：
- 全部 487 个顶层定义（测试、fixture、辅助函数、常量）在整理前后的 AST 逐一相同，没有丢失、修改或新增。
- 收集到 308 个用例，与基线的用例名集合完全一致，没有重复收集。
- 全量（CI 方式）308 passed，检出目录前后一致。
- 每个新目录单独运行都通过：`cli` 15、`configs` 54、`runtime/inference` 44、`runtime` 47、`memory/tests/storage` 7。
- 从仓库外的工作目录运行推理与 Host 生命周期用例（真实 spawn），20 passed。

### 第二步：必要性审查

改动（共 6 处，均不删除用例）：

| 改动 | 理由 | 仍由谁覆盖 |
|---|---|---|
| 合并推理测试中逐字相同的辅助函数，放进 `runtime/inference/inference_checks.py`：`children`、`descriptors`、`wait_until` 各 3 份，`assert_released`、`settled` 各 2 份，`test_process` 的 `open_descriptors` 与 `descriptors` 只差注释；三个文件的 `HANG_GUARD = 30` 也改为引用该模块 | 同一检查维护多份副本，改一处就可能漏改其他 | 行为不变；压力测试的 `wait_until` 防挂上限从 60 s 变为 30 s，它只等一个闸门被进入，其他测试也用 30 s。`journal`、`service`、`limits`、`test_process` 自己的 `assert_released` 各文件确实不同，保留 |
| `test_runtime.py::test_repeated_start_stop…` 从 3 轮改为 2 轮 | 第 3 轮与第 2 轮完全相同，2 轮已经证明完整关闭后能重新启动、换了新进程 | 本用例保留同进程竞争者的拒绝、端点文件删除、每轮新进程、资源回收；更长的重复由 `test_stress.py::test_repeated_runtime_start_stop…`（`--stress-seconds`）负责 |
| `cli/test_entrypoint.py`：基础用例不再单独以子进程运行 `--help`，console 用例补上 `--help` 的退出码断言 | `--help` 原来以子进程跑了两次；导入探针也在进程内运行 `--help`、`--version` | 探针（不导入重依赖）、基础用例的 `--version` 子进程、console 用例的 `--help` 退出码和命令结构 |
| `cli/test_check.py` 与 `configs/test_projection.py`：按行号位置取输出行的 5 处断言改为按内容匹配；写死的"7 runners"改为从同一份 JSON 报告推导 | 行号和 runner 数量取决于其他插件和输出顺序，与被测风险无关 | `test_check_reports_valid_and_invalid…` 仍逐行固定完整的文本格式（文档化的契约） |
| Memory `test_finalization_extracts…without_background_updates`：删除断言启动后私有任务名完整集合的那一段 | 绑定内部任务命名 | 同一用例的行为断言：154 条输入全部保留，stop 之前 conversation 和 tool 模型都没有收到 prompt |
| Memory 两个"一个 context 失败后 Store 仍为其他 context 开启"的用例：删除 `>= {"memory_outbox:index", "memory_outbox:export"}` | 同上 | 同一用例里的 `not stopping.done()`，以及放行后其他 context 的 checkpoint 仍成功提交 |

审查后保留：

| 候选 | 保留理由 |
|---|---|
| 压力测试的启停场景与普通启停用例 | 压力测试在默认 0 秒时只跑 1 轮，那一轮的检查被普通用例覆盖；但它是 T-9 要求的显式时长压力报告场景，普通用例则有竞争者、端点文件、新进程等独有断言 |
| `test_runtime` 与 `test_parallel` 的部分启动失败 | 前者按 method 检查启动状态和"后续 method 从未启动"，后者按 worker 检查并覆盖初始化中取消，层级不同 |
| `test_parallel::test_close_is_idempotent…` | 独有的重复关闭、worker 与通道回收、在途请求取消 |
| 多处快照还原 | `test_loading` 两个用例分别覆盖显式 cache/workspace 根目录，以及环境变化后输入保持冻结；`test_projection` 覆盖并行覆盖项经过快照；`test_bundles` 覆盖 profile 被删除后仍能还原，风险各不相同 |
| `cli/test_entrypoint` 的 dev 凭据用例与 `cli/test_check` 的错误输出用例 | 入口不同（`dev` 子进程与进程内 `config check`），输出边界也不同 |
| Router 的 `tts:answer` 任务名、Memory 的 `assert not memory_tasks()` | 在 runtime 关闭可能掩盖泄漏之前，证明组件回收了自己的任务的唯一观察点，属于用户允许保留的必要观察点；Persona 那处任务名只用于泄漏时的报错信息 |

核对：
- 用例集合与第一步相同，仍是 308 项，没有重复。顶层定义从 487 个变为 475 个：删除 18 个重复定义，共享模块新增 6 个。
- 全量（CI 方式）308 passed，45.6 s，检出目录前后一致。
- 每个目录单独运行都通过：Core 42、Agents 69、runtime 47、runtime/inference 44、Host 83、cli 15、configs 54、Memory 29、storage 7。
- 从仓库外目录运行 spawn 场景，20 passed。
- Ruff、格式、workspace、lock、对改动和新增文件运行 pre-commit，全部通过。

### 发现的既存问题（未修，建议单独开批）

- 整理过程中，单独运行 `cli/` 时 `test_rejected_configuration_secret_never_reaches_cli_output` 偶发失败：`alphaavatar dev` 以退出码 2 结束，但输出里缺少最后一条错误诊断。
- 判定为既存问题：16 核满载下，HEAD 原文件 10 次失败 5 次，移动后的文件 10 次失败 6 次；空闲时单独运行（各 20 次）、shell 中直接运行 `alphaavatar dev`（30 次）都没有失败。
- 可能原因：`HostLog.close()` 设置停止标志后，写线程可能在读到 socket 里最后一条记录之前就退出了。
- 影响：机器负载高时，启动失败的原因可能不显示；这个用例在负载较高的 CI 上可能偶发失败。
- 本批只改测试，没有修复，也没有放宽该用例。

### 未做

- 没有修改生产代码；没有引入测试基类或 mock 框架。
- 本批修改没有 commit 或 push。

---

## T-10A1、T-10T 复核与验收（`b46c4ea`）

- 结论：**T-10A1 和 T-10T 都已验收**，验收提交 `b46c4ea`。
- T-10A1：
  - 使用 filelock 3.20.0，helper 与 Memory 两条真实调用路径的 14 项回归通过；
  - 链接目标的内容和权限保持不变；
  - 跨进程互斥正常，异常和取消后锁都能释放。
- T-10T：
  - 独立对照确认，原有 294 个参数化用例全部保留，新增恰好 14 项，没有重复收集；
  - fixture 隔离守卫、spawn 导入和关键行为断言都保留；
  - 辅助代码的合并、对实现细节断言的删减被认为合理。
- review 环境：
  - 收集 308 项，原生选跑 246 项全部通过；
  - 另有 20 项推理测试改用测试自有的回环 TCP 监听后通过，保留真实 spawn；
  - Ruff、格式、workspace、lock 通过，仓库无修改；
  - 原生 IPC 全量未独立复跑。
- Host 日志丢失确认为既存 P2，登记为 KD-16（统一 KD 表在 2A 日志）：
  - 停止前的最后一次 `select` 返回空之后，写线程可能直接退出，漏掉随后才入队的最后一条错误日志；
  - review 用线程屏障确定性复现了这一交错，不需要 CPU 满载，只替换了受限的 Unix 传输边界。
- 下一步（review 建议）：先用一个小批修复日志收尾，再进入基础 Doctor。要求：
  - 退出前重新确认队列已排空；
  - 保留关闭期限和脱敏；
  - 补确定性回归；
  - 现有入口测试的诊断断言保留。

---

## KD-16 Host 日志关闭时丢失最后一条诊断

- 基线：`84f2c6d`（T-10A1、T-10T 验收之后的最新提交），开始时工作区干净。
- 范围：只改 `avatar-host/alphaavatar/host/log/runtime.py` 的收尾，另加必要的回归测试。没有改 dev/start，也没有新增生产观测接口。

### 1. 竞态与修复

原有交错：
1. 写线程的一次 `select` 返回"无可读数据"；
2. 最后一条诊断随后进入接收 socket（`LogClient.emit` 在调用线程里同步 `sendto`，返回时记录已入队）；
3. `close()` 关闭客户端，然后设置停止标志；
4. 写线程处理第 1 步的空结果，看到停止标志后直接退出，没有消费已入队的记录。

后果：无效配置启动时，进程照常以退出码 2 结束，但不打印错误原因。

修复（`HostLog._listen`）：
- 每轮在 `select` 之前读取停止标志。只有在停止之后才开始、且结果为空的那次等待，才能作为队列已排空的证据并退出。
- `close()` 在最后一条记录入队之后才设置停止标志，所以这次等待之前的记录一定会被读到并写出。
- 有界批处理（每批 256 条）、`shutdown_timeout`、期限到时明确报错（`Diagnostic log writer did not drain before its deadline`）、写入失败的上报、脱敏、终端和文件输出格式、CLI 退出码都不变。持续有输入时，写线程不会退出，`close()` 到期限时明确报错，不会静默丢记录后报告关闭成功。

### 2. 回归测试（验证后已按 T-10T2 规则移出项目）

下面两个用例用来验证修复，验证完成后已从项目中移除（见 T-10T2），副本暂存在 scratchpad 的 `t10t/removed/test_host_log.py`，不进入仓库。

| 用例 | 覆盖 |
|---|---|
| `test_a_record_queued_after_an_empty_wait_is_written_before_close_returns` | 用 `select` 包装确定性构造交错：写线程拿到一次空结果后，先停住，直到 `close()` 设置了停止标志才把空结果交回去。断言最后一条诊断在 `close()` 之前已入队（从接收 socket 可读），`close()` 正常返回时它已写出，socket 目录已回收 |
| `test_close_under_unending_input_fails_at_its_deadline_and_the_writer_still_exits` | 写线程的 `select` 一直报告可读，相当于输入永不停止：`close()` 在 0.1 s 期限到时明确报错；输入停止后写线程自行退出，socket 目录回收 |

- 正常关闭的对照复用已有的 `test_local_endpoints.py::test_host_log_endpoint_fits_and_is_released`（写一条记录后关闭，断言它被写出、资源被释放）。
- 写入失败和脱敏的代码路径这次没有改动，没有新增测试。
- 入口用例 `cli/test_entrypoint.py::test_rejected_configuration_secret_never_reaches_cli_output` 的诊断断言原样保留。
- 测试读取了 `HostLog` 的私有成员 `_thread`、`_stop`、`_socket`、`_finished`。它们只用来构造和观察确定性时序，属于必要的观察点，没有为此新增生产接口。

### 3. 反向验证

- 把修复改回原逻辑（`elif self._stop.is_set()`），把新文件运行 10 次：
  - 竞态用例 10/10 失败，失败点是"记录已入队但未写出"；
  - 期限用例 10/10 通过，说明有界关闭本来就是这个行为，这次没有改变它。
- 恢复后用 `cmp` 确认文件逐字节一致；修复后两项各运行 30 次，0 失败。

### 4. 运行结果

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`--basetemp`、检出前后对比）×1 | **310 passed**，46.9 s；检出目录前后一致 |
| `test_host_log.py` ×30（移出前） | 0 失败 |
| Host 日志、本地端点和 CLI 定向测试 | 22 passed |
| 补充：16 核满载下运行入口用例 ×10 | 0 失败（修复前 HEAD 原文件在同样条件下 10 次失败 5 次）；只作参考，不能代替确定性复现 |
| Ruff、格式、`scripts/check_workspace.py`、`uv lock --check`、对改动和新增文件运行 pre-commit | 全部通过 |

- 限制：
  - 只在 Linux（AF_UNIX 数据报）上验证；
  - 修复保证的是 `close()` 设置停止标志之前已入队的记录；之后才到达的记录（例如仍在运行的子进程发来的）不在保证范围内，这与需求的范围一致。
- KD-16 标为"已修复，待复核"，不提前关闭。
- 本批修改没有 commit 或 push。

---

## T-10T2 只为修小 BUG 的测试移出项目

- 基线：`84f2c6d`，与 KD-16 修复同在一个工作区。本批只删测试和不再使用的测试辅助代码，没有改动任何生产代码。
- 依据：用户要求测试中只为修小 BUG 而存在的非必要测试，不能留在项目中，测试完就删除或移到其他地方；这适用于所有测试目录，不只是 `avatar-host/tests`。
- 判断标准：
  - 移出：在修复轮次中为局部小缺陷加的用例，并且它的长期风险已由其他用例覆盖，或者风险本身很小。
  - 保留：对外契约、安全边界（符号链接越界、脱敏）、资源回收、身份与数据完整性（KD-14、KD-13、KD-10 等）。
- 已提交的被移出用例都能在 git 历史 `b46c4ea` 中找到；本批新增的 KD-16 用例副本暂存在 scratchpad，不进仓库。

| 移出的用例 | 原因 | 仍由谁覆盖相关风险 |
|---|---|---|
| `cli/test_check.py::test_each_stream_detects_its_own_terminal`（×2） | T-8 修复轮次的小问题：stderr 单独判断终端以决定是否着色 | `test_only_an_enabled_terminal_gets_styles_and_json_stays_plain`（着色契约） |
| `configs/test_projection.py::test_credential_values_never_rewrite_fixed_fields` | T-8 修复轮次：凭据值与固定字段名相同时，误把字段名替换掉 | `test_safe_projection_keeps_useful_settings_without_credentials`、`cli/test_check.py::test_check_summary_passes_the_same_output_boundary`（脱敏契约） |
| `configs/test_bundles.py::test_cancelling_init_undoes_it_before_the_settings_commit_and_keeps_it_after`（×2） | T-10A 修复轮次：只在 settings 替换前后被打断这一狭窄时刻才出现 | 提交前回滚由 `test_a_failed_init_removes_only_what_it_created`（settings 替换失败、全新 Home）覆盖 |
| `configs/test_bundles.py::test_concurrent_inits_never_both_become_the_default` | T-10A 修复轮次：线程交错下的默认值竞争 | 锁保留在生产代码；锁本身的互斥由 `test_locked_directory.py::test_two_processes_exclude_each_other` 覆盖 |
| `configs/test_bundles.py::test_the_default_joins_any_valid_settings_and_keeps_their_values`（×5） | T-10A 修复轮次：流式映射、文档结束标记等格式的回退 | 追加并保留注释由 `test_init_never_overwrites_reuses_directories_and_keeps_an_existing_default` 覆盖 |
| `configs/test_bundles.py::test_a_linked_settings_lock_is_refused_and_what_it_points_to_is_kept`（×2） | T-10A 修复轮次；同类风险已由共享入口统一防护 | `test_locked_directory.py::test_a_linked_lock_file_is_refused_and_left_as_it_was`（目录内、目录外、悬空） |
| `test_local_endpoints.py::test_host_log_construction_failure_releases_its_directory`（×2） | KD-15：socket 创建失败时私有目录的清理 | 无单独覆盖，风险小；缺陷保持关闭 |
| `test_host_log.py`（2 项，整个文件） | KD-16：验证用例，验证后移出 | 入口用例 `cli/test_entrypoint.py::test_rejected_configuration_secret_never_reaches_cli_output` 的诊断断言 |
| `runtime/inference/test_parallel.py::test_executor_close_returns_after_its_running_and_locally_queued_calls_left` | T-9 修复轮次：本地排队调用比 `close()` 晚约 0.5 ms 退出 | Executor 关闭与在途请求取消由 `test_close_is_idempotent_and_reclaims_every_worker_and_channel` 覆盖 |
| `runtime/inference/test_process.py::test_cancelled_initialization_is_terminated_without_a_drain_wait` | O-1：初始化中取消要等满排空期限的延迟问题 | 初始化中取消后的资源回收由 `test_parallel.py::test_partial_start_failure_and_cancelled_initialization_release_every_worker` 覆盖；就绪 Runner 正常收尾由 `test_ready_runner_still_closes_through_its_drain_path` 覆盖 |
| `runtime/inference/test_runtime.py::test_mixed_close_drains_ready_runners_and_terminates_initializing_ones`（×2） | O-1 在 Runtime 层的对应用例 | 同上 |
| Router `test_speech_synthesis.py::test_revoked_answer_awaiting_tts_first_audio_is_interrupted_not_failed`、`test_provider_self_cancellation_on_an_active_output_remains_a_failure` | KD-12（低严重度）：打断时的原因标签和 ERROR 日志，后者是它的对照 | 打断时撤回旧 PCM 和文本、仍完成收尾由 `test_interrupted_speech_withholds_old_pcm_and_text_but_settles_closing_facts` 覆盖 |

随之删除的测试辅助代码：`test_runtime.py` 的 `CLOSING` 常量、样例中的 `GateInitRunner`（只服务于被移出的 O-1 用例），以及 Ruff 清理掉的、因此不再使用的导入。

审查后保留（不属于"只为修小 BUG"）：
- `test_parallel.py::test_close_during_recovery_starts_no_worker_and_reclaims_every_one`：会遗留 Runner 进程，属于资源回收；
- `configs/test_bundles.py::test_named_references_and_init_targets_stay_inside_the_real_home`：符号链接越出 Home，属于安全边界；
- `cli/test_check.py::test_check_summary_passes_the_same_output_boundary`：脱敏边界；
- KD-14 的 audio activity 系列：语音丢失和误提交，T-7 已确定为正式回归；
- KD-13 的 alignment：影响 Agent 认为已经说出的内容；
- KD-10、KD-11、KD-5、O-7 等：身份、准入、持久化、凭据外露；
- `test_local_endpoints.py` 的端点长度用例：O-3，长 TMPDIR 和 App 沙盒下的启动兼容性。

运行结果：
- 全量（CI 方式）**287 passed**（310 − 23），45.3 s，检出目录前后一致；
- `avatar-host/tests` 68、`runtime/inference` 40、Router 32 单独运行都通过；
- Ruff、格式、workspace、lock、对改动文件运行 pre-commit，全部通过；
- 没有残留未使用的测试辅助定义（逐个检查了每个顶层定义的引用）。

- 本批修改没有 commit 或 push。
