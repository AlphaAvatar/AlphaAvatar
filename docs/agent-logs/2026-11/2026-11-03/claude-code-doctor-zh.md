# AlphaAvatar v0.6.9 Doctor — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 从 T-10B 开始，Doctor 的设计、实现、实验、测试、限制以及后续 review 收尾都记录在本文件，按时间顺序追加。
- 统一的 KD/O 表仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`；T-10A～T-10T3 记录在 [claude-code-t10-zh.md](claude-code-t10-zh.md)。
- 干净机器安装的主日志是 [claude-code-install-zh.md](../2026-11-05/claude-code-install-zh.md)；T-10B 范围中"不做安装器"的结论和安装集合与 `packages.*` 检查的关系记录在那里。
- T-10C `6a593f2` 第 6 节「`config init` 轻量交互入口」的方案已由交互配置日志 [claude-code-setup-zh.md](../2026-11-06/claude-code-setup-zh.md) 汇总并取代：交互配置由 `alphaavatar setup` 承担。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| T-10B | 基础 Doctor：静态、只读、离线的安装与配置诊断（`doctor`、`doctor <bundle或文件> [KEY=VALUE...]`、`--list`、`--json`） | 2026-11-03 | `7c53c4a` | `0579d81`、`8a66b81`；第二轮收尾未提交 | `8a66b81` review：剩一处生产误报和一处测试断言，另要求把 loop 必填项纳入 check、Doctor 文本分组；已完成，待 review。本地全量 301 passed（CI 方式，检出前后一致） |
| T-10C | 多模态 Doctor 自检：`alphaavatar doctor [配置]` 为唯一入口，静态检查后自行创建有期限的临时诊断会话，固定样本走生产链路，报告端到端指标、分段证据和降级结果 | 2026-11-04 | `8fdc2c2`（临时提交）；review 修复基线 `9993aad`；收尾基线 `bf79300`；真实验收基线 `6a593f2` | `9993aad`、`bf79300`、`6a593f2`；验收记录未提交 | 真实服务验收（`6a593f2`）：同一实际请求携带转录与样本帧、输出正常结束、指标齐全；视觉受阻时原配置阻塞原因与纯音频降级同时出现。严格答案校验未通过：真实 STT 丢掉样本第二句格式要求，待用户决定；另发现 KD-17（真实语音轮因 `transcript_timeout` 被丢弃）。第 9 条方案待 review。本地全量 322 passed，检出前后一致 |
| Doctor 默认运行时测试 | 静态检查后默认运行运行时测试；外部服务先列出、提示计费、明确同意（同一快照），拒绝或 `--no-metrics` 只做静态检查；非交互只认配置授权；缺模型先说明、同意后下载重跑；`—` 带原因、`Run again as JSON`；诊断进程输出不进终端 | 2026-11-06 | `2fc4f398` | 未提交（用户提交） | 待审查。真实服务验收已跑（该节第 9 小节）：安装、setup、下载、文本、关闭视觉的纯语音、拒绝、非交互均通过；音画场景卡在严格答案校验（T-10C 2.4 遗留，待用户决定）；验收发现的 4 处报告问题已修并在真实环境复验 |

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

---

## T-10C 多模态 Doctor 自检

- 基线：`8fdc2c2`（用户的临时提交）。其中包含 T-10C 第一版：`--runtime`、`RunnerProbe`、`InferenceRunner.probe()`，以及 Silero 和 Smart Turn 的专用探针。第一版过程中用户还做过两次结构调整：
  - Doctor 移入 `host/doctor/` 包，另建 `enums/`、`schemas/`；
  - probe 改为从 Runner 自身派生，不再在插件层注册。
- 本轮按用户新的 T-10C 说明重做：
  - 命令行只保留 `alphaavatar doctor [配置]`，外加 `--list` 和 `--json`。移除 `--runtime`，也不引入 `--live`。
  - 第一版的探针全部移除。Runner 沿用 `initialize()`、`run()` 和现有的资源释放接口。
  - 固定样本与结果校验只属于诊断场景。

### 1. 统一入口与授权

- **命令流程**：`alphaavatar doctor [配置]` 先做静态检查（与 T-10B 相同），再决定诊断会话这一步要不要启动。
  - 是否启动由三方面决定：配置启用的能力、本机可用条件、诊断授权。
  - 静态检查用同步的 `prepare()` 完成，不创建事件循环，也不打开本地 socket。
  - 只有需要启动时，才进入 asyncio 并接管 Ctrl+C。
  - 这样做的原因：受限主机会拒绝 AF_UNIX，而 asyncio 自身要用 socketpair。沙箱测试 `sandbox` 复现了这个问题，见第 9 节。
- **授权**：新增配置项 `host.doctor.external_services`，默认 false，写在 `config init` 生成的 host 档案里。
  - 也可以单次覆盖：`alphaavatar doctor my-avatar host.doctor.external_services=true`。
  - 未授权时诊断会话不运行。`session.start` 列出会话会访问的外部服务，并写明开启方法，同时提示可能计费。
  - 未授权时仍有一项独立检查：如果 Runner 启动不会访问外部服务，就单独启动 Runner，以检查本地模型缓存。
  - 默认 memory、persona 和 MCP 的 LanceDB Runner 在 `initialize` 时会对探针文本做一次 embedding，这是付费调用。这些插件启用时，Runner 启动也要等授权（实测见第 10 节）。
- **Library 接口**（App、TUI 可用）：
  - `diagnose()`：异步，执行完整诊断；
  - `prepare()`：同步，只做静态检查；
  - `Diagnosis.run()`：运行诊断会话；
  - `Diagnosis.report()`：不运行会话，直接给出报告。

### 2. 结构

| 位置 | 职责 |
|---|---|
| `host/doctor/doctor.py` | 检查清单 `CHECKS`、静态检查、`prepare`/`Diagnosis`/`diagnose`、报告输出边界（场景、证据一并脱敏） |
| `host/doctor/session.py` | 诊断会话：场景规划、授权判定、Runner 启动、`create_execution`、逐轮运行、降级、期限、回收 |
| `host/doctor/transport.py` | 诊断传输：`DiagnosticSource`（按 RTC 输入适配器的方式发布样本）、`DiagnosticSink`（按 RTC 传输的方式读输出边界，兼任本地音频队列并发送播放回执）、`LogTimings`（采集会话已有的计时日志） |
| `host/doctor/measure.py` | 由观测构造场景结果：阻塞阶段、端到端指标、分段、选帧、关联证据 |
| `host/doctor/samples.py` | 固定样本与任务；语音为 16 kHz 单声道 PCM16 WAV（待生成，见第 11 节），图片在代码中绘制 |
| `host/doctor/config.py` | `DoctorConfig`（`external_services`） |
| `host/doctor/enums/session.py`、`schemas/session.py` | `ScenarioOutcome`；`Metric`、`Evidence`、`ScenarioResult`、`RunnerResult` |

检查项：
- 保留的静态检查：`system.platform`、`python.version`、`packages.alphaavatar`、`config.load`、`config.runners`、`packages.capabilities`、`paths.*`、`devices.media`。
- 新增在诊断会话中运行的检查：`session.start`、`models.runners`、`session.scenarios`、`session.cleanup`。
- `models.runners` 原来恒为"未验证"，现在报告 Runner 的实际启动结果。
- `services.external` 未授权时保持未验证；授权后跟随场景结果。RTC 服务器始终不联系。
- 第一版临时提交中的 `runtime.models`、`runtime.cleanup` 已撤销。
- 文本分组：environment、configuration、directories、session、not verified。

### 3. 诊断会话复用的生产链路

- **生产组件**：配置解析为 `load_application`，另加覆盖项 `avatar.workspace_root=<临时目录>`。Runner 计划、启动快照、Runner、执行接口都与 `start` 一致：
  - Runner 计划：`plan_inference_runners`，含配置的 workers；
  - 启动快照：`snapshot_inference_config`；
  - 运行：`InferenceRuntime`；
  - Engine、插件和输出运行时：Host 自己的 `create_execution`（`InferenceExecutor.from_env`、`AvatarEngine`）。
  - 启动顺序同 `SessionManager.start`：先输出端，再 `execution.start()`，再输入端，最后 `notify_ready()`。
- **Doctor 自己负责的部分**：只有传输和临时工作区。
- **输入边界**：`perception.publish_observation`，以及 `publish_source_state` 和 `engine.submit_input`，与 LiveKit 输入适配器的调用位置相同。
  - 音频：20 ms 一帧（取 `runtime.perception.audio_frame_size_ms`），按采样节奏发送。时间范围取发布时刻往前一帧，与 RTC 适配器一致。源晚于节奏的最大时延单独记录（`input_lateness`）。
  - 屏幕帧：按 `video_publish_interval_sec` 发送。每帧先在线程里编码 JPEG 再发布，与 RTC 视频输入一致。
  - 打字输入：经 `engine.submit_input`。
- **输出边界**：`output.stream.subscribe`，用可靠订阅。Sink 按测试 `Player` 和 LiveKit 音频输出的语义发送播放回执，否则字幕不会结束。Sink 不向任何设备播放。
- **离线与工作区**：
  - 会话运行期间，诊断进程置 `ALPHAAVATAR_MODEL_OFFLINE` 和 `HF_HUB_OFFLINE`，结束后复原。Runner 子进程在 spawn 时继承这两个变量。
  - 模型只用已有缓存。
  - 工作区为临时目录，结束即删除。真实 Avatar 工作区、Memory、Persona 和向量库都不会写入。
- **期限**：
  - Runner 启动、会话装配和就绪各不超过 180 s；
  - 单轮不超过 60 s；
  - 全程不超过 480 s；
  - 关闭步骤各有自己的上限；
  - 缓存检查就是 Runner 启动本身，计入上述期限。
- **回收**：
  - 顺序：先关会话（含其 Executor），再关 Runtime，最后删临时工作区。
  - 检查 `mp.active_children()` 的差集，有残留子进程即报 FAIL。
  - 成功、失败、超时和 Ctrl+C 走同一条回收路径。Ctrl+C 只设置停止事件，回收过程本身不会被打断。

### 4. 场景、固定样本与结果类别

| 场景 | 触发条件 | 输入 | 答案须含 |
|---|---|---|---|
| `voice_vision` | VAD、STT、TTS 都已配置且视觉开启 | 语音"What color is the card on my screen?"，同时以屏幕共享送入绿色卡片图 | `green`/`绿` |
| `voice` | VAD、STT、TTS 都已配置且视觉关闭 | 语音"What is two plus three?" | `5`/`five`/`五` |
| `text` | 总是在语音轮之后运行 | 打字"What is two plus three? Answer in one short sentence." | 同上 |
| `image_input` | — | 尚无传输向会话送入图片：报尚无覆盖 | |
| `visual_output` | 配置了 Character | AIRI 在独立的浏览器参会方中渲染，帧不带 Turn：报尚无覆盖；未配置则报未启用 | |

- **语音场景的转写**：转写须含问题中的词（每组任一）。
- **送图方式**：卡片图走屏幕共享（SCREEN），不走摄像头。
  - 原因：生产 turn-taking 中，摄像头可用时为 AUDIO_VISUAL 模式（`policy.decide`）。此时没有寻址证据会进入 HOLD，最终判为 PASSIVE，不会作答。
  - 卡片图没有人脸，视觉寻址无法给出证据。
  - 屏幕帧不改变 turn 模式，帧选择器同样会选取屏幕帧（`VisualFrameSelector` 接受 `VIDEO_FRAME` 和 `SCREEN_FRAME`）。
- **结果类别**：`passed`、`failed`（这两项是实测）、`not_enabled`、`conditions_unmet`（缺授权、模型、样本或会话）、`no_coverage`、`interrupted`。
- **阻塞阶段**：失败场景写出 `blocked_stage`，即下列阶段中第一个未到达的：
  `input`、`vad.closed`、`stt.final`、`turn.committed`、`frames.selected`、`model.request`、`model.first_event`、`text.first`、`text.complete`、`audio.first`、`response.complete`。
  全部到达但答案不符时，写 `answer`。

### 5. 降级

原配置失败、且有现成降级路径时，降级在独立会话中试跑，原配置与降级结果分别报告（`configuration` 分别为 `original`、`degraded: …`）：

- **视觉不可用**：`voice_vision` 已到 STT 之后，但停在选帧、模型或答案（`frames.selected`、`model.*`、`text.*`、`answer`）。处理：以 `vision.enabled=false` 和 audio 会话运行 `voice` 场景。
- **语音输出不可用**：语音轮或打字轮停在 `audio.first`。处理：以 chat 会话运行 `text` 场景，不带音频输出。

两条都是项目已有的路径：
- 视觉关闭时，`VisionConfig` 归为 TEXT，会话类型 audio 不含视频输入；
- chat 会话为 IMMEDIATE 文本模式，不带音频。

原配置的状态决定 `session.scenarios` 的状态：原配置失败即为 FAIL，即使降级通过。

### 6. 指标口径

- **时钟**：统一用会话时钟的单调部分（`time.monotonic_ns`）。
  - 输出事件：`OutputEvent.monotonic_ns`；
  - 输入轨迹：`recorded_time_ns`；
  - 日志：`LogTimings` 在处理器收到记录时打的时间戳；
  - 源：发布时刻。
- **响应起点**：
  - 语音轮：样本中最后一个有效语音采样所在帧的发布时刻。有效语音按 20 ms 窗口判定：RMS 不低于样本最大窗口的 5%。尾部静音照常送入，一直送到本轮结束。
  - 打字轮：`engine.submit_input` 返回、输入被接纳的时刻。
- **测量边界**：诊断输入到服务端输出边界。没有客户端参与，客户端看到或听到的延迟不测。

端到端指标：
- `first_text`、`first_audio_frame`：分别到首个答案文本块、首个答案音频帧从输出边界发出。
- `first_visual_output_frame`：恒为 null，注明没有视觉输出到达输出边界。
- `text_complete`、`audio_last_frame`、`response_final`：分别到文本完成、末个答案音频帧、响应终态。
- `last_required_input`（仅 `voice_vision`）：到最后一个被选中的帧或最后有效语音采样到达。

流式供给：
- `audio_duration`、`audio_frame_interval`（中位数）、`audio_max_gap`。
- `audio_underruns`：假设从首帧起实时播放、没有启动缓冲的队列会断供的次数，注释中给出断供总时长。
- `audio_rtf`：产出时长除以音频时长，注释中给出分子和分母。
- `output_events_dropped`：可靠订阅，不丢帧。慢消费者会反压生产者；反压本身在 sink 侧观测不到，注释中已写明。

分段：
- `vad_close`、`stt_final`、`turn_cutoff`；
- `stt_request_to_final`：以 `stt.commit` 为请求起点，即段落进入 STT 请求队列的时刻；
- `cutoff_to_model_request`、`model_first_token`、`model_first_text`；
- `tts_text_ready_to_request`、`tts_request_to_first_pcm`、`first_pcm_to_first_audio_frame`、`tts_request_to_first_audio_frame`：
  - TTS 请求起点取 Router 的 `SPEECH REQUEST`，每种 TTS 插件都会经过；
  - 首个 PCM 只有 HTTP PCM 提供方会记录，其他插件为 null，并注明原因；
- 视觉：`frame_input_to_available`（JPEG 编码加发布）、`selected_frame_age`（选中帧到模型请求，给出逐帧值）、`vision_wait`（Turn cutoff 之后等帧的时间）；
- 会话：`session_ready`；
- Runner：`models.runners` 给出每个 Runner 的启动时长；`queue_wait_max`、`execution_max` 取自 Runner 进程自己的 `INFERENCE SUMMARY`。峰值队列深度现有观测没有，注明未观测。

每项指标都有数值、单位、起止事件、样本数和测量边界，事件未观测到时值为 null。

### 7. 关联证据

- **复用的观测**：`input_trace` 与现有输出事件，外加 loop 和语音合成已有的日志事件。
  - loop 的 `model.*`、`run.*` 是结构化的 `ConversationEvent`。
  - 语音合成的 `SPEECH SEGMENT`/`SPEECH REQUEST`/`Speech first audio`、TTS 的 `TTS FIRST PCM`、Runner 的 `INFERENCE SUMMARY` 是 debug 格式串，按固定前缀匹配，参数按位置取。CI 断言了由此得到的分段，可防止措辞漂移。
  - 采集只在诊断会话期间进行，范围限于 `alphaavatar` logger，结束后复原级别。
- **生产代码的两处新增**：
  - `InputTrace.identity(value)`：轨迹的加盐身份对外的唯一入口，`record()` 也改为调用它。这样 Doctor 可以找到自己已知的 Turn。
  - Context 选帧时记录 `context.frame_selected`（含 `turn_id`、`observation_id`、perception `sequence`、`event_time_ns`），并在每轮记一条 `context.visual`（含 `frame_count`、`outcome`）。只在视觉作为输入时记录。
  - 之前没有任何记录能说明"哪一帧进了哪一轮"，选帧结果只出现在 prompt 文本里。
- **关联方法**：按身份关联，不按时间窗。
  - 轨迹链：Turn → decision → candidate → segment。
  - 选中帧按 perception sequence 对上 Doctor 自己发布的帧。
  - 证据中给出缩短后的身份令牌（`turn`、`decision`、`candidate`、`segment`）。输出事件和日志带原始 Turn，经 `identity()` 换成同一个令牌。
- **CI 实例**（替身）：
  - 段 `53bd…` 依次出现在 `perception.speech_closed` 和 `stt.terminal`；
  - candidate `9c91…` 的 commit decision 为 `c27d…`；
  - `turn.committed` 记录 decision `c27d…`、turn `73fa…`；
  - 帧 61/97/104 记为 `context.frame_selected`，turn 同为 `73fa…`；
  - `model.started` 与 `output.text_chunk` 的 turn 也是 `73fa…`。
- **边界**：证据最多 64 条，有界且经过报告输出边界。

### 8. 生产代码改动

- `avatar-core/.../log/trace.py`：`InputTrace.identity()`。
- `avatar-plugins-context/.../manager.py`：选帧的两个轨迹阶段。
- `host/application/config.py`：`HostConfig.doctor`。
- `host/configs/template.py`：host 档案增加 `doctor.external_services: false`。
- `host/cli/app.py`、`cli/commands/doctor.py`：移除 `--runtime`，单一入口，按需建事件循环。
- 撤回第一版：
  - 删除 `host/doctor/runtime.py`；
  - `avatar-agents` 的 `RunnerProbe`、`probe()` 和 `cached_*` 文件查询函数，按 `6ff7334` 的内容逐字恢复；
  - 插件的 `missing_*`、Runner 的 `probe()` 和校验函数，同样按 `6ff7334` 的内容逐字恢复。
  - `git diff 6ff7334 -- avatar-agents avatar-plugins` 只剩 context 选帧一处。

### 9. 测试

新增 `avatar-host/tests/doctor/test_session.py`，3 个用例，约 23 s。替身在 `avatar-host/tests/doctor_doubles.py`：
- 只替换外部服务和模型文件：VAD 与 Smart Turn 协议 Runner、按请求内容作答的流式 LLM、分段 STT、实时节奏 TTS、空 Memory 和空 Persona。
- Router、Context、Loop、Engine、输出运行时和共享推理运行时都是生产代码。

| 用例 | 保护的边界 |
|---|---|
| 配置链路跑固定样本、证据按身份关联 | 外部服务允许、下载未关闭的环境中，会话自行关闭下载，结束后复原，logger 级别复原；语音轮与选中帧进入同一个模型请求，帧逐一对上；证据链顺序与身份令牌一致；响应起点为最后有效采样所在帧（首帧在 −1000 ms）；同一时钟下分段之和等于 `first_text`（误差 0.01 ms 内）；vision wait 为 0；语音合成分段可观测；文本逐场景显示；真实工作区未建、临时目录无残留 |
| 视觉或语音输出不可用时跑现有降级，两者分别报告 | 模型拒绝图片：原配置停在 `model.first_event`，降级 `voice` 通过且无帧；TTS 失败：原配置停在 `audio.first`，不触发视觉降级，降级 `text` 通过且没有音频帧；各轮都靠自身输出结束，没有因超时结束 |
| 启动失败、超时与中断都报告并回收 | 首个 Runner 启动失败：其余 Runner 为未到达，`session.start` FAIL，报告不含私有信息；Runner 启动超时，限期 1 s；单轮超时；Ctrl+C（SIGINT 发给本进程）：退出码 130，两个场景为 interrupted；每种情况 `session.cleanup` 都为 PASS，且没有残留进程、socket 目录和临时目录（fixture 检查） |

`tests/cli/test_doctor.py` 的调整：
- 删除第一版的 3 个 runtime 用例和 `doctor_runner_samples.py`。
- 辅助函数改为记录 `Diagnosis.report` 给出的报告。这些配置都没有授权，因此不启动任何东西，文本与 JSON 必须一致。
- `--list --json` 增加 `in_session` 断言；`--runtime`、`--live` 均为用法错误。
- 未授权路径：会话、Runner 和服务三项均为 SKIP，并写明开启方法；向量库会 embedding 时不启动 Runner。
- provider 用例关闭 turn-taking，使其保持静态（它关心的是 provider 后端）。

变异（H1–H13，脚本 `scratchpad/t10c/mutate.py`，每次运行后按 SHA-256 逐字恢复原文件）：

| 变异 | 结果 |
|---|---|
| H1 诊断进程不关闭模型下载 | 测出：Runner 拒绝在可下载时启动 |
| H2 离线变量不复原 | 测出 |
| H3 临时工作区不删除 | 测出（fixture 报残留） |
| H4 不记录选帧 | 测出 |
| H5 轮次不等输出完成 | 首轮存活：TTS 替身在 0.1 s 收尾窗口内已结束。替身改为实时节奏后测出 |
| H6 视觉降级在任何失败时都触发 | 测出 |
| H7 中断目标不计为完成 | 测出（各轮限 10 s） |
| H8 响应起点取首个音频帧 | 测出 |
| H9 不接管 Ctrl+C | 测出（pytest 被 KeyboardInterrupt 中断） |
| H10 日志级别不复原 | 测出 |
| H11 未授权也运行会话 | 测出（沙箱中拒绝 AF_UNIX） |
| H12 启动期限不生效 | 首轮存活：只测了单轮期限。新增卡住的 Runner 后测出 |
| H13 轨迹身份与 `identity()` 不一致 | 测出 |

### 10. 实验记录

- **CI 替身下的音画联合场景**（数值来自替身，只用于验证口径，不代表性能）：
  - 端到端：首字 705 ms，首音频帧 727 ms，文本完成 706 ms，音频末帧 958 ms，终态 958 ms。
  - 分段：VAD 封段 600 ms（静音阈值 0.55 s 加上窗口），STT 终稿 650 ms，cutoff 651 ms，cutoff 到请求 2.9 ms，请求到首 token 50.5 ms。
  - 选中 3 帧，相对语音结束的偏移约为 0、+499、+599 ms，到请求时的帧龄为 655、156、55 ms。vision wait 为 0。
  - 音频 0.24 s，RTF 0.96。按无缓冲口径，断供 11 次：替身每帧比实时慢约 0.8 ms。
- **模型拒绝图片时的降级**：
  - 原配置 `voice_vision` 停在 `model.first_event`。
  - 同一会话的 `text` 轮也带上了 cutoff 之后仍在 perception 中的屏幕帧，同样失败。这是生产行为。
  - 降级 `voice` 通过，首字 705 ms。
- **会话发现的真实配置缺口**：`voice.stt.model` 只在 `get_plugin` 时检查，`config check` 能通过，`start` 却会在会话装配时失败。Doctor 把它报为 `session.start` FAIL。记入 2A 日志 O-10。
- **LanceDB Runner 在 `initialize` 时做 `embed_query("dimension-probe")`**：空 key 时报 `OpenAIError`，有 key 时就是一次付费 embedding。因此启用默认 memory、persona、MCP 时，Runner 启动也需要授权。记入 O-12。
- **空缓存时的离线解析**：`resolve_url_file` 和 `resolve_hf_file` 会先创建命名空间目录和锁文件，然后才报缺失。只有授权或 Runner 可以本地启动时才会发生。记入 O-11。
- **第一版（已撤回）在缓存副本上的单 Runner 实测**，仅作参考：
  - Silero：启动 0.73 s，每次请求约 0.3 ms；
  - Smart Turn：启动 2.28 s，每次请求约 31 ms，8 s 音频 RTF 0.004。

### 11. 真实配置实测：未完成，原因与所需条件

- **凭据**：`.env.dev` 中的 `OPENAI_API_KEY` 被 OpenAI 拒绝（401 invalid_api_key），本次没有产生任何计费。
  - 我随后想逐个检查其他 env 文件里的 key 是否可用，被权限分类器以"凭据探查"拒绝。我没有绕过。
  - 因此两个验收场景都没有用真实服务实测：
    - 音画进入同一轮并按任务作答；
    - 视觉不可用时试跑纯音频降级。
- **固定语音样本**：本机没有本地 TTS 引擎。原计划用 OpenAI TTS 生成一次 `samples/card_question.wav` 和 `samples/sum_question.wav`（16 kHz 单声道），随代码提交。凭据无效，这一步也没有完成。
  - 目前真实运行时，语音场景报 `conditions_unmet`（fixed sample unavailable），不会中断会话。
  - CI 用合成的语音替代样本，不依赖这两个文件。
- **补测需要的条件**：
  - 一个可用的 OpenAI key（或用户指定的 `ENV_FILE`）；
  - 允许用它生成两个样本，费用不到一美分；
  - 一个视觉可用的验收配置，以及一个视觉不可用的配置（例如模型不接受图片）；
  - 模型缓存（本机 `~/.cache/alphaavatar/models` 有 Silero、Smart Turn 和语义寻址模型，可复制后用 `application.cache_root` 指向副本，不改动原文件）。
- 真实实测结果将与本节的 CI 结果分开记录。

### 12. 运行结果

- **测试**：
  - 全量：304 passed，CI 方式（`--basetemp` 在 scratchpad），检出前后一致。28 条警告都是既有的 LanceDB `table_names()` 弃用提示（O-6）。
  - `tests/doctor`：3 passed，约 23 s。
- **静态检查**：`ruff check`、`ruff format --check`、`check_workspace`（16 个成员）、`uv lock --check` 均通过。
- **pre-commit**：对本批改动和新增文件运行，通过。
  - 曾用 `--all-files` 运行，它顺带修正了 4 个与本批无关的已提交文件（两个 `__init__.py` 文件末空行，两个 banner SVG 末尾换行）。已按 HEAD 内容逐字恢复。
- **真实默认 bundle（未授权）**：静态检查与 T-10B 一致；会话、Runner、服务均为 SKIP 并写明开启方法；home 和 `/tmp` 都没有新增内容。

### 13. 限制与未做

- **未验证的部分**：客户端设备、RTC 服务器、客户端实际展示或播放的延迟。
- **尚无覆盖**：
  - 图片输入：没有传输把图片送进会话；
  - 视觉输出：Character 帧不带 Turn；
  - 摄像头寻址：样本走屏幕共享。
- **TTS 首 PCM**：只有 HTTP PCM 提供方（OpenAI、Voice.ai）记录。
- **观测本身的局限**：
  - 语音合成与 TTS 的分段依赖 debug 文案前缀。CI 守住了 Router 一侧；`TTS FIRST PCM` 只有真实 TTS 才会触发，CI 没有覆盖。
  - 播放回执是 sink 收到 COMPLETE 时立即给出的，sink 并不播放，因此不测播放端排队。
- **不在本轮范围**：Runner 并行沿用已有专项测试；长时运行和压力测试归 `alphaavatar test`（0.6.9 第 11 项）。
- **未提交**：等待 review。真实实测见第 11 节。

---

## T-10C `9993aad` review 修复

- 基线：`9993aad`（用户已 push）。统一 CLI 入口、撤回 Runner 专用探针、复用 `create_execution` 三项已通过审查。本轮修复其余五项，只做离线和受控验证，T-10C 暂不验收。
- 两个真实服务场景单列为待验收（第 10 节），等用户指定 `ENV_FILE` 和验收配置后再运行。

### 1. 固定语音样本

- **生成方式**：`scripts/doctor_samples.py make [--ffmpeg PATH]`。
  - 用 FFmpeg 的 `lavfi flite`（kal 音色）。文本取自任务的 `prompt`，经临时 `textfile` 传入，避免过滤器转义。
  - 参数：`-ar 16000 -ac 1 -c:a pcm_s16le -map_metadata -1 -fflags +bitexact -flags:a +bitexact`，不写元数据。同一 FFmpeg 和 flite 生成同一文件，全程不下载。
  - 生成后自动执行 `check`。
- **文本改为要求简短作答**（见第 2 节）：
  - "What color is the card on my screen? Answer in one word."
  - "What is two plus three? Answer with just the number."
  - 独立审查此前按旧文本生成的两段（约 2.24 s、1.75 s）需要按新文本重新生成。
- **打包**：Host 用 hatchling 的 `packages = ["alphaavatar"]`，`alphaavatar/host/doctor/samples/*.wav` 会自动进入 wheel，也没有被 `.gitignore` 排除，不需要改 `pyproject.toml`。
- **读取校验**：`check` 通过 Doctor 自己的 `samples.speech()` 读回，校验 16 kHz 单声道 PCM16、时长和有声结尾。`--installed` 还要求读取位置在已安装环境的 site-packages，而不是源码树。
- **CI**：
  - `quality.yml` 的 build job 在 `uv build` 之后新增一步：新建空环境，按锁文件装 numpy，`--no-deps` 只装 Host wheel，再执行 `python -I scripts/doctor_samples.py check --installed`。
  - 另有源码树测试 `tests/doctor/test_samples.py`。
  - CI 的链路测试继续用替身语音。
- **本机未能生成样本**：
  - 本机没有 `ffmpeg`、`flite`、`espeak`。`~/.cache/ffmpeg-static-nodejs` 里缓存了一个静态 FFmpeg 6.0，但它的构建配置没有 `--enable-libflite`。解压出的副本已删除。
  - 我从 conda-forge 下载了 `flite-2.3.0` 和 `libflite-2.3.0`（SHA-256 与索引一致），准备在 scratchpad 里运行，被权限分类器以"外部代码"拒绝。我没有绕过。
  - 因此两段 WAV 目前还不存在：
    - `test_samples.py` 现在失败。这是真实失败，没有 skip。
    - 真实运行时，语音场景报 `conditions_unmet`（fixed sample unavailable）。
- **wheel 链路的离线验证**（在 scratchpad 中）：
  - 用当前树构建 Host wheel（`uv build --offline`），其中没有 WAV。把它装进只含该 wheel 和 numpy 的干净环境，`check --installed` 在 site-packages 下找不到 `card_question.wav`，按预期失败。
  - 把 avatar-host 复制到 scratchpad，放入两段占位 WAV（正弦音，只用于验证打包，不是语音，不进仓库），再构建 wheel：
    - wheel 中有 `alphaavatar/host/doctor/samples/card_question.wav` 和 `sum_question.wav`；
    - 干净环境中 `check --installed` 从 site-packages 读取成功（2.50 s、2.10 s）。
  - 干净环境所需的 numpy 2.2.6（锁文件版本）不在 uv 缓存中，是从 PyPI 下载装进 scratchpad 环境的。
  - 真实样本生成后，需要在同样的干净环境里再验证一次（第 10 节）。

### 2. 在实际模型请求边界证明音画同轮，并收紧判定

- **请求边界的记录**（`avatar-plugins-loop` 的 `execution.py`，`_trace_request`）：
  - Loop 每次构造 `ModelRequest` 并记录 `model.started` 之后，向本会话的 `input_trace` 写一条 `model.request`，字段为 `turn_id`、`run_id`、`request_id`、请求中本轮输入消息的 `input_id`，以及其中的帧数。
  - 再为每一帧写一条 `model.request_frame`，字段为 `request_id` 和 `ModelImagePart.observation` 的 `observation_id`。
  - 只看请求中 id 等于本轮 `input_id` 的那条消息。
  - `InputTrace` 字段白名单增加 `run_id`、`request_id`，仍按会话加盐散列。
- **Doctor 的判定**（`measure.py`）新增两个阶段：
  - `request.input`：Turn 的首个模型请求所带的输入（`input_id` 令牌）等于 `turn.committed` 的输入。本轮语音转录沿 segment → candidate → decision → Turn 这条链进入该输入。
  - `request.frames`（音画场景）：请求所带的帧中，至少有一帧是 Doctor 发布的样本帧。观测 id 按同一加盐身份比对。
  - 两者缺一，音画场景就不能通过。
- **报告**：
  - `request` 摘要：`turn`、`run`、`request` 令牌，`carries_turn_input`、`frames`、`sample_frames`，以及本轮请求数 `requests`。
  - `frames` 区分 Context 选中的帧（`selected`）、实际进入请求的帧（`requested`）和 Doctor 发布的帧（`published`）。
- **证据**：
  - trace 记录带 `input`、`run`、`request`、`observation` 令牌。
  - loop 日志 `model.started` 中的 `run`、`request`，以及输出事件的 `run`，都用同一个 `identity()` 换成令牌，可以和 trace 直接对上。
  - 证据仍有界（64 条）。截断时优先保留链路的起点、转折和终态：`input.voiced_end`、`stt.terminal`、`turn.committed`、`model.request`、`run.finished`、`output.control`、末帧等。
- **答案判定**（`samples.py`）：
  - 整段答案去掉首尾空白和标点（问号保留），转小写后，必须精确等于期望答案之一。card 为 `green`、`绿`、`绿色`；sum 为 `5`、`five`、`五`。
  - 转录仍按词组校验，但改为按词匹配，`12` 不再算作 `2`。
- **逐输出终态**：同一 run 的每个输出按 `output_id` 单独判定。
  - 终态分为：
    - `completed`：COMPLETE 早于任何以它为目标的 INTERRUPT；
    - `failed`：中断原因以 `_failed` 结尾，例如 `speech_synthesis_failed`；
    - `interrupted`：其他中断原因；
    - `timed_out` 或 `interrupted`：本轮超时或被停止，由 Doctor 以 `doctor_turn_ended` 收尾；
    - `not_ended`。
  - 每个输出附原因和时间。
  - 新增阶段 `outputs.complete`：全部输出都是 `completed` 才通过。`run.completed` 对应 loop 的运行状态。
  - `text_complete`、`audio_last_frame`、`response_final` 只在全部输出正常完成后记录，否则为空、样本数为 0，并注明原因。`response_final` 取最后一个输出完成的时刻，不会早于任何输出的末帧。

### 3. 授权、工作区和资源回收限定在本次诊断内

- **同一快照**：
  - `Diagnosis.run()` 不再重读配置文件和环境。
  - `session.isolate()` 从已校验快照的 `payload` 派生诊断快照（`derive()`：按点路径改值，再 `validate_application`），只改 Doctor 自己的存储位置。授权判定和启动都用这一份快照。
  - 诊断进程收到的是这份快照的 payload，用 `restore_application` 还原。
- **自定义插件**：
  - Doctor 列出本版本自带的插件名和 provider 后端（`_BUILT_IN`）。其余一律记为 `custom <能力> '<名称>'`，外部访问未知，需要授权。
  - 不属于 `alphaavatar.plugins.*` 的 Runner 也计入"启动时会访问的服务"，未授权时不会单独启动。
- **外部服务分四种状态**：
  - `services.external` 改为结构化的 `services`，字段为 `name`、`authorized`、`reached`、`passed`、`note`。文本逐行写明 configured、authorized、reached、passed，或无法判断的原因。
  - reached：该服务应答了会话的某个阶段（模型的首个流事件、STT 终稿、TTS 首帧）。
  - passed：该阶段完成，且没有场景停在这里。
- **诊断进程**（新增 `process.py`）：
  - **启动**：用 `spawn` 启动，进程内调用 `os.setsid()` 自成进程组。离线变量在该进程内设置；`TMPDIR` 指向 Doctor 临时目录下的 `tmp/`；推理端点的环境变量和日志采集（`LogTimings`）都只在该进程内。
  - **停止**：父进程只持有一根管道，关闭写端就是请求停止；父进程意外退出时，这根管道同样会关闭。终端的 Ctrl+C 只到达父进程，因为诊断进程不在前台进程组里。
  - **结果**：以 pickle 写入 Doctor 的临时目录，父进程在诊断进程退出后读取。
  - **期限与强制回收**：
    - 父进程的期限是整轮预算加 `CLOSE_SECONDS`（60 s）。到期或收到停止时关闭管道，再等 `CLOSE_SECONDS`。
    - 仍未退出就用 `killpg` 结束整个进程组，包括 Runner。
    - 退出后再检查一次进程组，有残留同样结束，并写入 `session.cleanup`。
  - **直接取消 `Diagnosis.run()`**：同样关闭管道，等待收尾（不受再次取消打断，有上限），回收之后再抛出 `CancelledError`。取消时没有报告可以返回；Ctrl+C（停止事件）会保留已经取得的结果。
  - **没有留下报告**：会话类检查记为 FAIL 并写明退出码；回收问题单独写入 `session.cleanup`。
- **按会话和本次输入关联**（`_find_turn`）：
  - 语音轮：在本会话的 `input.committed` 中，取 `turn.committed` 感知事件区间 `(start_cutoff_sequence, cutoff_sequence]` 包含本次语音"最后有声帧"事件序号的那一个。
  - 文字轮：取本会话中文本相同、cutoff 晚于本轮开始的那一个。
  - 日志再按 `session_id` 过滤，输出按 Turn 和 run 过滤。
  - 不再取"标记之后的第一个 `input.committed`"。
- **存储隔离**：
  - 默认 memory、persona、MCP 的 LanceDB 如果显式指定了 `client_path`，改绑到临时工作区内的默认位置。
  - Qdrant 等远程存储无法隔离，`session.start` 跳过并写明 "not isolable"。这与 `external_services` 无关：外部调用和写真实 Avatar 数据是两条边界。
- **预算**：`_bounded` 的行为改为：
  - 已请求停止或预算已用尽时，不再启动下一项（返回 `interrupted` 或 `budget`）；
  - 终态在等待结束时确定，任务之后才返回也不改变；
  - 迟到的结果交给调用方关闭，例如超时之后才装配好的 execution 会立即 `aclose`。
  - Runner 启动（含模型缓存检查）、会话装配与就绪、每一轮都在整轮预算之内。预算用尽时 Runner 记为"未启动"，不算作 Runner 失败。
- **单轮回收**：轮次超时、被停止或会话失败时：
  - 立即取消样本播放。时间线是预先传入的，取消后已发送的部分仍然保留。
  - 以 `doctor_turn_ended` 中断该轮的全部输出，并关闭本会话。
  - 剩余场景在新会话中运行，不受前一轮影响。

### 4. 真正的视觉不可用降级

- **触发条件按原因判定**：
  - 模型拒绝图片：`run.finished` 的 `error_type` 为 `ModelCapabilityError`；
  - 只有视觉需要的 Runner 启动失败：用原计划的 Runner 集合减去"无摄像头配置"的 Runner 集合，失败的 Runner 落在差集里。
- **无摄像头配置**（`vision_off()`）：
  - `vision.enabled=false`，默认 persona 的 `face.enabled=false`，默认 router 的 `addressing.visual.enabled=false`。
  - 按这份配置重新规划并启动 Runner。
  - 原配置根本没跑起来时，降级会话同时运行 `voice` 和 `text`。
- **各配置分开运行**：每个尝试的配置各自启动 Runner 和会话，再各自关闭。`models.runners` 展示原配置的结果，降级配置的 Runner 带 `configuration` 字段另行列出。
- **其他原因不降级**：凭据错误等（如 `ModelRequestError`）按原因报告。
- **语音输出降级**：没有音频，或某个输出的音频在首帧之后失败（`speech_synthesis_failed`），都会试跑文本降级。

### 5. 指标与交付

- **模型分段拆为三项**：
  - `model_first_event`：首个流事件；
  - `model_first_text_delta`：首个非空文本增量，来自 loop 的 `model.first_text`，没有观测到就为空；
  - `first_displayable_text`：首段非空文本到达输出边界。
  - 原来的 `model_first_token`（实际是首事件）删除。
- **新增 `context_ready_wait`**：取自 Context manager 自己的 readiness 日志。
- **帧与 cutoff**：
  - 原 `vision_wait`（实际是帧到达与 commit 之差）改名为 `last_selected_frame_to_cutoff`，正值表示该帧在 cutoff 之前到达。
  - `vision_wait` 只在观测到等待时填写。目前生产链路里没有"等待帧"的环节，因此它为空，样本数为 0。
- **样本数**：缺失的指标，样本数统一为 0。
- **部分覆盖**：原配置有场景通过，但有已启用的场景没能运行（例如语音缺 TTS，或 Character 视觉输出无覆盖）时，`session.scenarios` 为 WARN，摘要以 "Partial coverage" 开头。
- **CLI**：仍然只有 `alphaavatar doctor [配置]`、`--list`、`--json`。失败场景另外显示 `cause`（细节中已出现时不重复）。
- **表格输出**（用户在本轮中途提出）：文本输出改为表格，JSON 不变。
  - 检查表：STATUS / CHECK / SUMMARY，按原分组加组标题行；通过的检查占一行，其余在下方续行写细节和下一步。`--list` 同样是表格（CHECK / NEEDS / TITLE）。
  - 运行过会话后，依次给出：
    - Runner 表：STATUS / RUNNER / CONFIGURATION / STARTUP / SUMMARY，原配置与降级配置分行；
    - 外部服务表：SERVICE / AUTHORIZED / REACHED / PASSED / NOTE。服务已在表中的，检查表不再重复这些行；
    - 场景表：OUTCOME / SCENARIO / CONFIGURATION / SUMMARY，失败场景在下方续行写阻塞原因；
    - 指标表：每个实测场景一列，未观测为 `-`，10 ms 以下保留一位小数。原先失败场景下的 "end to end / segments" 两行由该表取代。
  - 实现是命令模块内的私有 `_table()`：列宽取各列最宽的单元格，最后一列不限宽，颜色只在补齐宽度之后加上；没有引入通用表格框架或新依赖。
  - 分隔线用 ASCII `-`。
- **文档**：`docs/cli/doctor.md` 的相应各节已重写，示例输出改为本轮 CI 替身的真实输出。

### 6. 代码改动

| 文件 | 改动 |
|---|---|
| `avatar-core/alphaavatar/core/log/trace.py` | `InputTrace` 字段白名单增加 `run_id`、`request_id`，按身份散列 |
| `avatar-plugins-loop/.../execution.py` | `_trace_request`：在模型请求边界记录 `model.request` 和 `model.request_frame` |
| `host/doctor/process.py`（新增） | 诊断进程：启动、停止管道、期限、`killpg` 回收、临时目录（同时是诊断进程的 `TMPDIR`）、报告传回 |
| `host/doctor/session.py` | 快照派生（`derive`、`isolate`、`vision_off`），存储隔离判定，各配置独立的 Runner 与会话，预算与终态，按截断范围找轮次，单轮回收，按原因降级，外部服务四态，部分覆盖 |
| `host/doctor/measure.py` | 请求边界阶段、逐输出终态、完成类指标条件、指标改名与新增、帧的三种标记、证据令牌与有界截断 |
| `host/doctor/samples.py` | 新提问文本，整段精确判定，按词校验转录 |
| `host/doctor/transport.py` | 输出记录带 `run_id`、控制原因；播放时间线由调用方传入；采集 Context readiness 日志 |
| `host/doctor/doctor.py` | `_external` 返回名称和类别并识别自定义插件；`run()` 经诊断进程；`_report` 一并处理 `cause` 和 `services` |
| `host/doctor/schemas/` | `ScenarioResult` 增加 `cause`、`reached`、`request`、`outputs`；`RunnerResult.configuration`；新增 `ServiceResult`；`Check.services` |
| `host/cli/commands/doctor.py` | 文本改为表格（检查、`--list`、Runner、外部服务、场景、指标）；失败场景显示 `cause` |
| `conftest.py`（根目录） | `pytest_configure` 中 `asyncio.set_event_loop(None)`，见第 9 节 |
| `scripts/doctor_samples.py`（新增） | 样本生成与读取校验 |
| `.github/workflows/quality.yml` | build job 新增"只装 Host wheel 读取样本"一步 |
| `docs/cli/doctor.md` | 诊断进程、快照与存储、授权、场景与判定、降级、指标、证据、期限各节重写；示例输出 |

### 7. 测试与反例验证

- **测试结构**：链路测试改为真正经过诊断进程。
  - `doctor_doubles.child` 取代诊断进程的入口：先在该进程内装上与测试进程相同的禁网守卫（只允许绝对路径的 AF_UNIX；任何尝试都写入文件，即使调用方吞掉了异常），再装替身，最后调用真实入口。
  - 替身的说明通过环境变量 `DOCTOR_DOUBLES`（JSON）传入，替身所见写入测试目录。
  - 每次运行都断言：父进程环境前后完全一致，禁网记录为空。
- **`tests/doctor/test_session.py`**（7 项）：
  - **主链路**：
    - 父进程允许下载时，诊断进程和 Runner 仍然离线（替身 Smart Turn 只在离线时才能启动）；父进程里不出现离线变量和推理端点，日志级别不变。
    - 请求带本轮输入，样本帧数等于替身实际收到的图片数；三种帧标记；逐输出全部 `completed`。
    - 证据令牌：`turn.committed` 的 input、`model.request` 的 input/run/request、日志 `model.started` 的 run/request、输出的 run 一一对上。
    - 分段加和等于端到端；首事件与首文本增量相差约 50 ms（替身先发一个空增量）；`vision_wait` 与视觉输出帧为空、样本数 0。
    - 服务四态；文本输出。
    - **快照**：`prepare()` 之后把配置文件改成关闭视觉，运行结果仍是原快照的 `voice_vision`。
  - **降级**（4 种原因）：
    - 模型拒绝图片 → 原配置停在 `model.first_event`、`cause=ModelCapabilityError`，但请求已带样本帧；降级 `voice` 通过，请求不带图片；模型服务记为 reached、未通过。
    - 只有视觉需要的 Runner 缺模型 → 原配置在 `runners` 阻塞；降级配置的 Runner 计划里没有它，`voice` 和 `text` 都通过。
    - 两个输出，第二个的 TTS 在首帧后失败 → `[completed, failed(speech_synthesis_failed)]`，停在 `outputs.complete`，完成类指标为空、样本数 0；不触发视觉降级；文本降级通过；TTS 服务 reached、未通过。
    - 凭据被拒（`ModelRequestError`）→ 按原因报告，不尝试任何降级。
  - **答案判定**：精确匹配与反例清单，另跑一次纯文本会话，答案 "15." 判为失败。
  - **失败、超时与预算**：Runner 启动失败；启动卡住 1 s 超时；轮次在播报中途超时（输出 `timed_out`，下一场景用新会话，Turn 不同）；预算为 0 时什么都不启动，并写明原因。
  - **`_bounded` 单元**：超时后迟到返回仍为 `timeout`，被停止后迟到返回仍为 `interrupted`，停止或预算用尽后不再启动。
  - **Ctrl+C 与直接取消**：退出码 130，两个场景都是 `interrupted`，进程组消失；取消 `Diagnosis.run()` 抛出 `CancelledError`，进程组消失，父进程环境不变，临时根目录为空。
  - **不响应停止的诊断进程**（替身让它忽略停止和预算，并卡在 Runner 启动里）：约 4 s 后整组被结束；`session.cleanup` 为 FAIL 并写明被结束；卡住的 Runner 进程已不存在；`/tmp` 下没有新的推理 socket 目录残留。
- **`tests/doctor/test_measure.py`**（3 项，直接构造一轮的记录）：
  - 评审复现：一个输出完成，另一个在首个音频帧之后被中断，且中断晚于前者完成 → FAILED，停在 `outputs.complete`，`response_final` 和 `audio_last_frame` 为空；两个都完成 → `response_final` ≥ 末帧；从未结束 → `timed_out`。
  - 请求所带 input 不是本轮的 → 停在 `request.input`；100 条无关步骤时，证据截断仍保留关键终态。
  - Context 选中两帧、请求只带一帧时，两种标记分开。
- **`tests/doctor/test_isolation.py`**（4 项，纯判定）：
  - 显式 LanceDB 路径改绑进工作区，除存储位置外快照不变；Qdrant 即使已授权也阻塞。
  - 自定义插件需要授权；自定义 Runner 不会在未授权时单独启动。
  - 关闭视觉时恰好去掉人脸分析 Runner。
  - 按截断范围和会话找轮次（语音轮与文字轮）。
- **`tests/doctor/test_samples.py`**（1 项）：源码树中两段样本可被 Doctor 读取。**当前失败**，原因见第 1 节。
- **`tests/cli/test_doctor.py`**：
  - 适配结构化的 `services`；新增断言：远程存储标为 not isolable，所有服务都是"未授权、未到达"。
  - 文本断言改为表格：表头、组标题、检查行（列宽对齐）、非通过项的细节、服务表行、场景表行（含配置列），以及 `--list` 表。
  - 主链路测试另外断言指标表：表头为各实测场景，未观测为 `-`。

### 8. 变异

脚本 `scratchpad/t10c/mutate2.py`，每次运行后按 SHA-256 逐字恢复原文件，结束后再整体比对一次校验和，一致。

| 变异 | 结果 |
|---|---|
| M1 Loop 不记录请求所带帧 | 测出 |
| M2 不核对请求所带输入 | 测出 |
| M3 任一输出完成即算完成 | 测出 |
| M4 失败与中断不区分 | 测出 |
| M5 超时记成中断 | 测出 |
| M6 答案按子串判定 | 测出 |
| M7 轮次不按截断范围关联 | 测出 |
| M8 超时后迟到的结果记为完成 | 测出 |
| M9 预算用尽仍启动 | 测出 |
| M10 停止后仍启动下一项 | 测出 |
| M11 诊断进程不另立进程组 | 测出（卡住的 Runner 成了孤儿进程，没有被回收） |
| M12 诊断进程的临时目录不放进 Doctor 目录 | 测出（`/tmp` 残留推理 socket 目录） |
| M13 超时时只结束诊断进程本身 | 存活：随后的进程组复查会把残留的 Runner 一并结束，结果相同。这是两道等价的回收，记为等价变异 |
| M14 父进程设置离线变量 | 测出（父进程环境变化） |
| M15 诊断进程不关闭下载 | 测出 |
| M16 启动前重读配置 | 测出（快照测试） |
| M17 不改绑显式 LanceDB 路径 | 测出 |
| M18 远程存储不阻塞 | 测出 |
| M19 自定义插件不计入外部访问 | 测出 |
| M20 自定义 Runner 不计入 | 测出 |
| M21 关闭视觉时不关人脸分析 | 测出 |
| M22 视觉降级不看原因 | 测出（TTS 失败时误触发） |
| M23 视觉专属 Runner 判断失效 | 测出 |
| M24 降级沿用原配置 | 测出 |
| M25 首帧后失败不降级到文本 | 测出 |
| M26 缺失指标的样本数为 1 | 测出 |
| M27 首文本增量取自首事件 | 测出 |
| M28 未全部完成仍记录末帧 | 测出 |
| M29 证据截断丢掉终态 | 测出 |
| M30 请求帧与选中帧不区分 | 测出 |

### 9. 运行结果

- **全量测试**（CI 方式：`--basetemp` 在 scratchpad，`PYTHONDONTWRITEBYTECODE=1`）：316 项，315 passed，1 failed，用时 112.7 s，检出前后一致。
  - 唯一失败是 `test_samples.py`：样本尚未生成（第 1 节）。
  - 28 条警告都是既有的 LanceDB `table_names()` 弃用提示（O-6）。
  - `tests/doctor` 共 15 项，其中 `test_session.py` 7 项约 72 s；`tests/cli/test_doctor.py` 5 项通过。
- **事件循环泄漏（O-13，既有问题）**：
  - 修复前，全量运行 2 次都以 exit 1 结束。会话结束时报 `unclosed event loop` 和两个 AF_UNIX socket，所有测试都是通过的；拆成两半分别运行时不出现。
  - 我用临时 pytest 插件记录每个事件循环的创建栈，定位到 pytest-asyncio 在首个异步测试（`avatar-core/tests/test_lifecycle.py`）前调用 `asyncio.get_event_loop()` 时新建的那个循环。
  - 用 `git archive` 导出 `9993aad`，以其代码和测试复现了同样的 exit 1，确认不是本轮引入的。
  - 根 `conftest.py` 修复后，最小复现和全量运行都不再出现。
- **静态检查**：以下各项均通过：
  - `ruff check`、`ruff format --check`（712 个文件）；
  - `check_workspace`（16 个成员）、`uv lock --check`；
  - pre-commit（本批改动的文件）；
  - workflow YAML 可以解析。
- **CI 替身下的运行**（数值来自替身，只用于验证口径）：
  - 主链路：`voice_vision` 首字 707 ms、首音频帧 729 ms、完成 961 ms；`text` 首字 53 ms、完成 301 ms。
  - 模型拒绝图片（文档示例）：原配置 `voice_vision` 停在 `model.first_event`，原因为 `ModelCapabilityError`；降级 `voice` 首字 725 ms，完成 1001 ms。
  - 真实默认 bundle（未授权）的输出与上一轮一致，只是改为表格。

### 10. 待验收与未实测

- **待验收（等用户指定 `ENV_FILE` 和验收配置后运行）**：
  - 音画同轮：真实 VAD/STT/LLM/TTS 下，`request.input`、`request.frames` 通过，答案为 `green`，并给出各项指标和分段证据；
  - 视觉不可用时降级为纯音频：原配置的阻塞阶段和降级结果分别报告。可以用不接受图片的模型，也可以用缺少人脸模型缓存的默认 persona。
- **先决条件**：用户本机用带 libflite 的 FFmpeg 运行 `uv run python scripts/doctor_samples.py make` 生成两段样本，或允许我在本机运行 conda-forge 的 flite。之后用 `check` 和干净环境中的 `check --installed` 各复验一次，`test_samples.py` 应转为通过。
- **未实测**：
  - 真实 TTS 的 `TTS FIRST PCM` 分段；
  - 真实 STT 对 flite 语音的转录质量；
  - 远程向量存储（按设计跳过）；
  - 自定义插件对临时工作区之外的写入（Doctor 无法隔离，只标为未验证）；
  - 路径过长时，`private_socket_path` 会退回 `/tmp`，此时诊断进程被强制结束后，socket 目录不在 Doctor 目录内。

### 11. 限制

- **直接取消**：直接取消诊断协程时，按 asyncio 惯例抛出 `CancelledError`，已取得的结果不会返回；需要保留结果时用停止事件（Ctrl+C 走的就是这条路径）。
- **库调用**：诊断进程用 `spawn` 启动，与推理 Runner 相同。在脚本中调用 `diagnose()` 需要 `if __name__ == "__main__":` 保护。
- **用时**：链路测试改走真实诊断进程后，`tests/doctor` 从约 23 s 增加到约 70 s。全量用时见第 9 节，仍在 CI 的 5 分钟内。
- **不在本轮范围**：Runner 并行沿用已有的专项测试；长时运行和压力测试归 `alphaavatar test`（第 11 项）。
- **未提交**：等待 review。

---

## T-10C `bf79300` 收尾

- 基线：`bf79300`（用户已提交上一轮的 review 修复和表格输出）。保持不变的部分：表格输出；唯一入口 `alphaavatar doctor [配置]`；`--list` 列出检查项、`--json` 输出同一份报告；`--live`、`--runtime` 仍然移除。
- 用户已在本机运行 `ENV_FILE=.env.dev alphaavatar doctor my-avatar`：9 项静态检查通过。该 bundle 未授权外部服务、视觉未启用，因此只验证了静态检查和默认授权行为。两个真实服务场景仍待验收（第 6 节）。
- 本轮只做离线和受控验证。

### 1. 样本存放

- **Doctor 安装后直接使用的小样本**：
  - 来源：用户提供的 `AlphaAvatar-Doctor-samples-bf79300.zip`。提取前校验了成员：只有两段 WAV，路径正是 `avatar-host/alphaavatar/host/doctor/samples/`，然后只提取这两个文件到仓库。

    | 文件 | SHA-256 | 时长 | 有声结尾 |
    |---|---|---|---|
    | `card_question.wav` | `04763dd6b7f5a1b61d91b752c7865fc41182b1d73b3519ac7862976c53374e98` | 3.65 s | 3.52 s |
    | `sum_question.wav` | `93ac159096acaf89eed0220b1d42b9c4c89f11f6916053266949910268d2d18f` | 3.26 s | 3.14 s |

    两段都是 16 kHz 单声道 PCM16，内容与当前提示词一致。
  - 读取：由 `importlib.resources` 读取，随 Host wheel 发布。`scripts/doctor_samples.py` 保留，作为可复现的生成入口。
  - 源码树：`python -I scripts/doctor_samples.py check` 通过，`tests/doctor/test_samples.py` 由上一轮的失败转为通过。
  - 干净 wheel 安装验证（scratchpad 中）：
    - `uv build --offline --wheel --package alpha-avatar-host` 构建的 wheel 含两段 WAV，SHA-256 与仓库中的文件一致；
    - 新建环境中只装该 wheel（`--no-deps`）和 NumPy 2.2.6（锁文件版本），`check --installed` 从该环境的 site-packages 读出两段样本，通过。
- **仅供测试的小样本**：约定放在使用它的包自己的 `tests/fixtures/` 下。仓库中目前没有这类文件，测试用的语音和画面都在代码里生成，因此没有需要搬迁的。本轮的大样本清单是测试专用文件，放在 `avatar-host/tests/fixtures/large_samples.json`。
- **大样本**（独立的 Hugging Face Dataset）：
  - **实际状态（2026-11-04 查询，未带 token）**：`/api/datasets?author=AlphaAvatar` 返回空列表（该组织下有多个公开模型，但没有 dataset）；`/api/datasets/AlphaAvatar/diagnostics-fixtures` 返回 401，即不存在或不公开。
  - **结论**：尚未发布。清单中 repo ID 仍为此前建议的 `AlphaAvatar/diagnostics-fixtures`；`revision`、`license`，以及每个样本的 `sha256`、`bytes` 均为 `null`；`published: false`。
  - **拟用清单**：

    | 名称 | 路径 | 用途 |
    |---|---|---|
    | `long_session` | `speech/long_session_16k.wav` | 30 分钟语音与停顿：VAD、STT、轮次的长时稳定性 |
    | `multi_speaker` | `speech/multi_speaker_16k.wav` | 两人轮流和重叠说话：轮次与说话人归属 |
    | `noisy_room` | `speech/noisy_room_16k.wav` | 室内和街道噪声下的语音：VAD 与 STT 的鲁棒性 |
    | `barge_in` | `speech/barge_in_16k.wav` | 回答中途用户插话：打断与输出中断 |
    | `face_toward_away` | `video/face_toward_away_640x360.mp4` | 人脸转向和背离摄像头：视觉寻址与人脸分析 |

  - **测试入口**：
    - 测试用 `@pytest.mark.large_samples("名称", ...)` 声明所需样本，通过 `large_sample("名称")` 夹具拿到本地文件。
    - 默认 `addopts` 带 `-m "not large_samples"`，普通运行、离线 CI 和 wheel 校验都不会选中这类测试；用 `pytest -m large_samples` 选中。
    - 会话级夹具在各测试的禁网与环境守卫生效之前，按清单拉取所选测试需要的全部样本：`hf_hub_download`，固定到清单中的 commit，以 `local_dir` 缓存到 `~/.cache/alphaavatar/test-samples/<repo>/<revision>/`。
    - 缓存中的文件 SHA-256 有效时直接复用，完全不联网。否则下载并校验。
    - 下载失败时报告样本名、文件、`repo@revision` 和错误类型；校验不符时报告样本名、文件、期望值与实际值前缀，并删除不符的文件。
    - 后续接入 `alphaavatar test`。
  - **实际拉取状态**：未发布，所以没有拉取过。现在选中这类测试，会逐个报 "`<名称>`: AlphaAvatar/diagnostics-fixtures is not published with a pinned revision and SHA-256"。发布后需要填入 commit、license、各文件的 SHA-256 和大小。
  - **离线机制测试**（`avatar-host/tests/test_large_samples.py`，2 项）：
    - 清单结构，以及未发布时逐个样本报告的内容；
    - 按固定 commit 下载；有效缓存不再下载（下载函数被调用就失败）；损坏的缓存重新下载；下载内容不符时报出并删除；下载失败报出原因；清单之外的名称报出。

### 2. review 问题

#### 2.1 场景终态优先

- **问题**：`ended` 为 `timeout`、`interrupted` 或 `session_failed` 时，如果输出在收尾窗口内完整到达，场景仍返回 PASS。
- **修复**：
  - `ended` 非空时，场景不再可能 PASS：`interrupted` 记为 INTERRUPTED，其余记为 FAILED。
  - 没有更早的阻塞阶段时，阻塞阶段为 `turn.timeout`、`turn.interrupted` 或 `turn.session_failed`。
  - 迟到的输出及其终态（例如 `completed`）仍保留在 `outputs` 和证据中。
  - `text_complete`、`audio_last_frame`、`response_final` 只在场景正常完成时填写，否则为空、样本数 0，注明 "not recorded: the turn ended by …"。
- **反例**（`test_measure.py`）：三种结束方式下输出全部在之后完成，结果分别为 FAILED / FAILED / INTERRUPTED，阻塞阶段为 `turn.<结束方式>`，三项完成耗时为空，`outputs` 仍为 `completed`，证据中有 `output.control`。

#### 2.2 实际请求同时携带语音内容和样本帧

- **Loop**（`_trace_request`）：对本轮 TurnSnapshot 的每个 `input_observation_ids`，在同一个 `ModelRequest` 的本轮消息中查找，并记一条 `model.request_input`（`request_id`、`observation_id`，`outcome` 为 `carried` 或 `missing`）。判断方式：
  - 该配置使用音频输入时，看是否有对应 observation 的 `ModelAudioPart`；
  - 否则看该 observation 的文本（转录或输入文字）是否出现在请求文本中。比较前反转义 XML/HTML 实体，并合并空白。
- **Doctor** 新增阶段 `request.content`：
  - 语音任务：Turn 的首个请求必须 carried 该样本的 STT 终稿 observation（`stt.terminal outcome=final_text` 的 `observation_id`）。
  - 文字任务：必须 carried 输入的文字。
  - 关联链：segment → candidate → decision → Turn（`turn_id`）→ `model.request`（`run_id`、`request_id`、`input_id`）→ `model.request_input` 与 `model.request_frame`（样本 observation ID）。
  - 报告只保留脱敏令牌和校验结果：`request.carries_turn_input`、`carries_turn_content`、`frames`、`sample_frames`。
- **反例**（`test_session.py`）：替身让 Context 渲染本轮时去掉语音（`_speech_xml` 返回空），其余不变：
  - 请求仍带本轮 `input_id`，也带样本帧，但不带转录；
  - 音画场景停在 `request.content`，细节为 "The model request does not carry this Turn's transcript"；
  - 不触发降级。
- 主链路测试中，语音轮和文字轮的 `request.content` 都通过。

#### 2.3 视觉不可用降级

- **Runner 设置**：`vision_off()` 先按关闭视觉后的配置（不带任何方法设置）规划 Runner，再只保留仍在计划中的 `runtime.inference.methods`。否则 `check_inference_config` 会以 `unselected_runner` 拒绝该配置。原配置不变，其阻塞结果照常保留。
  - 反例（`test_isolation.py`）：原配置为人脸分析 Runner 和另一个 Runner 都设置了 workers；关闭视觉后只剩后者的设置，原配置的两项都在。
- **图像能力拒绝的分类**：
  - `ModelCapabilityError` 增加可选的 `code`，与 `ModelRequestError.code` 对应。
  - OpenAI Responses 适配器在本地拒绝图像时标 `code="image_input"`：图像无媒体载荷、没有可编码的表示、本地路径 URL、内联图像超过 `max_inline_bytes`。
  - Loop 的 `run.finished` 增加 `error_code`，取模型错误的 `code`；同时把 `error_code` 加入 conversation 事件字段白名单。不加的话，带 code 的 `run.finished` 会被 `log_event` 静默丢弃。实测中这会表现为场景没有原因，最终以超时结束；变异 N9 确认了这一点。
  - Doctor 的 `cause` 带上 provider 的代码，例如 `ModelCapabilityError: image_input`、`ModelRequestError: http_401`。
  - 只有 `ModelCapabilityError: image_input` 才触发视觉降级。OpenAI 适配器把 HTTP 错误统一归为 `ModelRequestError(code="http_<状态码>")`，从中看不出与视觉有关，因此 HTTP 400、401 和其他服务故障都按原分类报告，不降级。
- **用实际 provider 适配器验证**（`test_session.py`）：
  - 测试进程在 loopback 上起一个 HTTP 替身，诊断进程的禁网守卫只额外放行这一个端口。loop 使用真实的 `openai` backend（Responses 适配器和 OpenAI SDK），`base_url` 指向该替身。
  - `max_inline_bytes=1024`：适配器在发出请求前拒绝样本帧，原配置 `cause=ModelCapabilityError: image_input`，并触发 "degraded: vision off"。纯音频请求真正发出后被替身以 401 拒绝，降级结果为 `ModelRequestError: http_401`，停在 `model.first_event`。
  - 默认设置下替身返回 400：原配置为 `ModelRequestError: http_400`，没有降级。
  - 用 ScriptedLLM 补充两个反例：凭据错误（`ModelRequestError: invalid_api_key`），以及与图像无关的 `ModelCapabilityError`（没有 code）。两者都只有原配置结果，不降级。

#### 2.4 诊断进程隔离与零 Runner

- **诊断子进程不继承 Host 的端点**：子进程入口清除 `ALPHAAVATAR_INFERENCE_ENDPOINT`、`ALPHAAVATAR_INFERENCE_PLAN`、`ALPHAAVATAR_LOG_ENDPOINT`，沿用各自已有的常量。
- **stdout 只属于报告**：子进程启动后先执行 `dup2(2, 1)`，子进程及其 Runner 打印的内容都进 stderr。父进程的 stdout 只有 `--json` 报告。
- **验证**（`test_session.py`，用 `capfd` 在文件描述符层面捕获）：
  - 父进程设置了三个 Host 变量，log endpoint 指向测试进程自己绑定的 AF_UNIX 数据报接收端。替身在诊断进程（STT）和其 Runner（VAD）中各打印一行。
  - 结果：stdout 可以直接整体解析为 JSON；两行打印都出现在 stderr；会话和 Runner 正常启动，音画场景通过；Host 接收端没有收到任何数据报；父进程环境在运行前后完全一致。
- **零 Runner**：没有任何 Runner 的计划是合法的（例如纯文字配置）。`session.start` 改为按会话实际的启动结果判定，`models.runners` 为 SKIP（"Not started: no runner selected"）。
  - 反例：纯文字配置中，`models.runners` 为 SKIP，`session.start` 为 PASS（此前为 FAIL）。

### 3. 代码改动

| 文件 | 改动 |
|---|---|
| `avatar-agents/.../provider/errors.py` | `ModelCapabilityError(message, *, code=None)` |
| `avatar-plugins-provider/.../openai/adapters/responses.py` | 图像相关的本地拒绝标 `code="image_input"` |
| `avatar-plugins-loop/.../execution.py` | `model.request_input`（按 observation 判断请求中是否携带）；`run.finished` 增加 `error_code` |
| `avatar-core/.../log/events.py` | conversation 事件字段白名单增加 `error_code` |
| `host/doctor/measure.py` | `request.content` 阶段；`cause` 带代码；场景终态优先；完成耗时只在正常完成时填写 |
| `host/doctor/session.py` | `vision_off()` 同步修剪 `runtime.inference.methods`；视觉降级只认 `image_input`；零 Runner 的 `session.start` |
| `host/doctor/process.py` | 清除 Host 端点，stdout 改道到 stderr |
| `avatar-host/alphaavatar/host/doctor/samples/*.wav` | 两段固定样本（新增） |
| `avatar-host/tests/large_samples.py`、`tests/fixtures/large_samples.json`、`tests/conftest.py`、根 `pyproject.toml` | 大样本清单、加载器、夹具、`large_samples` 标记和默认排除 |
| `docs/cli/doctor.md` | 诊断进程隔离、零 Runner、样本存放、`request.content`、带代码的原因、终态优先、视觉降级条件；示例输出重新生成 |

### 4. 测试与变异

- **新增或修改的测试**：
  - `test_session.py` 共 9 项，新增 2 项：
    - 用真实 OpenAI 适配器的分类测试；
    - Host 隔离与 stdout 测试。
    - 降级测试增加了去掉语音和非图像能力错误两次运行；答案测试增加了零 Runner 断言。
  - `test_measure.py` 共 4 项，新增终态优先 1 项。
  - `test_isolation.py`：增加 Runner 设置修剪的断言。
  - `test_large_samples.py`：新增 2 项。
- **变异**（脚本 `scratchpad/t10c/mutate3.py`，每次运行后按 SHA-256 逐字恢复原文件，结束后再整体比对校验和，一致）：

| 变异 | 结果 |
|---|---|
| N1 迟到的完成覆盖超时终态 | 测出 |
| N2 中断时只在已有阻塞阶段时才判中断 | 存活：N1 修复后，`ended` 非空时阻塞阶段一定存在，这一条件永远为真，属于等价变异 |
| N3 未正常结束仍记录完成耗时 | 测出 |
| N4 不核对请求所带的转录 | 测出（去掉语音的反例） |
| N5 Loop 不比对请求内容 | 测出 |
| N6 任何能力错误都触发视觉降级 | 测出（非图像能力错误的反例） |
| N7 关闭视觉后保留全部 Runner 设置 | 测出（`unselected_runner`） |
| N8 Loop 不记录错误代码 | 测出 |
| N9 事件字段白名单没有 `error_code` | 测出（`run.finished` 被丢弃，原因为空） |
| N10 适配器的体积拒绝不标图像 | 测出（真实适配器测试） |
| N11 诊断进程继承 Host 的三个端点 | 测出（推理端点冲突，会话没有启动） |
| N12 诊断进程只清除推理端点 | 测出（Runner 接入 Host 日志，打印不再出现在 stderr） |
| N13 诊断进程的 stdout 不改道 | 测出（stdout 无法解析为 JSON） |
| N14 零 Runner 判为启动失败 | 测出 |
| N15 有效缓存仍重新下载 | 测出 |
| N16 校验不符时保留坏文件 | 测出 |

### 5. 运行结果

- **全量测试**（CI 方式：`--basetemp` 在 scratchpad，`PYTHONDONTWRITEBYTECODE=1`）：321 passed，0 failed，exit 0，用时 137.7 s，检出前后一致。
  - 没有被标为 `large_samples` 的测试，所以默认排除没有排除掉任何测试。
  - 28 条警告都是既有的 LanceDB `table_names()` 弃用提示（O-6）。
  - 没有出现 `unclosed event loop`（O-13 已修复）。
- **样本**：
  - 源码树 `check` 通过；
  - 干净 wheel 环境的 `check --installed` 通过（第 1 节）；
  - `test_samples.py` 通过。
- **Doctor 相关**：`tests/doctor`、`tests/cli/test_doctor.py`、`tests/test_large_samples.py`、Loop 与 trace 的测试合计 33 项通过，其中 `test_session.py` 9 项约 95 s。
- **静态检查**：以下各项均通过：
  - `ruff check`、`ruff format --check`；
  - `check_workspace`（16 个成员）、`uv lock --check`；
  - pre-commit（本轮改动的文件）。
- **CI 替身运行（文档示例）**：模型拒绝图片时，原配置 `voice_vision` 停在 `model.first_event`，原因为 `ModelCapabilityError: image_input`；降级 `voice` 通过。

### 6. 待验收

由用户指定 `ENV_FILE` 和配置后运行，用单次 `host.doctor.external_services=true` 授权：

1. **音画同轮**：启用 `vision.enabled=true`、`vision.input_mode=vlm`，使用支持图像的模型。要验证的是：
   - `request.input`、`request.content`、`request.frames` 均通过，答案为 `green`；
   - 输出全部正常完成；
   - 端到端指标和分段指标齐全。
2. **视觉链路受阻**：从已启用视觉、但视觉链路受阻的配置开始，例如适配器无法内联图像（`ModelCapabilityError: image_input`），或者只有视觉需要的 Runner 缺少缓存。要验证的是：报告中同时给出原配置的具体阻塞原因，以及 "degraded: vision off" 的纯音频实测结果。

真实服务下尚未实测的项目：`TTS FIRST PCM` 分段、真实 STT 对 flite 语音的转录质量。按设计跳过的项目：远程向量存储，以及自定义插件在临时工作区之外的写入（Doctor 无法隔离，只标为未验证）。

### 7. 限制

- **视觉能力的判定**：只有 provider 能确认是视觉能力问题时，才会触发视觉降级。目前只有 OpenAI 适配器的本地图像拒绝带 `image_input`。服务端因模型不支持图像返回的 HTTP 400，按设计仍报 `ModelRequestError: http_400`，不降级。其他 provider 适配器需要各自给出 `code`。
- **请求内容的判定**：在实际请求中查找文本，依据是转录文字出现在请求的文本部分里。如果某个渲染器改写了转录（例如翻译或摘要），就会判为 missing。目前 Context 原样嵌入转录。
- **大样本**：数据集尚未发布，拉取流程只用离线替身验证过，没有真实下载过。
- **未提交**：等待 review。

---

## T-10C `6a593f2` 真实服务验收

- **基线**：`6a593f2`。
- **授权**：用户授权以 `/home/ecs-user/AlphaAvatar/.env.dev` 作为 `ENV_FILE`，并执行配置所需的真实服务调用。
  - 凭据只经 `ENV_FILE` 注入，报告中只出现服务名和错误分类。
  - 所有 JSON 报告都经过检查：没有 `sk-`，也没有 40 字符以上的类密钥串。
- **结论**：真实链路的关键证明都成立：
  - 本轮转录与样本帧进入同一个实际 `ModelRequest`；
  - 各启用输出正常结束，首字、首音频帧、终态和分段指标齐全；
  - 视觉受阻时，原配置的 `ModelCapabilityError: image_input` 与纯音频降级（STT、模型、TTS 都实际完成）同时出现在报告中。
- **未通过之处**：严格答案校验两次都没有通过。真实 STT 返回的转录只有样本的第一句，丢掉了后面的作答格式要求，模型因此用完整句子回答（2.4）。
- **另外两个发现**：
  - 默认配置下，真实语音轮会因 `transcript_timeout` 被丢弃（KD-17，2.1）；
  - 未提交轮次的阻塞阶段原先会被误报，Doctor 已修正（2.1）。
- **大样本**：HF 数据集的发布与拉取仍单独跟踪，本次没有使用。验收用的是随 Host 打包的两段小样本。

### 1. 验收配置

- **隔离**：
  - 临时 home 为 `scratchpad/accept/home`。用 `ALPHAAVATAR_HOME` 指向它，以 `alphaavatar config init` 生成两个 bundle：`av-vision`（Avatar `doctor-av-vision`）和 `av-blocked`（`doctor-av-blocked`）。
  - 用户的 `my-avatar` bundle、真实 home 和 Avatar 数据都没有改动。
  - 模型缓存只复制了 Silero VAD 和 Smart Turn 两个目录（19 MB）到临时 home 的 `cache/`，真实缓存没有改动。
- **命令**：`ALPHAAVATAR_HOME=<临时 home> ENV_FILE=.env.dev alphaavatar doctor <bundle> host.doctor.external_services=true --json`，授权只对这一次运行有效。
- **两份配置共用的链路**（与 `my-avatar` 及模板一致）：
  - loop：`realtime`，原生 OpenAI Responses backend，模型 `gpt-5.6-luna`；
  - STT：`openai_segment`，`gpt-4o-transcribe`；
  - TTS：`openai`，`gpt-4o-mini-tts`，音色 `ash`；
  - VAD：`silero`；轮次判定：`smart_turn_v3`；
  - memory、persona：默认插件。LanceDB 位于 Doctor 的临时工作区，embedding 为 `text-embedding-3-small`。
- **相对模板的改动，两份都有**（完整 diff 在 `scratchpad/accept/config-diff.txt`）：

| 位置 | 模板 | 验收 | 原因 |
|---|---|---|---|
| `vision.enabled` / `input_mode` | `false` / `text` | `true` / `vlm` | 音画场景 |
| `router.init_config.addressing.semantic.enabled` | `true` | `false` | 减少变量：单人会话，样本就是对 Avatar 说的 |
| `router.init_config.addressing.visual.enabled` | `true` | `false` | 画面以屏幕共享发送，没有人脸 |
| `router.init_config.turn_taking.transcript_wait_sec` | 默认 0.75 | `3.0` | 见 2.1（KD-17）；第三次运行起才加入 |
| `persona.init_config.profiler/speaker/face.enabled` | `true` | `false` | 减少变量；也就不需要复制 1.9 GB 的说话人与人脸模型 |
| `memory.init_config.retrieval/conversation/tool.enabled` | `true` | `false` | 减少变量：不发生 gpt-4o 增量调用 |
| `status.enabled` | `true` | `false` | 减少变量 |

- **只有 `av-blocked`**：`loop.init_config.model.input_options.max_inline_bytes: 1024`。原生 Responses 适配器因此无法内联样本帧，在发出请求之前就拒绝图像。
- **静态检查**：两份配置 `config check` 均有效，计划相同：Silero、memory LanceDB、persona LanceDB、Smart Turn，各 1 个 worker。

### 2. 实测过程与结果

#### 2.1 第一、二次运行（`av-vision`，模板默认的 `transcript_wait_sec=0.75`）

- **两次相同的部分**：会话、4 个 Runner、embedding、模型、TTS 都正常；`text` 场景通过（真实 `gpt-5.6-luna` 回答 "5"）。
- **`voice_vision` 失败**：60 s 内没有提交轮次（Ended by timeout）。
- **第一次的报告把阻塞阶段误报成 `vad.closed`**：没有提交的 Turn 时，trace 链为空，输入之后的阶段全都显示为缺失。离线用缓存中的真实 Silero 跑这段样本，114 个窗口中有 100 个概率大于 0.5，说明 VAD 本身没有问题。
- **Doctor 修正**：没有提交的轮次时，按本轮输入的时间窗口追踪其语音片段、STT 和轮次判定记录（`measure._uncommitted`），报告给出实际停下的阶段。
- **第二次运行，修正后的报告给出实际链路**（时间相对最后有声样本）：

| 时间 | 事件 |
|---|---|
| +680 ms | VAD 封段（`perception.speech_closed`） |
| +681 ms | 提交 STT（`stt.commit`，210 帧） |
| +815 ms | Smart Turn 判定 HOLD（等待转录） |
| +1566 ms | CANCEL：等待转录 0.75 s 后超时，候选退役 |
| +2442 ms | 真实 STT 终稿到达（`final_text`），因片段已退役被拒（`candidate.transcript_rejected reason=retired_segment`） |

- **结论（KD-17）**：轮次判定在判为结束之后，只等待转录 `transcript_wait_sec`（默认 0.75 s）。真实 `gpt-4o-transcribe` 从提交到终稿约 1.76 s，晚于这个等待。按模板默认配置（`my-avatar` 同样如此），只要 STT 比这更慢，用户的语音轮就会被整句丢弃。这是生产问题，不属于 T-10C 范围，本批没有改默认值，已记入 2A 日志的 KD 表，待用户决定。验收从第三次运行起，在两份配置中同时把它设为 3.0 s。

#### 2.2 第三次运行：音画同轮（`av-vision`）

- **检查结果**：13 PASS、1 FAIL（`session.scenarios`）、1 SKIP（`devices.media`），退出码 1。
  - `session.start` 103 ms 就绪；
  - Runner：Silero 0.73 s、memory LanceDB 6.53 s、persona LanceDB 4.41 s、Smart Turn 2.29 s；
  - `services.external`：模型、STT、TTS 三项均为 reached 并通过；
  - `session.cleanup` PASS：2 个自有部件关闭，Runner 进程、socket 和临时工作区都已回收。
- **`voice_vision` 场景**：
  - 转录为 "What color is the card on my screen?"，回答为 "The card is green."；
  - 停在 `answer`：不是 `green` 这样的单词答案，原因见 2.4。
- **同一实际请求的关联**（脱敏令牌）：
  - `model.request`：turn `9b4ef3400415`、run `9202e29b2f68`、request `30e1a51b9e55`，`input` 等于 `turn.committed` 的 input（`carries_turn_input`），`frame_count=4`；
  - `model.request_input`：STT 终稿 observation `8d970c5d8fec` 为 carried（`carries_turn_content`，即 `request.content` 通过）；VAD 语音片段 observation 为 missing，这是正确的：VLM 模式只带转录，不带音频；
  - `model.request_frame`：4 帧，全部是 Doctor 发布的样本帧（`sample_frames=4`）。Context 选中与请求所带完全一致，帧龄分别为 2904、1903、1004、104 ms；
  - 日志 `model.started` 的 run/request 令牌与 trace 一致，输出的 run 也是这个 run。
- **输出**：1 个输出（text+audio），终态 `completed`。
- **端到端指标**（起点为最后有声样本发布）：

| 指标 | 值 |
|---|---|
| 首字 `first_text` | 3415 ms |
| 首音频帧 `first_audio_frame` | 4651 ms |
| 文本完成 `text_complete` | 3943 ms |
| 音频末帧 `audio_last_frame` | 6431 ms |
| 响应终态 `response_final` | 6431 ms |
| 最后必需输入 `last_required_input` | 1482 ms（最后一张选中帧晚于语音结束） |
| 音频 | 3.15 s，RTF 0.565（3.15 s 音频用 1.78 s 产出），最大间隔 575 ms，按无缓冲口径断供 1 次 |

- **分段指标**：

| 分段 | 值 |
|---|---|
| VAD 封段 `vad_close` | 681 ms |
| STT 终稿 `stt_final` | 1543 ms（提交到终稿 861 ms） |
| 轮次截断 `turn_cutoff` | 1579 ms |
| Context 就绪等待 | 0.3 ms |
| 截断到模型请求 | 4.2 ms |
| 请求到首个流事件 / 首个文本增量 / 首段文本到输出边界 | 1652 / 1832 / 1832 ms |
| TTS 请求到首个 PCM | 884 ms |
| 首个 PCM 到首音频帧 | 0.6 ms |
| 帧到达到可用（JPEG 编码） | 0.8 ms |
| 最新选中帧早于截断 | 97 ms |
| `vision_wait` | 空（没有观测到等待） |

- **Runner 队列**：
  - Silero 311 次调用，最大排队 0.014 ms、最大执行 2.7 ms；
  - Smart Turn 2 次，最大执行 37 ms；
  - LanceDB 1 次，8 ms。
- **同会话的 `text` 场景**：通过，回答 "5"。首字 992 ms，首音频帧 2022 ms，终态 2410 ms；模型首事件 574 ms，TTS 首 PCM 818 ms。

#### 2.3 视觉受阻后降级为纯音频（`av-blocked`）

- **检查结果**：12 PASS、2 FAIL（`services.external`、`session.scenarios`）、1 SKIP，退出码 1。这是原配置的预期失败导致的，因此单独检查了降级场景自身的结果。
- **原配置**：
  - `voice_vision`：转录 "What color is the card on my screen?"，请求带本轮输入、转录（`request.content` 通过）和 4 张样本帧。停在 `model.first_event`，原因为 `ModelCapabilityError: image_input`：Responses 适配器因 `max_inline_bytes=1024` 在本地拒绝图像，没有发出请求。
  - 同会话的 `text`：同样因上下文中带着屏幕帧，原因为 `ModelCapabilityError: image_input`。这是生产行为。
  - 原配置的阻塞结果完整保留在报告中。
- **降级配置 `degraded: vision off`**：重新规划了 Runner，4 个均启动；未修剪任何方法设置（本配置没有设置）。
  - `voice` 场景实际完成了 STT（转录 "What is two plus three?"）、模型调用（回答 "Two plus three is five."）和 TTS。请求带本轮输入与转录，不带图像。
  - 输出 1 个（text+audio），终态 `completed`。
  - 停在 `answer`，原因见 2.4。
  - 端到端：首字 3274 ms、首音频帧 4189 ms、文本完成 3413 ms、音频末帧与终态 4906/4907 ms；音频 2.4 s，RTF 0.299。
  - 分段：VAD 682 ms、STT 终稿 1745 ms（提交到终稿 1063 ms）、截断 1781 ms、截断到请求 1.7 ms、请求到首事件 1244 ms、到首文本 1491 ms、TTS 请求到首 PCM 776 ms。
- **外部服务**：模型 reached 但未通过（原因 `ModelCapabilityError: image_input`），STT 与 TTS 均通过。
- **回收**：`session.cleanup` PASS，4 个自有部件关闭（原配置与降级配置的会话和各自的运行时）。
- 本次没有出现普通 HTTP 400、401 或通用服务故障。凭据有效：embedding、模型、STT、TTS 都已实际调用成功。

#### 2.4 严格答案校验没有通过的原因

- **现象**：两段固定样本由 flite 生成，各有两句（问题 + 作答格式要求）。两段都是 VAD 的一个片段（210 帧，覆盖整段），没有被拆开。但真实 `gpt-4o-transcribe` 两次都只返回第一句（"What color is the card on my screen?"、"What is two plus three?"）。STT 插件发送的是整段 PCM，终稿原样使用，没有截断。
- **后果**：模型没有收到作答格式要求，用完整句子作答。内容正确（"The card is green."、"Two plus three is five."），但不满足"整段答案等于期望单词"。
- **处理**：我没有放宽判定，避免把真实失败变绿。可选做法（待用户决定）：
  1. **重写提示词**：改成单句、把格式要求放进问题本身，例如 "In one word, what color is the card on my screen?" 和 "As a single number, what is two plus three?"，再离线重新生成样本。转录模型是否保留前置的格式要求仍需实测，而我在本机无法运行 flite。
  2. **可确定的去回显判定**：去掉问题中已出现的词以及冠词和系词（`the`、`card`、`is`、`it`、`two`、`plus`、`three` 等）之后，剩下的必须恰好是期望答案。按这个规则，"The card is green." 和 "Two plus three is five." 通过；"Not green."、"Maybe green."、"The card is not green. It is red."、"15"、"Green?" 仍不通过。该规则可以确定判定，也不依赖 STT 保留格式要求。
  3. 两者结合。

### 3. 回收

- 四次真实运行的 `session.cleanup` 均为 PASS，没有进程残留：第三次运行 2 个部件，`av-blocked` 4 个部件。
- Doctor 临时目录（含诊断进程的 `TMPDIR` 和 socket）都已删除。
- 临时 home 中的 `avatars/` 没有生成，诊断数据只写在 Doctor 自己的临时工作区，运行后已删除。
- 用户的 `~/.local/share/alphaavatar` 只被读取过：用 `config check my-avatar` 读取模型选择。`~/.cache/alphaavatar` 只被读取过：复制了两个模型目录。验收开始后，两处都没有任何文件被修改（已用 `find -newer` 核对）。

### 4. 受控测试（与真实实测分开）

- **新增 `test_measure.py::test_a_spoken_input_that_never_committed_shows_where_it_stopped`**：
  - 复现真实链路：片段封段、提交 STT、HOLD、CANCEL，之后才到达转录；
  - 断言阶段到达 `input`、`vad.closed`、`stt.final`，停在 `turn.committed`，证据中按顺序有 hold 和 cancel，且不包含本轮开始之前的旧 `turn.committed`。
- **变异**（每次运行后按 SHA-256 逐字恢复原文件）：
  - U1 不跟踪未提交的输入：测出；
  - U2 不按本轮时间窗口取 trace：测出。
- **全量结果**：322 passed，0 failed，exit 0，用时 137.8 s（CI 方式），检出前后一致，没有 `unclosed event loop`；`ruff check`、`ruff format --check`（714 个文件）通过。

### 5. 待用户决定

1. **KD-17**：`transcript_wait_sec` 默认 0.75 s，短于真实分段 STT 的延迟（本次实测为 0.86 s 至 1.76 s）。可选：
   - 提高默认值；
   - 按 STT 能力（分段或流式）设默认值；
   - 改为等到 STT 终稿或出错，再加一个上限。
2. **样本提示词与答案判定**：见 2.4。
3. **大样本 HF 数据集**：发布、实际拉取和校验仍单独跟踪（见上一节第 1 节）。

### 6. 第 9 条 `config init` 轻量交互入口：最小实现方案（待 review，尚未实现）

- **目标**：交互终端里依次选择：
  - 预设：纯文本、语音、音画；
  - Memory 和 Persona 的处理器；
  - 工具。

  写入前预览启用项和所需凭据的名称。脚本和 CI 可以用显式参数无人值守完成。自动安装另立任务。
- **配置接口**（放在 `alphaavatar.host.configs`，供 CLI、Web、TUI 和移动端复用，纯函数）：
  - `InitChoices`（冻结 dataclass）：
    - `preset`：`text`、`voice` 或 `audio_visual`；
    - `memory`：retrieval、conversation、tool 中启用的集合；
    - `persona`：profiler、speaker、face 中启用的集合；
    - `tools`：deepresearch、rag、mcp 中启用的集合。

    默认值等于现有模板，即 `voice`、全部启用、不启用工具。
  - `render_bundle(name, avatar_id, choices=InitChoices())`：在现有模板文本上按选择改写各节，例如：
    - `text` 预设：`voice` 的 vad、stt、tts 均为 null，视觉关闭；
    - `audio_visual` 预设：视觉启用、`input_mode: vlm`。

    改写后沿用现有校验（`HostConfig` / `AvatarConfig`，以及 Runner 规划），文件写入前就失败。
  - `preview_bundle(...)`：从渲染结果得出启用项（复用 `describe_summary` 的结构）和所需环境变量名，不含任何值。例如 OpenAI 模型、语音、embedding 需要 `OPENAI_API_KEY`；deepresearch 需要 `TAVILY_API_KEY`；`voiceai` 需要 `VOICEAI_API_KEY`；RTC 需要 `LIVEKIT_*`。现有的 `REQUIRED_ENVIRONMENT` 改为由选择推导。
  - `create_bundle(paths, name, avatar_id=..., choices=...)`：沿用现有的原子写入、不覆盖和失败回滚逻辑，只是写入渲染后的文本。
- **CLI**（`cli/commands/config.py`，交互只放在这里）：
  - `alphaavatar config init <name> --avatar-id ID [--preset text|voice|audio-visual] [--memory retrieval,conversation,tool|none] [--persona profiler,speaker,face|none] [--tools deepresearch,rag,mcp|none] [--yes]`。
  - stdin 和 stdout 都是终端、且有选项没有给出时，按编号菜单逐项询问，显示预览后确认（`y/N`）。
  - 非终端，或参数已经给全时，从不提问：用给出的值和默认值，直接预览并写入；`--yes` 跳过确认。
  - `--json` 输出预览与结果，供脚本使用。
- **测试**：
  - 三种预设渲染后都能通过 `config check` 同一套校验；
  - 预览只列名称、不含值；
  - 交互流程用替身输入测试，包括取消时不写任何文件；
  - 无人值守的参数路径；
  - 不带参数时的输出与现在相同；
  - 已有的不覆盖、回滚测试保留。
- **不做**：自动安装依赖、模型下载；凭据的写入或校验（只列出名称）。

---

## Doctor 默认运行时测试（基线 `2fc4f398`）

依据：Codex 对 `2fc4f398` 复核的第二阶段。要求：Doctor 先做静态检查，再默认运行所有适用的运行时测试；纯本地测试直接运行；可能联系外部服务时先列服务、提示计费并要求明确同意，提问和运行用同一份已加载配置；拒绝或 `--no-metrics` 只做静态检查，运行时指标标 SKIP 并写原因；非交互时只有明确授权才调用外部服务；`--json` 的 stdout 保持纯 JSON，仍是同一个 `doctor` 入口；首次缺模型时先说明要下载什么，确认后继续；覆盖文本、音视频、关闭视觉的纯语音；显示首字、首音频帧、响应完成和收集到的所有阶段耗时，失败时保留已测值，未观测的显示 `—` 和原因；离线替身的耗时可用于验收；给出可复现的真实服务验收步骤；报告写明测量止于 Host 输出，LiveKit 传输和客户端播放另测。所有改动在未暂存的工作区。

### 0. 历史记录（合并来源）

| 原位置 | 原结论 | 现状 |
|---|---|---|
| 本文件 T-10C 各节 | 外部服务只凭配置授权（`host.doctor.external_services`，默认 false），未授权时跳过会话；缺模型只报告、不下载 | 配置授权保留，用于非交互；终端里多了由人同意这条路。缺模型在同意后下载 |
| 安装日志「第 1 项第二轮」第 10 节 | 只装基础包时，Doctor 的缺包建议提示 `alphaavatar setup` | 不变；缺包行与 `config check` 共用，窄终端拆成设置、问题、包名、提示四行 |
| 安装日志「第 1 项 CLI 展示统一」第 4 节 | Doctor 文本分组、未验证原因、端到端与阶段耗时；`Full report` 给出带同样参数的 `--json` 命令 | 展示规则仍记在那里。本轮 `Full report` 改为 `Run again as JSON`，`—` 带原因（第 3 节） |

### 1. 先静态检查，再默认跑运行时测试

- **纯本地**：配置不联系本机以外的服务时（`Diagnosis.unauthorized` 为空），静态检查后直接运行。
- **外部服务**：在终端里，静态检查后先列出要联系的服务（`_external` 加上 runner 启动时就会联系的，如向量库的 embedding），写明「Calls to these services may be billed.」，再问 `Run the runtime tests? [y/N]`：
  - 同意：`Diagnosis.authorized()` 在 Doctor 已加载、已校验的同一个快照上 `derive(config, {"host.doctor.external_services": True})`，问的和跑的是同一份配置，中间不重读；
  - 拒绝、回车或 `--no-metrics`：`session.start`、`models.runners`、`session.scenarios` 为 SKIP，原因分别是 `Not run: the external services it reaches were declined` 和 `Not run: left out with --no-metrics`；`session.cleanup` 写明什么都没启动；`End-to-end latency` 为 `Not measured · Not run: …`。
- **非交互**：不提问，只认配置或覆盖项 `host.doctor.external_services=true`；未授权时与之前相同，`session.start` 列出会联系的服务和放行方法。
- **`--json`**：标题和提问写 stderr，stdout 只有 JSON。
- **提问处 Ctrl+C**：退出 130，报告原因为 `interrupted at a question`，什么都不运行。
- **`--no-metrics`**：只做静态检查，不起 runner，不联系任何服务，也不提问。

### 2. 缺模型：先说明，同意后下载

- 第一次运行时，runner 只从模型缓存启动，诊断进程里下载是关的。所有模型文件都经共用解析器 `agents/utils/files/model/model_files.py`，离线缺文件时抛 `FileNotFoundError`；`missing_models(report)` 找出因此失败的 runner。
- 有终端、没有中断、下载也没被 `ALPHAAVATAR_MODEL_OFFLINE`／`HF_HUB_OFFLINE` 关掉时，Doctor 列出这些 runner 和下载位置（`<cache>/models`），问 `Download and continue? [y/N]`。同意后以 `downloads=True` 重跑，报告以重跑为准。
- 重跑时，runner 启动的时限与 `start` 相同，取 `runtime.inference.initialize_timeout`（默认 300 s），总时限相应加长（第 4 节第 3 条）。
- 拒绝或没有终端时，报告就是第一次的：这些 runner 失败，原因是模型不在缓存里。

### 3. 文本报告

- `End-to-end latency`：首字、首音频帧、响应完成，再列文本完成、最后一帧；`Stage timing · <场景>`：收集到的所有阶段耗时。失败的场景保留已测值。
- 未观测的指标显示 `—`，表下逐条写原因：
  - 指标自己知道的原因，如 `this TTS plugin logs no first PCM`、`not recorded: the turn ended by timeout`；
  - 否则是场景停在哪里，如 `not reached: stopped at model.first_event`；
  - 否则是 `not observed`。
  - 多个场景同一原因时合并为一行，并列出场景名。
- `Full report` 改为 `Run again as JSON`：`alphaavatar doctor [target] --json`。带过 `KEY=VALUE` 覆盖项时，另起一行说明需要带同样的覆盖项，原文不回显。
- 测量终点：`docs/cli/doctor.md` 和预览页写明，所有指标止于 Host 的输出边界，LiveKit 传输和客户端播放另测。

### 4. 录制中发现并修复

1. **runner 日志打进终端**：下载场景的录制里，runner 失败时自己的日志（`Inference runner failed`、`error: FileNotFoundError`、调用栈）直接接在「Running the runtime tests…」那行后面。原因是诊断进程把 stdout 并到 stderr，而 stderr 就是终端；runner 没有日志接收端时，Python 的兜底处理器把 WARNING 以上的日志写到 stderr。
   - 改为：诊断进程和它的 runner 的 stdout、stderr 都写到 Doctor 临时目录里的 `output.log`，随目录删除。runner 的失败本来就在 `models.runners` 的细节里。
   - 诊断进程自己退出（退出码大于 0）而没有留下报告时，缺报告原因附上它输出的最后一行（例如 `RuntimeError: …`），之后与其他细节一样经过输出边界脱敏。被杀（负退出码）时不附，那一行不是它结束的原因。
2. **`—` 的原因**：`model_first_text_delta` 的说明「the first token, as far as the stream shows it」被当成缺失原因显示出来。
   - `_metric` 的第 5 个参数只作缺失原因；说明改用 `note=` 关键字，只在有值时保留。`context_ready_wait` 的说明同样只在有值时保留。
   - `tts_request_to_first_pcm` 只在 TTS 请求已经发出时才写「this TTS plugin logs no first PCM」；请求没发出时，原因是场景停在哪里。
3. **下载重跑的时限**：原先重跑时 runner 启动仍按 180 s 计，真实下载可能超时。改为 `session.budget(initialize)`：启动时限取 `max(180, initialize_timeout)`，总时限加上同样的差值。
4. **提问处 Ctrl+C 的换行**：光标停在提问行末，报告紧贴其后。`Report.ask` 遇到 Ctrl+C 或输入结束时先结束该行；setup 同样受益。
5. **下载重跑的提示**：进行中提示改为「Downloading the model files, then running the runtime tests…」。

### 5. 改动文件

| 文件 | 改动 |
|---|---|
| `avatar-host/.../doctor/doctor.py`、`doctor/__init__.py` | `Diagnosis.unauthorized`、`authorized()`、`report(skipped)`、`run(downloads)`；`missing_models` |
| `avatar-host/.../doctor/process.py` | `diagnose(downloads)`，只在未同意下载时设离线；输出写入 `output.log`；无报告时附最后一行；下载时的时限 |
| `avatar-host/.../doctor/session.py` | `budget(initialize)` |
| `avatar-host/.../doctor/measure.py` | 缺失原因与说明分开 |
| `avatar-host/.../cli/commands/doctor.py` | 同意、拒绝、下载、`--no-metrics`、提问处 Ctrl+C、`—` 的原因、`Run again as JSON` |
| `avatar-host/.../cli/app.py` | `--no-metrics`；帮助文本 |
| `avatar-host/.../cli/render.py` | `pending` 进行中提示；`ask` 中断时结束提问行 |
| 测试 | `test_session.py`：同意与拒绝（`--json` 时提问在 stderr、stdout 是纯 JSON）、`--no-metrics`、下载同意与拒绝（终端里没有 runner 日志；两次运行的 runner 启动时限为 180 s 和 300 s）、提问处 Ctrl+C、诊断进程自己退出时附最后一行、Host 内运行时终端上没有诊断进程的输出；`test_measure.py`：缺失原因与说明；`test_render.py`、`test_doctor.py`：文本报告；`doctor_doubles.py`：`DownloadRunner`、`crash`、`runs.jsonl` |
| `docs/cli/doctor.md` | 默认运行时测试、同意与计费、`--no-metrics`、模型文件、时限、`—` 的原因、`Run again as JSON`、测量终点、新的示例输出 |

### 6. 验证

**本地**
- 全量测试 491 项通过；拦截已移除的包后再跑一遍，也是 491 项通过（含第 9 节验收后新增的 5 项）。静态检查（Ruff `--no-cache`、格式、`check_workspace.py`、`uv lock --check`、`git diff --check`、`bash -n`、pre-commit）全部通过。
- 变异：本部分 D1–D10、F1–F7b 共 18 个，全部被抓到，每个都核对过失败的是预期断言。首轮 F3（被杀的诊断进程也附最后一行）存活：被杀的替身什么都没输出，断言证明不了这一点；替身改为先输出一行再挂起后被抓到。证据：`scratchpad/evidence8/mutants8.log`、`mutants8-b.log`。

**离线测试替身（`doctor_doubles`：只替换外部服务和模型文件，Router、Context、Loop、Engine、输出运行时和推理运行时都是生产代码；本轮最终代码，伪终端录制）**

| 录制 | 结果 |
|---|---|
| `doctor-offline-agreed-100`、`-72` | 列出 6 项服务和计费提示，答 y：`Diagnostics completed · 14 passed · 1 skipped`；voice_vision 首字约 704 ms、首音频帧约 726 ms、响应完成约 954 ms，text 约 53／74／299 ms（替身的耗时）；`TTS request → First PCM` 为 `—`，原因 `this TTS plugin logs no first PCM` |
| `doctor-offline-voice-100` | 关闭视觉：`voice` 和 `text` 两列；`voice_vision` 为 SKIP |
| `doctor-offline-download-100` | 缺模型的 runner 和下载位置列出，答 y 后重跑通过；终端里没有 runner 的失败日志 |
| `doctor-offline-degraded-100` | 模型不接受图片：`voice_vision`、`text` 停在 `model.first_event` 并保留已测阶段，`voice [vision off]` 通过；`—` 的原因都是 `not reached: stopped at model.first_event` 或 `not recorded: an output ended otherwise` |
| `doctor-offline-interrupt-72` | 提问处 Ctrl+C：退出 130，`Not run: interrupted at a question` |

**干净沙箱（本轮最终构建）**

| 录制 | 结果 |
|---|---|
| `doctor-declined-72`、`-100` | 列出 5 项服务和计费提示，答 n：`OK 9 passed · 6 skipped`，`Session and services` 为 SKIP，原因 `Not run: the external services it reaches were declined` |
| `doctor-nometrics-100` | 不提问，SKIP 原因 `Not run: left out with --no-metrics` |
| `doctor-unasked.txt`（stdin 为 `/dev/null`） | 不提问；未授权时按原样跳过，并给出放行方法 |
| `doctor-unasked.json` | `--json`：stdout 第一个字符是 `{`，stderr 为空 |

### 7. 真实服务验收步骤（用户已确认，实测结果见第 9 节）

前提：Linux x86_64，glibc 2.28 或更新；真实的 `OPENAI_API_KEY`；三个 LiveKit 变量（Doctor 不连接 LiveKit，`config check` 只要求它们已设置）。下面全部放在 `$HOME/aa-accept`，不影响已有安装。

```bash
export ALPHAAVATAR_HOME=$HOME/aa-accept/home
P=$HOME/aa-accept/prefix; B=$HOME/aa-accept/bin; OUT=$HOME/aa-accept/out

# 1. 构建并安装本轮的基础包（推送后也可用 CI 制品）。在这台机器上构建要放宽到 glibc 2.32：
#    本机编译的 llama-cpp-python 引用了 2.32 的符号；CI 在 manylinux_2_28 里构建，不需要
packaging/linux/build.sh --allow-dirty --max-glibc 2.32 --out "$OUT"
bash "$OUT/install.sh" --file "$OUT"/alphaavatar-*-linux-x86_64.tar.gz --prefix "$P" --bin-dir "$B"
export PATH="$B:$PATH"

# 2. 首次交互 setup：逐项回车保留参考配置（含本机模型），bundle 名填 accept；
#    凭据回车保留环境里的值，Store …? 答 n；看完计划后 Install and enable? 答 y
export OPENAI_API_KEY=… LIVEKIT_URL=… LIVEKIT_API_KEY=… LIVEKIT_API_SECRET=…
alphaavatar setup --artifacts "$OUT"

# 3. Doctor：先看列出的服务和计费提示，再在 Run the runtime tests? [y/N] 答 y；
#    首次会出现 Model files：看清 runner 和下载位置后，在 Download and continue? [y/N] 答 y
alphaavatar doctor accept

# 4. 关闭视觉的纯语音；5. 纯文本（每次同样先确认）
alphaavatar doctor accept vision.enabled=false
alphaavatar doctor accept voice.vad.plugin=null voice.stt.plugin=null voice.tts.plugin=null

# 6. 拒绝：在提问处直接回车，应只做静态检查、不产生调用
alphaavatar doctor accept

# 7. 非交互：不提问，stdout 为纯 JSON
alphaavatar doctor accept host.doctor.external_services=true --json < /dev/null > report.json
python3 -c 'import json; r = json.load(open("report.json")); print(r["status"], r["counts"])'

# 8. 无人值守的 setup 路径（可选）
alphaavatar config init ci --avatar-id ci
alphaavatar setup ci --artifacts "$OUT" < /dev/null
alphaavatar config check ci
```

- **预期**：
  - 第 2 步：`Validate PASS · 8 runners`。
  - 第 3 步：同意下载后 `voice_vision`、`text` 有结果（失败时给出阻塞阶段和原因），`End-to-end latency` 有首字、首音频帧、响应完成，`Stage timing` 有各阶段，每个 `—` 都带原因。
  - 第 4 步：`voice`、`text`。第 5 步：只有 `text`。
  - 第 6 步：`Not run: the external services it reaches were declined`。
  - 第 7 步：模型已在第 3 步下载，不再提问。
- **计费**：每次同意后的运行都会多次调用对话模型、记忆与画像任务、embedding、STT 和 TTS；第 3、4、5、7 步各运行一次，模型不接受图片时还会多跑一次降级配置。第 6 步不产生调用。
- **下载**：只在第 3 步同意之后发生，位置是 `$ALPHAAVATAR_HOME/cache/models`。
- **测量终点**：所有指标止于 Host 的输出边界。LiveKit 传输和客户端播放不在其中，留给第 4 项（真实手机浏览器 RTC）另测。
- **清理**：`rm -rf $HOME/aa-accept`，只删本次验收的目录。

### 8. 待复核

1. **先跑一次再问下载**：第一次运行只从缓存启动 runner，失败后才知道缺哪些模型。runner 没有声明式的模型清单，不启动就列不出来。缺的若只是仅视觉用到的模型（例如人脸），第一次运行会先跑一遍关闭视觉的降级配置，这些调用已经过同意；同意下载后再整体重跑。参考配置下 turn taking 的模型也缺，降级配置同样起不来，第一次运行不会联系外部服务。
2. **同意只对本次有效**：不会写回配置；下次运行还会再问。
3. **列出的服务**：提问时列的是会话阶段和 runner 启动时会联系的全部服务；非交互跳过时，`session.start` 的细节只列会话阶段的服务（沿用原文本）。两处的列表可能不同。

### 9. 真实服务验收（用户确认后运行，2026-11-06）

用户确认后，按第 7 节在本机实测。凭据取自 `/home/ecs-user/AlphaAvatar/.env.dev`（T-10C 验收用过的同一文件），只取 `OPENAI_API_KEY` 和三个 LiveKit 变量，写进会话临时目录里一个只有本人可读的文件；每条命令都在空环境里运行，只带这四个变量、隔离的 `ALPHAAVATAR_HOME`、本轮的命令和 `PATH`。验收目录放在会话临时目录，而不是第 7 节示例的 `$HOME/aa-accept`。全部录制（伪终端，`.cast`／`.ansi`）和 JSON 报告都检查过，不含任何凭据值。

**磁盘与模型缓存**：磁盘只剩 3.4 GB，装不下 1.7 GB 的参考环境再加约 2 GB 的模型全量下载。验收的模型缓存因此用硬链接从本机已有缓存（`~/.cache/alphaavatar/models`）建立，不占额外空间，并去掉 turn taking 的模型，让 Doctor 首次运行真的缺模型、真的去下载。模型解析从不原地改写缓存文件（都是写临时文件再 `os.replace`），小文件（锁文件、清单）另外复制断开链接；删除验收目录后核对过，原缓存字节数不变、链接数恢复为 1。所以「首次缺模型并下载」只覆盖了 turn taking（8.4 MB），其余模型没有在本次验收中重新下载。

**结果**（第一轮用 `20261106133847` 构建；第 4 小节的修复后用 `20261106142425` 构建复验）

| 步骤 | 命令 | 结果 |
|---|---|---|
| 安装 | `install.sh --file … --prefix … --bin-dir …` | 基础包 208 MB |
| 交互 setup | `alphaavatar setup --artifacts …`：逐项回车（参考配置，含本机模型），bundle `accept`，凭据回车保留，不存 | 从真实索引下载 105 个包、514 MB；`Validate PASS · 8 runners`；环境 1.7 GB |
| 拒绝下载 | `doctor accept`，同意测试、拒绝下载 | 只列出 `smart_turn_v3`；第一次的报告：该 runner 失败，其后 5 个 runner 未到达；向量库 runner 未启动，没有任何计费调用 |
| 同意下载 | `doctor accept`，同意测试、同意下载 | turn taking 模型下载后 runner 3.07 s 启动；`text` 通过；`voice_vision` 各阶段都到达，卡在严格答案校验（见下） |
| 非交互 | `doctor accept host.doctor.external_services=true --json < /dev/null` | 不提问；stdout 第一个字符是 `{`，stderr 为空；三项外部服务都是 reached、passed |
| 关闭视觉 | `doctor accept vision.enabled=false` | `OK · 14 passed · 1 skipped`；`voice`、`text` 都通过 |
| 纯文本 | `doctor accept voice.vad.plugin=null voice.stt.plugin=null voice.tts.plugin=null` | `OK`；`text` 通过；两个音频指标为 `—`（原因见第 4 小节第 4 条） |
| 拒绝测试 | `doctor accept`，提问处回车 | 只做静态检查，`Not run: the external services it reaches were declined`，没有调用 |
| 无人值守 | `config init ci` → `setup ci --artifacts … < /dev/null` → `config check ci` | 复用已装环境，不提问，`Validate PASS · 8 runners`；之后 `config init` 的下一步是 `config check`、`doctor`（已装完整环境） |

**实测指标**（真实服务，单次样本；止于 Host 输出边界，不含 LiveKit 传输和客户端播放）

| 指标 | voice_vision | text（同一次） | voice（关闭视觉） | text（同一次） | text（纯文本会话） |
|---|---|---|---|---|---|
| 首字 | 6,575 ms | 1,717 ms | 5,862 ms | 1,006 ms | 1,632 ms |
| 首音频帧 | 8,330 ms | 3,745 ms | 6,629 ms | 2,519 ms | —（无音频输出） |
| 响应完成 | 9,060 ms | 4,176 ms | 7,121 ms | 2,896 ms | 1,705 ms |
| 语音结束 → STT 终稿 | 2,459 ms | | 1,664 ms | | |
| 语音结束 → Turn 提交 | 2,462 ms | | 1,895 ms | | |
| 模型请求 → 首个事件 | 3,610 ms | 1,055 ms | 3,550 ms | 542 ms | 1,098 ms |
| TTS 请求 → 首段 PCM | 1,499 ms | 1,446 ms | 696 ms | 1,402 ms | |

**`voice_vision` 未通过：严格答案校验（T-10C 2.4 遗留，待用户决定）**：非交互那次的 JSON 里，转录只有 `What color is the card on my screen?`，样本第二句「Answer in one word.」被 STT 丢掉，模型答 `The card is green.`，不是单个词，判为 `answer` 阶段失败。两次音画运行都是这样，与 T-10C 的发现相同；本轮没有改样本或判定。

**KD-17 未复现**：三次有语音的运行里，turn taking 连续 HOLD（约 +825、+1,361、+1,861 ms），直到 STT 终稿到达（+1,901 ms）后才提交，没有出现 T-10C 那样在等待超时后 CANCEL。这只说明这几次 STT 来得够快或判定一直在 HOLD，不说明 KD-17 已修复；KD 表状态不变。

**验收中发现并修复的报告问题**

1. **`services.external` 的误报（T-10C 起就有）**：一个更早的 runner 启动失败时，向量库 runner 根本没启动，模型 provider 却显示 `not reached, failed (vector store embeddings)`，标题因此多算一项失败。原逻辑按整个运行时是否启动来判断。改为按启动时会嵌入的 runner 自己的结果判断：这些 runner 由 `InferenceRunner.PROVIDERS` 识别（`session.embedding_runners`），不写死插件名。全部启动为 passed，有一个失败为 failed，没轮到为 not observed，并写明「an earlier runner did not start」。
2. **缺模型的处理建议过时**：`models.runners` 仍建议「Start `alphaavatar dev …` once with network access」。改为先说本命令自己的做法：「Run doctor again in a terminal and agree to the download, or start `alphaavatar dev …` once with network access」。
3. **允许下载时仍写「offline」**：`models.runners` 通过时的摘要固定写「started from the cache, offline」。改为按诊断进程是否离线，写「from the cache, offline」或「with downloads allowed」。
4. **纯文本会话的最后一帧**：首音频帧写「no audio output in this session」，最后一帧却写「not observed」。会话没有音频输出时，两项都写这个原因。

复验（修复后的构建，重新安装；这次 setup 走无人值守路径 `config init accept` → `setup accept < /dev/null`，同样从真实索引下载 105 个包、514 MB）：
- 拒绝下载：`services.external` 改为 SKIP，模型 provider「reached: not observed, passed: not observed (vector store embeddings: an earlier runner did not start)」，失败从 3 项降为 2 项；处理建议为新文本。
- 纯文本加同意下载：turn taking 模型再次下载，runner 3.15 s 启动，`text` 通过；两项音频指标都写「no audio output in this session」。
- 第 3 条由新的单元测试覆盖，文本报告里通过的分组不显示该摘要。

新增测试：`test_session.py` 的 `test_the_model_provider_is_judged_by_the_starts_of_the_runners_that_embed`（参考 bundle：未到达、启动、失败三种）、`test_the_runners_summary_says_whether_downloads_were_allowed`；下载拒绝的测试加了处理建议的断言；`test_measure.py` 的 `test_a_session_without_audio_output_says_so_for_each_audio_figure`。变异 G1–G5 全部被抓到（`scratchpad/evidence8/mutants8-c.log`）。修复后全量 491 项通过，拦截已移除的包后也是 491 项通过；Ruff、格式、pre-commit 通过。改动文件：`doctor/session.py`（`embedding_runners`、`_service`、`_runner_check`）、`doctor/measure.py`、`docs/cli/doctor.md`（`services.external` 如何判断只在 runner 启动时用到的模型 provider），以及上述测试。修复后重新构建，沙箱录制和离线测试替身录制都在修复后的代码上重做，`docs/cli/cli.html` 随之重新生成。

**计费调用**：同意下载那次、非交互那次、关闭视觉、纯文本，以及复验的纯文本，共 5 次运行调用了 OpenAI（对话、记忆与画像任务、embedding、STT、TTS；纯文本两次没有 STT 和 TTS）。两次拒绝下载、拒绝测试和无人值守 setup 都没有调用。

**清理**：验收目录在复验后删除；凭据副本在复验后删除。
