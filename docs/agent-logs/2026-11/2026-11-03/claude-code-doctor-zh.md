# AlphaAvatar v0.6.9 Doctor — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 从 T-10B 开始，Doctor 的设计、实现、实验、测试、限制以及后续 review 收尾都记录在本文件，按时间顺序追加。
- 统一的 KD/O 表仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`；T-10A～T-10T3 记录在 [claude-code-t10-zh.md](claude-code-t10-zh.md)。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| T-10B | 基础 Doctor：静态、只读、离线的安装与配置诊断（`doctor`、`doctor <bundle或文件> [KEY=VALUE...]`、`--list`、`--json`） | 2026-11-03 | `7c53c4a` | `0579d81`、`8a66b81`；第二轮收尾未提交 | `8a66b81` review：剩一处生产误报和一处测试断言，另要求把 loop 必填项纳入 check、Doctor 文本分组；已完成，待 review。本地全量 301 passed（CI 方式，检出前后一致） |

---

## T-10B 基础 Doctor

- 基线：`7c53c4a`（T-10T3 验收）。工作区中只有 T-10T3 的验收收尾（两份旧日志），其余是本批改动。
- 范围：
  - 命令：`alphaavatar doctor`、`alphaavatar doctor <bundle名称或配置文件> [KEY=VALUE...]`、`--list`、`--json`。
  - 只做静态检查，模型、服务、设备一律报"未验证"。
  - 不做：安装器、升级回滚、Agent 自动修复、长时压力测试、真实探测和延迟指标。

### 1. 结构

| 位置 | 职责 |
|---|---|
| `avatar-host/alphaavatar/host/doctor.py` | 检查逻辑与报告结构：`CHECKS`（稳定标识、标题、是否需要配置）、`Check`、`Report`（`status`、`exit_code`、`counts()`、`to_dict()`）、`diagnose(target, overrides)`。App、TUI 可以直接调用 |
| `avatar-host/alphaavatar/host/cli/commands/doctor.py` | CLI：读取 `.env`（与 `config check` 相同）、解析参数、输出文本或 JSON |
| `avatar-host/alphaavatar/host/cli/app.py` | 注册 `doctor` 子命令，复用 `config check` 的位置参数和 `KEY=VALUE` 规则；`--list` 与配置参数同时给出时报用法错误 |

没有搭建检查插件框架：每项检查是一个返回 `Check` 的函数，`diagnose` 按 `CHECKS` 的顺序汇总。某项检查自身抛出异常时，记为该项 FAIL，内容只包含 `format_failure` 给出的类型和位置，Doctor 本身不会因此中断。

### 2. 复用的公共服务（没有另写一套配置规则）

- 选择与加载：`application_paths`、`read_settings`、`select_configuration`、`load_application`、`check_application_paths`。Home 解析、bundle／profile 组合、覆盖规则、`.env` 和平台路径选择都与 `config check`、`start`、`dev` 相同。
- 唯一的额外判断：没有参数时，先用 `read_settings` 看是否有默认 bundle。没有就报 WARN 并给出初始化命令，不把它当作配置错误。
- Runner 计划：`plan_inference_runners`，它是纯函数，不写环境变量、不起进程、不加载模型。
- 输出边界：把 `view.py` 原来私有的 `_scrubber` 公开为 `output_scrubber(config=None)`。配置中的凭据、Host 日志的脱敏规则和控制字符清理，与 `config check` 是同一个函数；没有配置时只做后两项。`describe_application`、`describe_summary` 改为调用它，行为不变。
- 配色：复用 `host.log.format` 的样式和 `use_color`。新增命名常量 `YELLOW`，Host 日志的 WARNING 颜色改为引用它，取值不变。

### 3. 检查项

| ID | 内容 | 状态规则 |
|---|---|---|
| `system.platform` | 系统、内核版本、架构；POSIX 本地 socket（Host 必需） | 非 POSIX 或没有 AF_UNIX 时 FAIL |
| `python.version` | 解释器版本、实现、路径，对照 `alpha-avatar-host` 的 `Requires-Python` | 不满足时 FAIL |
| `packages.alphaavatar` | 已安装的 `alpha-avatar-*` 包及其版本；Host 的依赖 | Host 依赖缺失或版本不符时 FAIL；包来自多个版本时 WARN |
| `config.load` | 选择、组合、覆盖、校验、只读工作区检查 | 没有默认 bundle 时 WARN（给出 `config init` 命令）；加载失败时 FAIL（细节为 `format_failure` 的输出；缺模块时提示安装） |
| `config.runners` | Runner 数量与 worker 数，汇总方式与 `config check` 相同 | 计划有效时 PASS |
| `packages.capabilities` | 已启用能力需要的包（规则见第 4 节） | 有缺失或版本不符时 FAIL，并列出安装目标 |
| `paths.home` | Home 的来源（配置文件、`application.home` 覆盖、`ALPHAAVATAR_HOME`、平台默认）、状态、所有者与权限、能否写入、默认 bundle、bundle 数量、剩余空间 | 不可写或不是目录时 FAIL；剩余空间不足 1 GiB 时 WARN |
| `paths.cache` | 缓存根目录、是否已有下载的模型、剩余空间 | 同上 |
| `paths.workspace` | Avatar 工作区 | 同上 |
| `models.runners` | Runner 模型 | 始终 SKIP："未验证"，并指向 `alphaavatar dev` |
| `services.external` | 列出 RTC、模型提供方、语音、Qdrant、工具和 MCP 等服务 | 始终 SKIP："未验证" |
| `devices.media` | 麦克风、摄像头 | 始终 SKIP："未验证"；Host 的媒体来自 RTC 参与者 |

- 目录还不存在时，检查最近一个已存在的上级目录能否写入，并报告"首次需要时创建"。
- 没有配置时，需要配置的检查报 SKIP（"未选择配置／配置未加载；见 config.load"），下一步只写在 `config.load` 里，避免重复。

### 4. 依赖检查规则

- 对每个要求的包：先查是否已安装、版本是否满足 specifier；如果是 AlphaAvatar 自己的包（`alpha-avatar-*`），再展开它的依赖，按 extra 计算 marker，每个（包，extra）只展开一次。第三方包只查是否安装和版本，不再向下展开。
- Host 的基础依赖由 `packages.alphaavatar` 检查；`packages.capabilities` 不重复报告。
- 能力与包的对应关系：
  - RTC：`alpha-avatar-host`，带上以后端命名的 extra（`livekit`）。
  - loop、context、model provider 后端：按入口点组 `alphaavatar.loop`、`alphaavatar.context`、`alphaavatar.provider` 找到提供它们的包；包里有与插件同名的 extra 时一并检查，例如 `alpha-avatar-plugins-provider[openai]`、`[langchain]`。
  - voice（vad、stt、tts 任一启用）、router、status（启用时）、character（选中时）、deepresearch、rag：各自的插件包。
  - memory、persona、MCP（启用时）：各自的插件包；插件为 `default` 时另需 `alpha-avatar-agents[vdb]`。
- Provider 后端的识别：在插件配置中，同时含有 `model` 和 `provider` 或 `backend` 的映射视为一个 provider 任务；没写 `backend` 的任务使用 `ProviderTaskConfig` 的默认后端（`langchain`）。模板中 memory 和 persona 的任务没有写 `backend`，所以会要求 `[langchain]`。
- 为了解析 specifier 和 marker，`alpha-avatar-host` 显式声明了依赖 `packaging>=24,<27`：
  - 它原本已经作为 huggingface-hub、langchain-core 等的传递依赖被安装；
  - `uv.lock` 只增加了 2 行（host 的 dependencies 和 requires-dist）；`uv lock --check`、`check_workspace.py` 通过。

### 5. 默认检查没有副作用

- 不创建文件、目录或设置；不下载、不加载模型；不启动 Host 或 Runner；不访问服务；不打开麦克风或摄像头；不构造服务客户端或本地 socket。
- 读取方式：`importlib.metadata`、入口点、`stat`、`os.access`、`shutil.disk_usage`、读取 settings 和列出 bundles 目录。
- `.env`：CLI 与 `config check` 一样调用 `init_env()`（`load_dotenv` 只补充尚未设置的变量）。`diagnose()` 本身不读 `.env`，由调用方决定。
- 导入配置插件时第三方库改写环境变量，这是已知的 O-2，与 `config check` 相同，本批没有处理。

### 6. 输出

- 文本：
  - 第一行汇总：`OK`／`WARN`／`FAIL`，以及通过、警告、失败、未验证或跳过各几项；
  - 之后每项一行（状态、ID、摘要），细节缩进显示，下一步以 `->` 开头；
  - 只有输出到终端时才着色。
- JSON：`status`、`counts`、`checks`（`id`、`status`、`summary`、`details`、`action`），与文本是同一份 `Report`。
- `--list`：只列出检查项，什么也不运行；`--list --json` 输出 `id`、`title`、`needs_configuration`。
- 退出码：0 表示没有 FAIL（允许 WARN 和 SKIP）；1 表示至少一项 FAIL；2 表示参数错误。

### 7. 实验（scratchpad 中隔离的 HOME，`env -i`）

| 场景 | 结果 |
|---|---|
| 空 Home，不带参数 | 退出码 0；`config.load` WARN，给出 `config init` 命令；系统、Python、包、Home、缓存检查 PASS；之后 Home 仍为空 |
| `config init alpha` 后运行 `doctor` 和 `doctor alpha voice.tts.speed=1.3 --json` | 9 PASS、3 SKIP（模型、服务、设备），退出码 0；Home 下没有新文件 |
| `doctor nope` | `config.load` FAIL，细节与 `config check` 相同（`Bundle 'nope' does not exist`），退出码 1 |
| 文件中有无效时区 | `config.load` FAIL，细节为 `fields: avatar.timezone`，不含输入值 |
| `doctor --list alpha` | 用法错误，退出码 2 |

### 8. 测试

新增 `avatar-host/tests/cli/test_doctor.py`，共 4 项。辅助函数每次同时运行文本和 JSON，并断言两者每一项的状态和摘要一致、ID 顺序与 `CHECKS` 相同。

| 用例 | 保护的行为 |
|---|---|
| `test_without_a_configuration_doctor_says_how_to_create_one_and_checks_the_rest` | 没有默认 bundle：退出码 0，各项状态完整固定，`config.load` 给出初始化命令；不创建文件、不构造客户端或 socket；`--list` 不运行检查（settings 损坏时仍成功）；`--list` 带配置时退出码 2 |
| `test_doctor_selects_and_loads_configurations_as_config_check_does` | 默认 bundle、命名 bundle、只给覆盖项（落到默认 bundle）、文件加覆盖项这四种调用中，来源、Avatar ID、工作区都与 `config check --json` 一致；模型、服务、设备始终为 SKIP；缺失的 bundle 与 `config check` 给出同一条错误，退出码 1；全程只读 |
| `test_missing_packages_fail_and_low_disk_space_warns_with_a_next_step` | 让 `livekit` 和 `langchain-openai` 显示为未安装：FAIL，退出码 1，细节分别归到 rtc 和 providers，下一步给出 `'alpha-avatar-host[livekit]' 'alpha-avatar-plugins-provider[langchain]'`；磁盘空间不足：三个路径检查都 WARN，退出码 0，并给出下一步 |
| `test_doctor_reports_pass_the_configuration_output_boundary` | 凭据被用作 Avatar ID、Home 路径和文件路径中有终端转义时，文本和 JSON 中没有任何凭据和控制字符；Home 来源显示为配置文件 |

- 剩余空间是机器的输入，测试用 `disk` 夹具固定它，保证结果确定。
- 测试设施的改动：
  - 把 `test_bundles.py` 里的 `home` 夹具移到 `avatar-host/tests/conftest.py`，两个文件共用；
  - `cli/test_entrypoint.py` 的命令集合断言从 `{dev,start,config}` 改为 `{dev,start,config,doctor}`，这是有意新增的命令；
  - 同一用例里通过真实的 console 入口运行 `doctor console --json`，断言没有 FAIL，并由原有的文件清单断言证明它没有在 Home 中写入任何东西。

反向验证（每次只改一处，运行 `test_doctor.py`，按 SHA-256 恢复）：

| # | 变异 | 结果 |
|---|---|---|
| D1 | 未验证的模型显示为 PASS | 配置复用用例失败 |
| D2 | 退出码忽略 FAIL | 配置复用用例失败（缺失 bundle 时得到 0） |
| D3 | 不经过输出边界 | 脱敏用例失败（显示了 `avatar vdb-fictional-0042`） |
| D4 | 加载时丢掉覆盖项 | 配置复用用例失败（`avatar alpha` ≠ `avatar renamed`） |
| D5 | 检查时创建目录 | 无配置用例失败 |
| D6 | 不按 extra 计算依赖 | 缺包用例失败 |
| D7 | 不使用默认 provider 后端 | 缺包用例失败（漏掉 providers 一行） |
| D8 | 忽略剩余空间下限 | 缺包用例中的磁盘部分失败 |
| D9 | 没有默认 bundle 时判为 FAIL | 无配置用例失败 |
| D10 | `--list` 实际运行检查 | 无配置用例失败（settings 损坏时返回 1） |

### 9. 运行结果

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`--basetemp`、检出前后对比）×1 | **300 passed**（296 + 4），46.7 s；检出目录前后一致 |
| `avatar-host/tests` | 80 passed |
| `test_doctor.py` ×10 | 0 失败 |
| Ruff、格式、`scripts/check_workspace.py`、`uv lock --check`、对改动和新增文件运行 pre-commit | 全部通过 |

### 10. 文档

- `docs/cli/doctor.md` 重写，分成已实现和计划中两部分：
  - 已实现：用法、检查表、状态和退出码、文本示例、JSON 结构、不做的事；
  - 计划中：`--runtime`、`--live`、显式探测和延迟指标。
  - 原来的 `--format json` 改为已实现的 `--json`。
- `docs/cli/config.md`：说明 `doctor` 与 `config check`、`start`、`dev` 使用同一个配置参数。
- `README.md`：Step 1 增加 `alphaavatar doctor my-avatar`；按用户要求，删除了 `config check examples/agent_configs/voice/pipeline_openai_tools_minimal.yaml` 这一行。
- `avatar-host/README.md`：增加 `doctor` 示例，并在 Python 入口中列出 `output_scrubber` 和 `alphaavatar.host.doctor.diagnose`。

### 11. 限制与未做

- **Provider 后端的识别是结构上的约定**：只认插件配置中写出来的任务。插件内部自带的默认任务看不到；没写 `provider` 也没写 `backend` 的任务也识别不到。例如示例文件没有写 provider 任务时，`services.external` 不会列出模型提供方。
- **插件名是否已注册没有检查**：例如 memory 的插件名拼错时，静态检查只能确认插件包已安装；名字错误要到启动时才报 `Unknown plugin`。导入 character、status、tools 等插件会执行插件代码，本批不导入。
- **凭据**：不检查 `OPENAI_API_KEY`、`LIVEKIT_*` 等环境变量是否已设置，也不验证它们是否可用；这些归在 `services.external` 的"未验证"中。配置里的 `<ENV_VAR>` 占位符缺失时，与 `config check` 一样在 `config.load` 中失败。
- 剩余空间的下限固定为 1 GiB，不根据所选模型估算。
- `uv.lock` 已更新，但本机 `.venv` 中已安装的 `alpha-avatar-host` 元数据要在 `uv sync` 之后才会包含 `packaging`。这不影响运行，本批没有改动环境。
- 在 Windows 上，`system.platform` 会报 FAIL；其余检查仍然运行，但没有在 Windows 上验证。原生 AF_UNIX 全量只在本机 Linux 运行。
- 导入配置插件时改写环境变量，是已知的 O-2，与 `config check` 相同。
- 没有实现：安装器、升级回滚、Agent 自动修复、长时压力测试、`--runtime`／`--live` 探测、首 token／首音频帧／端到端延迟。
- 本批修改没有 commit 或 push，停在 review 阶段。

---

## T-10B `0579d81` review 收尾

- 基线：`0579d81`，开始时工作区干净。
- review 结论：暂不验收，三组 P2，都可以集中做小改，不调整整体架构。另有三处说明不准确。
- review 环境：收集 300 项，选跑 239 项，234 项通过。其中：
  - 4 项 Doctor 测试失败，原因是审查环境确实缺少声明的依赖；
  - 1 项未改动的语音测试首次出现时序失败，当前版本和父版本单独重跑都通过，尚未认定为本批回归。

### 1. P2 修正

| # | 问题 | 修正 |
|---|---|---|
| 1 | 依赖检查有漏报也有误报。只写 `model` 的任务实际使用默认后端，却被漏掉；补写同样的默认值后，结果反而不同。已禁用工具残留的 `init_config` 仍被扫描，其中未使用的 backend 被报成 FAIL | `_provider_backends` 不再按字典结构猜测，改为用插件启动时的 schema 校验已启用的内置插件，默认值由 schema 补齐后再收集 `ProviderTaskConfig`。所用 schema 为 realtime loop 的 `RealtimeLoopConfig`，以及默认 memory、persona 的 `DefaultMemoryConfig`、`DefaultPersonaConfig`。向量库的 embedding 是固定用默认后端构造的，所以默认 memory、persona 和启用的默认 MCP 都计入默认后端。已禁用的插件不读取。其他插件，或 schema 拒绝的配置，报为"provider backends not verified"，`packages.capabilities` 给 WARN 并指向 `alphaavatar dev` |
| 2 | 悬空符号链接被当作可创建的目录：`exists()` 跳过了失效链接 | `_directory` 向上寻找已存在的祖先时，遇到 `is_symlink()` 但无法解析的路径，就直接 FAIL（"is a symbolic link that does not resolve"）；遇到不是目录的祖先，也明确 FAIL。Home 是悬空链接时，Home 和 cache 都 FAIL |
| 3 | `.env` 读不了时，`doctor --json` 输出裸 traceback，stdout 为空 | `diagnose(..., read_env=init_env)` 在报告内读取 `.env`。失败时 `config.load` 报 FAIL，摘要为"The environment file could not be read"，细节是 `format_failure` 的类型和位置，下一步说明 ENV_FILE 应为 UTF-8 的 KEY=VALUE 文本。此时 Home 可能就定义在没读到的 `.env` 里，所以依赖它的路径检查 SKIP。JSON 照常输出，退出码 1 |

### 2. 说明更正

- `system.platform` 只确认 AF_UNIX API 存在，不打开 socket，摘要改为"AF_UNIX socket API present, not opened"。
- 导入边界：用 audit hook 实测，首次导入配置插件时，第三方库会做探测：
  - `urllib3`（经 `requests`）创建并 bind 一个 IPv6 socket，用来判断是否支持 IPv6；
  - `weasyprint` 通过 `ctypes.util.find_library` 查找本地库，会运行 `ldconfig`、`gcc`、`ld`，并创建、删除临时文件。
  - 这些来自 `config check`、`start` 同样会执行的导入；Doctor 自己的检查阶段（导入之后）实测没有 socket、子进程、写文件或建目录，只有 Python 为刚改动的模块写 `__pycache__`。
  - 文档已改为"Doctor 的检查不创建……"，并写明这条导入边界。2A 日志的 O-2 已补充记录。
- 显式配置有效、但 settings 损坏时，`config.load` 是 PASS，所以提示不能再指向它。现在由 `paths.home` 报 WARN，细节给出 settings 的错误，下一步直接写出要修复或删除的 settings 文件。
- 另外发现并修正一处与 `config check` 不一致的地方：Doctor 的 `config.load` 没有执行 `config check` 的 `describe_summary`。现在也执行，两者的结论在构造上一致。现有的 persona 配置错误在加载阶段就已经失败（Runner 计划会校验 persona 设置），所以这处修正目前没有可观察的差别（见变异 F7）。

### 3. 测试

- **测试与本机安装解耦**：本机是否装全了声明的依赖，属于机器本身的状态。原测试断言 `packages.*` 为 PASS、退出码为 0，在审查环境中因此失败。
  - 改法：辅助函数对每次运行都断言"退出码为 1 当且仅当报告里有 FAIL"；退出码的取值规则直接用 `Report` 验证（只有 WARN 和 SKIP 时为 0，有 FAIL 时为 1）。
  - `packages.*` 的具体状态只在测试主动移除某个包时断言。缺包用例用"包含"判断，不要求细节完全相等。
  - 其他检查（平台、Python、配置、路径）的状态仍然精确断言。
- **新增**：`test_provider_backends_follow_defaults_and_ignore_disabled_plugins`。
  - 只写 `model` 的任务与补写默认值的任务结果相同；
  - 显式写 `backend: openai` 时要求 openai；
  - 已禁用 rag 残留的 `backend: nowhere` 不出现在结果中。
- **扩展**：
  - 配置复用用例：增加 `persona.init_config.unknown=1` 这一校验失败场景，与 `config check` 的拒绝一致；增加 settings 损坏时显式 bundle 的情况（`config.load` PASS，`paths.home` WARN）。
  - 失败用例：增加悬空链接 Home（FAIL，退出码 1）和不可读 `.env`（JSON 完整，`config.load` FAIL，路径检查 SKIP，没有 traceback）。
- `test_doctor.py` 现为 5 项。

反向验证：用一个临时测试文件把各场景拆开，分别对 `0579d81` 的两个 Doctor 模块和修正后的模块运行；文件随后删除，模块按 SHA-256 恢复。

| 场景 | `0579d81` | 修正后 |
|---|---|---|
| 只写 `model` 的任务遵循默认值 | 失败（结果中没有 provider） | 通过 |
| 已禁用工具的残留不参与检查 | 失败（出现 `nowhere`） | 通过 |
| 悬空链接 Home 报 FAIL | 失败（退出码 0） | 通过 |
| `.env` 不可读时仍输出 JSON | 失败（`UnicodeDecodeError` 直接抛出） | 通过 |
| settings 损坏、显式 bundle | 失败（Home 为 PASS） | 通过 |
| `persona.init_config` 错误与 `config check` 一致 | 通过（加载阶段已拒绝） | 通过 |

变异（每次只改一处，按 SHA-256 恢复）：

| # | 变异 | 结果 |
|---|---|---|
| F1 | 悬空链接按"不存在"处理 | 被发现 |
| F2 | 在报告之外读取 `.env` | 被发现（`UnicodeDecodeError`） |
| F3 | settings 损坏时仍报 PASS | 被发现 |
| F4a | 只计入显式写出的 backend | **未被发现**：默认 memory 和 persona 的 embedding 本身就要求默认后端，在用例中掩盖了 loop 的默认值 |
| F4b | 不计入 embedding 的默认后端 | **未被发现**：loop 只写 `model` 时同样落到默认后端，两者在用例中互相掩盖 |
| F4c | 不按 loop 的 schema 读取任务 | 被发现 |
| F5 | 摘要中没有 memory 处理器开关 | 被发现 |
| F6 | 摘要中没有 vision | 被发现 |
| F7 | `config.load` 不调用 `describe_summary` | **未被发现**：现有校验在加载阶段已经覆盖 |

T-10B 首版的变异 D1–D10 在最终代码上重跑：
- D7（基于结构的扫描）对应的代码已删除，改由 F4 覆盖；
- 其余 9 个仍全部被发现。

### 4. 用户在本轮追加的配置改动

1. **`config check` 摘要补全开关**：
   - 新增 `vision`（开关及输入方式）、`context`、`status`；
   - router 显示 audio activity、semantic addressing、visual addressing、turn taking、interruption 的开关；
   - memory 显示 retrieval、conversation、tool、environment（ENV memory）的开关；
   - persona 增加 profiler 的开关。
   - 开关都用各插件自己的 schema 读取，省略的开关显示默认值。JSON 在 `plugins` 下给出相同的值，`router` 和 `status` 由字符串改为对象。
   - 行为变化：读取 memory 开关时会校验 `DefaultMemoryConfig`，这一点 Runner 计划此前没有做。所以 `memory.init_config` 无效时，`config check` 现在就会拒绝；原来要到 `start` 才失败。
2. **`config check` 分层展示**：
   - 选择信息（config、avatar_id、home、workspace）之后，依次分为 `host`（rtc、health）、`agent`（inference）、`plugins/foundation`、`plugins/perception`、`plugins/tools`；
   - tools 拆成 deepresearch、rag、mcp 三行。
   - 层的划分来自 `alphaavatar.host.configs.LAYERS`，与 profile 布局共用同一份定义。JSON 结构不分层。
3. **profile 分层**（用户选择："host 放 host，agent 放 runtime"，tools 用一个文件）：
   - `host`、`runtime` 可以作为 profile。`profile_sections()` 取代 `plugin_sections()`，`avatar`（身份）仍只能写在 bundle 中。这改变了 T-10A 已验收的规则。
   - 错误信息改为"profiles must map sections to profile names"。
   - `config init` 按层生成 12 个 profile：

     ```
     configs/profiles/<name>/
       host/host.yaml
       agent/runtime.yaml
       plugins/foundation/{context,loop,voice,vision}.yaml
       plugins/perception/{status,router,character,memory,persona}.yaml
       plugins/tools/tools.yaml
     ```

   - 新增的 host、runtime、context、status、router、character profile 都显式写出默认值。memory 增加 `environment: {enabled: false}`；persona 增加 `profiler.enabled`、`speaker`（`enabled`、`inference_queue_size`）和 `face`（`enabled`）。
   - 生成时，host 用 `HostConfig` 校验，其余用 `AvatarConfig` 校验。
   - init 输出的 profiles 行改为指向 bundle 的 profile 根目录，并列出各层。
   - 原测试逐值比较 bundle 与旧的单文件模板，现在改为套用各插件 schema 后再比较（context、router、memory、persona），因为新 profile 把单文件里隐含的默认值写了出来。新增断言 `set(LAYERS) == profile_sections()`。
4. 此前已按要求删除 README 中 `config check examples/.../pipeline_openai_tools_minimal.yaml` 一行。用户机器上已有的 `~/.local/share/alphaavatar` 文件没有改动。

### 5. 运行结果

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`--basetemp`、检出前后对比） | **301 passed**（新增 1 项），46.6 s；检出目录前后一致 |
| `avatar-host/tests` | 81 passed |
| Doctor、check、bundles 测试 ×10 | 0 失败 |
| 真实入口 | 不可读 `.env` 时 `--json` 输出完整、stderr 为空、退出码 1；悬空链接 Home 时两项路径检查 FAIL、退出码 1；settings 损坏时显式 bundle 得到 `config.load` PASS、`paths.home` WARN |
| Ruff、格式、`check_workspace.py`、`uv lock --check`、pre-commit | 全部通过 |

### 6. 限制

- `config check` 和 Doctor 的 `config.load` 都不校验 `loop.init_config`（`RealtimeLoopConfig`）。例如没有写 `model` 的配置能通过 check，但会在启动时失败。Doctor 会在 `packages.capabilities` 中给出 WARN，并指出缺少的字段。是否把这项校验放进 `config check` 留给 review 决定。
- F4a、F4b、F7 三个变异未被发现，原因见上表。
- review 环境中那项语音时序失败不在本批范围，没有处理。
- 本批修改没有 commit 或 push，停在 review 阶段。

---

## T-10B `8a66b81` review 收尾（第二轮）

- 基线：`8a66b81`，开始时工作区干净。
- review 复验：
  - 已通过：`.env`、悬空链接、settings 问题已修复；配置分层与旧 profile 兼容。
  - 还剩一处生产误报、一处测试断言；F4a／F4b 需要在现有用例中隔离两条后端来源。
- review 环境：收集 301 项，选跑 240 项，239 项通过；失败的 1 项正是下面第 2 条的字符串断言。
- review 对上一轮四个待定项的决定：

| 项目 | 决定 | 本轮处理 |
|---|---|---|
| host、runtime 可以写成 profile | 接受，Avatar 身份留在 bundle | 不变 |
| memory 配置提前校验 | 接受；建议集中为一个小型公共纯校验函数，由 check 和 Doctor 共用 | 新增 `validate_plugin_settings`，见第 3 条 |
| router、status 的 JSON 改为对象 | 接受，明确记录结构变化 | 见第 5 条 |
| loop 缺少必填的 `model` | **纳入 check**：已知 schema 能确定的错误报 FAIL；未知插件的未验证状态仍为 WARN | 见第 3 条 |

### 1. 关闭的处理器不再计入依赖

- 问题：`collect()` 会遍历 schema 的所有字段。关闭 `memory.tool` 或 `persona.profiler` 后，残留任务里的 backend 仍让 Doctor 报 FAIL，而启动时并不会创建这些处理器。
- 修正：
  - 遍历时遇到 `enabled` 为 False 的模型就跳过它和它下面的内容；
  - 向量库 embedding 的默认后端单独计入，与处理器无关：默认 memory、默认 persona 和启用的默认 MCP 各加一次。

### 2. 测试不再假设两个安装目标紧挨着

缺包用例对 `'alpha-avatar-host[livekit]'` 和 `'alpha-avatar-plugins-provider[langchain]'` 分别断言是否包含。机器另外缺包时，建议中会多出其他目标，用例不受影响。

### 3. 公共纯校验函数 `validate_plugin_settings`，loop 必填项纳入 check

- 新增 `alphaavatar.host.configs.validate_plugin_settings(config)`：
  - 用各内置插件启动时使用的 schema，校验已启用插件的设置：realtime loop、context、router、memory、persona；
  - 返回校验后的模型，其他插件不在结果中；
  - 只读取已接受的配置。
- 错误按所在段定位，例如 `loop.init_config.model`。实现上重建 `ValidationError`，把渲染后的消息作为上下文传入，避免消息中的大括号被当作模板；输出仍只有类型和字段位置，不含输入值。
- 使用者：
  - `config check` 的加载步骤；
  - `start`／`dev` 的预检（新阶段 "validate plugin settings"，在准备目录之前）；
  - Doctor 的 `config.load`；
  - `describe_summary` 读取开关；
  - Doctor 的依赖检查。
- 因此 `config check`、`start` 和 Doctor 的结论相同：缺少 `model` 的 realtime loop 现在在 check 中就报 FAIL，`start` 退出码 2，不创建任何目录。
- Doctor 的 `config.load` 不再调用 `describe_summary`：它额外做的校验都已包含在这里，上一轮未被发现的 F7 因此不复存在。
- 所有 `examples/agent_configs` 都通过 `config check` 和 `doctor`，没有 WARN 或 FAIL。
- 测试样例：原来的 `CONFIG` 和几个最小配置都没有 loop 的 `model`，`start` 本来就会拒绝它们。`config_samples` 增加 `LOOP`，并加入 `CONFIG`；`test_check`、`test_bundles` 中需要通过 check 的最小配置也带上 `LOOP`。

### 4. Doctor 文本分组

- 分为 environment（system、python、packages.alphaavatar）、configuration（config.load、config.runners、packages.capabilities）、directories（paths.*）、not verified（models、services、devices）四组。
- 标题、缩进和配色与 `config check` 一致。
- PASS 只显示一行；WARN、FAIL、SKIP 显示细节和下一步。
- `--list` 使用相同分组；`--list --json`、报告 JSON、检查 ID 和退出码都不变。
- 分组只定义在 CLI 中（`GROUPS`）：只影响展示，库接口不变。测试辅助函数会断言每项检查都出现在文本中，所以新增检查而忘记分组时，测试会失败。

### 5. `config check --json` 的结构变化（v0.6.9）

- `plugins.router`：由插件名字符串改为对象 `{plugin, audio_activity, semantic_addressing, visual_addressing, turn_taking, interruption}`。
- `plugins.status`：由插件名字符串改为对象 `{plugin, enabled}`。
- 新增 `plugins.vision` `{enabled, input}` 和 `plugins.context`（插件名）。
- `plugins.memory` 增加 `retrieval`、`conversation`、`tool`、`environment`；`plugins.persona` 增加 `profiler`。
- 已写入 `docs/cli/config.md`。

### 6. 测试与反向验证

- `test_provider_backends_follow_defaults_and_skip_what_start_does_not_create`（原用例改写，不扩大矩阵）：
  - **只有 loop 一个来源**：memory 和 persona 使用其他插件、MCP 关闭，所以没有 embedding 的默认后端。只写 `model` 和补写默认值得到相同结果，都是 `(langchain)`。
  - **只有 embedding 一个来源**：loop 显式使用 openai，MCP 关闭，因此 `(langchain, openai)` 中的 langchain 只能来自 memory 和 persona 的 embedding。
  - **关闭的处理器和禁用的工具**：`memory.tool`、`persona.profiler` 关闭后残留的 `backend: nowhere`，以及禁用的 rag 中残留的 `nowhere`，都不会出现。
- 配置复用用例：在拒绝场景中增加"loop 缺少 `model` 的文件"，check 和 Doctor 一致，细节为 `fields: loop.init_config.model`。
- 入口用例：真实入口运行 `start <缺少 model 的文件>`，退出码 2，输出 `fields: loop.init_config.model`；随后原有的断言确认 Home 中只有 `configs` 和 `settings`。
- 测试辅助函数：
  - 断言四个分组标题依次出现；
  - 断言 PASS 的细节不出现在文本中，其他状态有细节时会显示。

变异（每次只改一处，按 SHA-256 恢复）：

| # | 变异 | 结果 |
|---|---|---|
| G1 | 关闭的处理器仍计入依赖 | 被发现（出现 `nowhere`） |
| G2 | 只计入显式写出的 backend（原 F4a） | **被发现**（只有 loop 来源时为空） |
| G3 | 不计入 memory／persona embedding 的默认后端（原 F4b） | **被发现**（只剩 `openai`） |
| G4 | `validate_plugin_settings` 不校验 loop | 被发现（check 返回 0） |
| G5 | 错误位置不带所在段 | 被发现（只有 `fields: model`） |
| G6 | `start` 预检不校验插件设置 | 被发现（退出码 1，而不是 2） |
| G7 | PASS 也显示细节 | 被发现 |
| G8 | 不显示分组标题 | 被发现 |

- 在最终代码上重跑之前的变异：
  - D1–D10（D7 已删除）、F1–F3、F5、F6 全部仍被发现；
  - F4a、F4b 已由 G2、G3 取代；F7 因 `describe_summary` 调用已删除而不复存在。

### 7. 运行结果

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`--basetemp`、检出前后对比） | **301 passed**，49.1 s；检出目录前后一致 |
| `avatar-host/tests` | 81 passed |
| `cli`、`configs` 测试 ×10 | 0 失败 |
| examples 的 `config check` 和 `doctor` | 5 个都通过，没有 WARN 或 FAIL |
| Ruff、格式、`check_workspace.py`、`uv lock --check`、pre-commit | 全部通过 |

### 8. 限制

- `validate_plugin_settings` 只覆盖 realtime loop、context、router、memory、persona。status、character 和 tools 插件的 `init_config` 仍在启动时才校验。导入它们会执行插件代码（例如 character 依赖 playwright），本批不做。
- 其他插件的 provider 后端仍报"未验证"（WARN）。
- 本批修改没有 commit 或 push，停在 review 阶段。
