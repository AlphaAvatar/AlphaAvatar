# AlphaAvatar v0.6.9 安装、升级回滚与 Doctor 阶段 — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 本阶段（T-10 起）的批次都记录在本文件，按时间顺序追加。
- 2A 阶段及 T-1～T-9 的记录，以及统一的 KD/O 表，仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`；本文件不复制 KD 表。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| T-10A | profile／bundle 配置公共能力：拆分配置生成、选择规则、引用解析 | 2026-11-03 | `62af558` | 未提交 | 待 review：本地 283 passed（CI 方式 ×1）；Host 测试 ×5 无失败；14 个变异中 12 个被杀死，另重写 1 个后被杀死，1 个为等价变异 |

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
- 本批修改没有 commit 或 push。
