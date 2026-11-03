# AlphaAvatar v0.6.9 Doctor — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 从 T-10B 开始，Doctor 的设计、实现、实验、测试、限制以及后续 review 收尾都记录在本文件，按时间顺序追加。
- 统一的 KD/O 表仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`；T-10A～T-10T3 记录在 [claude-code-t10-zh.md](claude-code-t10-zh.md)。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| T-10B | 基础 Doctor：静态、只读、离线的安装与配置诊断（`doctor`、`doctor <bundle或文件> [KEY=VALUE...]`、`--list`、`--json`） | 2026-11-03 | `7c53c4a` | 未提交 | 待 review：本地全量 300 passed（CI 方式 ×1，检出前后一致）；新增 4 项 Doctor 测试，10 个变异全部被发现 |

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
