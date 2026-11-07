# AlphaAvatar v0.6.9 交互配置（`alphaavatar setup`）— Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 本文件是交互配置的主日志：`alphaavatar setup` 的提问、给定 bundle 的安装，以及 `config init` 之后的下一步。按时间顺序追加。
- 同一轮的 Doctor 运行时测试记在 [claude-code-doctor-zh.md](../2026-11-03/claude-code-doctor-zh.md)；CLI 渲染和 HTML 预览沿用安装日志的 [CLI 展示记录](../2026-11-05/claude-code-install-zh.md#第-1-项-cli-展示统一基线-0a85122)。
- 统一的 KD/O 表仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 交互配置第一轮 | 去掉 `--preset`；`setup` 以 `config init` 的参考配置为起点逐项询问；新增 `setup <bundle>`，按已有 bundle（含编辑）的设置安装、校验、启用，不导入插件；基础包上 `config init` 的下一步改为 `setup <bundle>`；CI 与无人值守改走显式 bundle | 2026-11-06 | `2fc4f398` | 用户已提交（`38fad3c3`） | 部分被第二轮修正：只写模型名的 provider 任务、LiveKit 凭据 |
| 交互配置第二轮 | `setup <bundle>` 的两处收尾：只写 `model` 的 provider 任务按 `ProviderTaskConfig` 默认的 `kind`、`backend` 计入安装计划；给定 bundle 在安装前离线校验所选 LiveKit 后端的凭据。都在只装基础包、空环境的子进程里验证 | 2026-11-07 | `38fad3c3` | 用户已提交（`d5080d5`） | `d5080d5` 审查：URL 解析异常会带出原值（第三轮修复）；Quality 因字节码目录失败（第三轮修复） |
| 交互配置第三轮 | LiveKit URL 校验的错误不再带出原值，交互首配对最终生效值做同一校验；Quality 的裸基础包子进程不再写字节码 | 2026-11-07 | `d5080d5` | 未提交（用户提交） | 待审查；干净检出的 Quality 同等命令见 Doctor 日志同一轮第 6 节 |

## 历史记录（合并来源）

交互配置此前分散记在安装日志和 Doctor 日志里。原文都保留，原日志头部加了指向本文件的链接。

| 原位置 | 原结论 | 现状 |
|---|---|---|
| 安装日志「第 1 项第二轮」第 3 节 | `setup` 有交互问答和 `--preset default|remote` 两条入口，共用一条安装路径；`--preset` 从环境读凭据；16 种选择组合的需求与 `resolve_capabilities` 对拍 | 本轮去掉 `--preset`。交互入口保留，改以参考配置为起点；无人值守改为 `setup <bundle>`。`Selection` 与需求对拍保留 |
| 安装日志「第 1 项第三轮」第 3 节 | 预设不存凭据，交互先问是否保存；「逐项选择」里模型和语音可指向自托管服务；基础包上 `config init` 的下一步是 `alphaavatar setup`，另建一个 bundle | 凭据和自托管端点不变。`config init` 的下一步改为 `alphaavatar setup <bundle>`，装的就是刚生成的这个 bundle |
| 安装日志第四至第六轮各自的第 1 节 | 自托管凭据按端点命名并绑定到最终生效的 URL | 不变 |
| 安装日志「第 1 项 CLI 展示统一」第 3 节 | setup 四步展示、提问放在步骤下、失败与中止写 stderr、`--plan` 的 stdout 只有 JSON | 不变；给定 bundle 时四步的内容见本文件第 3 节 |
| Doctor 日志「T-10C `6a593f2` 真实服务验收」第 6 节 | 第 9 条：`config init` 轻量交互入口的方案（预设、处理器、工具逐项选，`--yes` 无人值守），待 review，未实现 | 被本轮取代：交互配置由 `alphaavatar setup` 承担；`config init` 保持非交互，只生成参考 bundle |

---

## 交互配置第一轮（基线 `2fc4f398`）

依据：Codex 对 `2fc4f398` 的复核，第一阶段（`setup` 和 `config init`）。要求：从菜单、帮助、文档和 CI 去掉 `--preset remote` 和 `--preset default`；保留本地推理；参考配置默认开启语音和视觉，本地能力按需开启，模型、语音和向量库各选后端，自托管服务继续支持；`setup` 从与 `config init` 共用的参考配置出发，先能力、再凭据、确认计划，然后安装、校验、启用；新增 `setup <bundle>`；CI 和无人值守用显式 bundle，凭据来自环境；`setup --plan` 的 stdout 保持纯 JSON。所有改动在未暂存的工作区。

### 1. 去掉预设

- `choices.PRESETS` 和 `--preset`、`--no-voice`、`--no-vision`、`--vector-store` 删除；帮助、`docs/cli/setup.md`、`DEPLOY.md`、README 和 CI 都不再提预设。
- 「远端推理」不再是一个入口：交互时把「本机模型」答成否即可，需求集合与原 `remote` 相同（85 个包、212 MB）。

### 2. 交互：以参考配置为起点

- `alphaavatar setup` 没有 bundle 参数时，必须有终端；否则报错退出 1，提示 `alphaavatar setup <bundle>` 和 `config init`。
- 第 1 步先说明出发点（参考配置：语音、视觉开启，带 Memory 和 Persona，模型来自下面选的后端），然后依次询问，回车保留参考值：
  1. 语音、视觉、本机模型（turn taking、寻址、人脸与说话人识别）；
  2. 向量库：工作区里的 LanceDB，或你的 Qdrant；
  3. 模型是否来自 OpenAI，否则问自托管服务的 URL 与三个模型；开语音时同样问语音；
  4. bundle 名和 Avatar ID。
- 第 2 步问凭据，第 3 步列出计划后确认，然后安装、校验、启用。凭据用途的文案改为 `…, from OpenAI`（原文「OpenAI's the model…」语法有误，上一轮第 9 节第 4 条）。

### 3. `setup <bundle>`

- **读取**：`configs.load_selections(source)` 复用 `load_application` 的组合步骤（抽出 `_composed`），只校验 `HostConfig` 和 `AvatarConfig`，不解析插件。基础包上还没装任何插件，这一步也能成功。
- **规划**：`choices.bundle_requirements(host, avatar, catalog["plugins"])` 按设置求需求，与 `resolve_capabilities` 的规则一致，但不导入任何插件：
  - Host 的 RTC 后端；
  - 每个选中实现：查 catalog 的 `plugins` 表（能力类型 → 实现名 → 需求）；
  - 插件设置里的 provider 任务：扫描含字符串 `model` 且带 `provider` 或 `backend` 的字典，跳过 `enabled: false` 的部分；`kind` 缺省为 `llm`，后端缺省为默认后端；
  - 默认 Memory、Persona 的向量库后端和其 embedding provider；默认 MCP 用 LanceDB；
  - 默认 Router：语义寻址开启且配置了 STT 时要 `router[semantic]`，turn taking 开启时要 `router[turn-taking]`；默认 Persona：按 speaker、face 开关；
  - 设置里没写的开关按开启计，最多多装一个包。
- **拒绝**：catalog 里找不到的选择，在安装任何东西之前报错，用设置位置命名，例如 `tools.rag.plugin: tools.rag 'default'`，退出 1。
- **四步**：
  - `01 Capabilities` 显示 `Bundle <name> · Voice on · Vision on · Local models on`；
  - `02 Credentials` 显示 `From the environment, .env or those stored`，不问也不存；
  - 有终端时列出计划并确认，没有终端时不问；
  - 校验用新环境对这个 bundle 跑 `config check`，缺凭据在这一步失败，什么都不启用；
  - 启用用 `template.set_default_bundle`：一次设置替换把它设为默认，失败时清理暂存文件。
- 同时给出 bundle 和 `--name`／`--avatar-id` 时，参数解析直接报错。

### 4. `config init` 的下一步

- 基础包上（还没运行过 setup）：`Next` 只有 `alphaavatar setup <name>`。
- 完整环境：仍是 `config check <name>`，再 `doctor <name>`（上一轮用户中途要求）。
- 覆盖已有文件的错误改为一行：`ERROR Refusing to overwrite an existing file: <path>`。

### 5. CI 与无人值守

- `linux-package.yml`：
  - `grep -F 'alphaavatar setup reference' init.txt`；
  - `config check` 的两处 `grep` 加 `COLUMNS=1000`（窄终端下缺包诊断会拆行）；
  - 新增「Setup plans the reference bundle from its settings」：`setup reference --plan > plan.json 2> plan.err`，第一个字符是 `{`，stderr 有 `Bundle reference`，计划里有 torch、llama-cpp-python、insightface；
  - 新增「Setup installs, checks and enables the reference bundle」。
- `packaging/linux/build.sh` 的自检：参考 bundle 由 `config init` 生成后经 `load_selections` 和 `bundle_requirements` 规划，必须等于 `requirements(Selection())`；「本机无模型」的计划里不得出现 torch、torchaudio、llama-cpp-python、insightface、transformers、onnx、scipy。构建日志：`reference bundle: 105 packages, 514 MB`，`no model on this machine: 85 packages, 212 MB`。

### 6. 改动文件

| 文件 | 改动 |
|---|---|
| `avatar-host/.../configs/loader.py`、`configs/__init__.py` | `_composed`、`load_selections` |
| `avatar-host/.../setup/choices.py` | 删 `PRESETS`；`bundle_requirements`、`_tasks`、`_on`；凭据用途文案 |
| `avatar-host/.../configs/template.py` | `set_default_bundle` |
| `avatar-host/.../setup/environment.py` | `check_environment` 接受 bundle 名或单文件 |
| `avatar-host/.../cli/app.py` | `setup [bundle]`，与 `--name`／`--avatar-id` 互斥；删预设选项 |
| `avatar-host/.../cli/commands/setup.py` | 以参考配置提问；给定 bundle 的规划、拒绝、四步与启用；结果行写 stderr 前空一行 |
| `avatar-host/.../cli/commands/config.py` | `Next` 与覆盖错误 |
| `packaging/linux/build.sh`、`.github/workflows/linux-package.yml` | 见第 5 节 |
| 测试 | `test_choices.py`：已有 bundle 的需求、编辑后的 bundle 与装好后 `start` 解析一致、未覆盖选择按设置命名、裸基础包不导入插件（子进程拦截 `alphaavatar.plugins.*`）；`test_setup.py`：无终端也无 bundle 时拒绝、给定 bundle 的规划与拒绝、只有安装成功才启用、Ctrl+C 结束提问行再报告；`test_check.py`：基础包 `Next` |
| `docs/cli/setup.md`、`config.md`、`README.md`（CLI）、`DEPLOY.md`、`README.md` | 去掉预设；交互与 `setup <bundle>`；体积 |

### 7. 验证

本轮的交互配置、Doctor 和 CLI 展示一起验证。数字是三部分完成后的最终结果。

**本地**
- 全量测试 491 项通过；拦截已移除的包后再跑一遍，也是 491 项通过（含 Doctor 真实验收后新增的 5 项）。静态检查（Ruff `--no-cache`、格式、`check_workspace.py`、`uv lock --check`、`git diff --check`、`bash -n`、pre-commit）全部通过。
- 变异：本部分 10 个（S1–S10），全部被抓到。首轮 S2（关掉的 provider 任务仍计入）和 S4（缺省开关算作关）存活，都是测试缺口：补了「直接改 profile 文件」的两种编辑（开关省略；关掉的部分写一个没有安装来源的后端），各自与 `resolve_capabilities` 对拍后被抓到。证据：`scratchpad/evidence8/mutants8.log`、`mutants8-b.log`。
- 构建自检：参考 bundle 105 个包、514 MB；本机无模型 85 个包、212 MB，且不含 torch 等本地推理库。基础包 63 MB，glibc 下限 2.17。

**干净沙箱（bubblewrap 里的 Ubuntu 24.04 rootfs，本轮最终构建，伪终端录制）**

| 录制 | 结果 |
|---|---|
| `setup-first-100` | 普通 `setup`：参考配置逐项回车，只把本机模型答成否；85 个包、212 MB；`Validate PASS · 3 runners`；环境 636 MB |
| `init-bare-100` → `check-bare-72` | 基础包上 `config init` 的 `Next` 是 `alphaavatar setup reference`；setup 前 `config check` 退出 2，72 列下缺包拆成四行 |
| `setup-bundle-100` → `check-72` | `setup reference`：105 个包、514 MB，`PASS · 8 runners`，环境 1.7 GB；之后 `config check` 通过 |
| `setup-plan.json` | `setup reference --plan` 的 stdout 第一个字符是 `{`：105 个制品，514,285,108 字节；步骤在 stderr |
| `setup-unserved-72` | 选了 `tools.rag.plugin: default`：安装前拒绝，退出 1，标题后只空一行 |
| `setup-cancel-72` | 计划处答 n：`WARN Cancelled`，退出 1；72 列下步骤摘要按 ` · ` 换行 |
| `setup-interrupt-72` | 提问处 Ctrl+C：提问行结束后空一行再 `WARN Interrupted`。退出码在沙箱里是 254（bubblewrap 的 PID 1 也被中断），setup 自己返回 130 由测试确认 |
| `setup-nocolor-100` | `NO_COLOR=1`：没有任何转义字符，也没有单独的回车；进度行换行 |

**真实服务验收（用户确认后，本机，隔离的前缀和 home；详见 Doctor 日志同一轮第 9 节）**
- 交互：`alphaavatar setup --artifacts …` 逐项回车，得到含本机模型的参考 bundle：从真实索引下载 105 个包、514 MB，`Validate PASS · 8 runners`，环境 1.7 GB；录制里没有任何凭据值。
- 无人值守：`config init accept` → `setup accept --artifacts … < /dev/null`，同样下载 105 个包、514 MB，不提问，`Validate PASS · 8 runners`；管道里每个文件一行，过长的文件名单独换行。
- 已装环境上的第二个 bundle：`config init ci` → `setup ci < /dev/null` 复用同一环境；此时 `config init` 的下一步是 `config check`、`doctor`。

**推送后待 CI 验证**
- linux-package 的新步骤：`setup reference --plan` 的 stdout 为纯 JSON、计划含 torch／llama-cpp-python／insightface；`setup reference --artifacts` 安装、校验、启用。

### 8. 过程中的问题与更正

- **测试夹具的插件表**：开发环境装了 rag，夹具的 `plugins` 表因此多出 rag，规划不再报未覆盖；改为只取 catalog 里有的键。
- **命名 bundle 的加载**：需要 `ConfigSource(path, name, home=paths.root)`；环境变量 memory 的编辑要写 `provider.task=memory.env_delta`。
- **Qdrant 选择**：需要 `QDRANT_URL`，测试里补上。
- **失败前的空行**：拒绝发生在任何步骤之前时，标题后出现两个空行；改为只在标题之后已有输出时才空一行（`_apart`）。
- **Ctrl+C 停在提问处**：光标停在提问行末，`WARN Interrupted` 紧贴其后；`Report.ask` 在 Ctrl+C 或输入结束时先结束该行。

### 9. 待复核

1. **`setup <bundle>` 的确认**：有终端时仍列计划并确认；无终端（CI）时直接安装。如果希望有终端时也能免确认，需要另加选项，本轮没加。
2. **默认开关按开启计**：设置里没写的开关算开启，规划可能多一个包，不会少。
3. **`config check` 的提示**：缺包时仍写 `` `alphaavatar setup` installs it ``，没有带上 bundle 名；这一行由能力检查生成，不知道当前命令选的 bundle。

---

## 交互配置第二轮：schema 默认的 provider 任务与 LiveKit 凭据（基线 `38fad3c3`）

依据：基于 `38fad3c3` 的要求，「`setup <bundle>` 的两个问题单独收尾」：安装计划要处理依赖 schema 默认 `backend` 和 `provider` 的模型任务；现有 bundle 启用前要离线校验所选 LiveKit 后端的必需凭据；用只装了基础包的环境验证，避免已有依赖和环境变量掩盖问题。所有改动在未暂存的工作区。

### 1. 只写模型名的 provider 任务

- `start` 按插件自己的 schema 找 `ProviderTaskConfig`；基础包里没有插件，`bundle_requirements` 只能读原始设置。原规则要求字典里写了 `provider` 或 `backend` 才算任务，于是 `loop.init_config.model: {model: gpt-4o}` 这类只写模型名、其余用默认值的任务被漏掉，计划里缺它的默认后端。
- 现在：插件设置里带字符串 `model` 的字典就是 provider 任务（其他设置的模型都用 `name` 命名，不会误判），缺的 `kind`、`backend` 取 `ProviderTaskConfig` 自己的默认值（`llm`、`langchain`），不再写死。
- 测试：
  - `test_choices.py` 的 profile 编辑新增「a task on the schema's defaults」，与装好后 `start` 的解析结果对拍；
  - 新增 `test_a_bare_base_plans_a_task_left_to_the_schemas_defaults`：在拦截全部 `alphaavatar.plugins.*` 导入、环境只有 `PATH` 和 `HOME` 的子进程里规划；catalog 去掉 `provider.llm 'langchain'` 后，必须报出 `loop.init_config.model: provider.llm 'langchain'`。默认后端的需求和向量库 embedding 的需求是同一个包，只比需求集合区分不出新旧规则，所以用这个方式。

### 2. LiveKit 凭据

- `sessions.factory.check_session_credentials(config, env)`：按 `start` 读取的方式离线检查所选会话后端的凭据，不联系服务器，错误里只出现变量名。LiveKit：三个变量都要有，远端地址必须是 `wss://`（本机除外）。`LiveKitCredentials.from_env` 改为接受显式环境，并逐个说出缺了哪些变量（原先 URL 为空时报的是「must not contain credentials…」，容易误解）。
- `setup <bundle>` 在第 02 步、安装之前检查，环境里已合并 `.env` 与已存凭据；不通过就报 `The session transport (livekit) cannot start: …`，退出 1，什么都不装、不启用。
- 测试：
  - `test_setup.py`：缺三个、缺两个、远端非 TLS 三种情况都在安装前拒绝，输出里没有凭据值；原有「只有安装成功才启用」的测试补上虚构的 LiveKit 凭据（CI 会导出它们）；
  - `test_choices.py` 的裸基础包子进程同时报告离线凭据检查：空环境时说出三个变量，给出虚构值后通过。

### 3. 验证

- 全量 511 项通过，拦截已移除的包后也是 511 项；静态检查同 Doctor 日志同一轮第 10 节。
- 变异 H1（只写模型名的任务不计入）、H2（不校验 LiveKit 凭据）都被抓到（`scratchpad/evidence8/mutants9.log`）。
- 构建自检不变：参考 bundle 105 个包、514 MB，本机无模型 85 个包、212 MB；沙箱里的 `config init` → `setup <bundle>` → `config check` 照常通过（录制使用虚构的 LiveKit 凭据）。

## 交互配置第三轮：LiveKit URL 不带出原值；Quality 的字节码泄漏（基线 `d5080d5`）

依据：`d5080d5` 审查的第一批第 1 项。`urlsplit` 或 `.port` 的异常文字会带出 `LIVEKIT_URL` 里的原始片段，`setup <bundle>` 把它拼进 `SetupError` 直接打印；Quality 在 511 项全过之后，被新增的 ignored `__pycache__` 卡在工作区前后对比。所有改动在未暂存的工作区。

### 1. 复现

- 旧 `websocket_url`：`wss://apikey:fakesecret`（把 key 和 secret 填进 URL）报 `Port could not be cast to integer value as 'fakesecret'`；`wss://[fakesecret]:1` 报 `'fakesecret' does not appear to be an IPv4 or IPv6 address`。两条都经 `setup <bundle>` 原样打到 stderr。带 userinfo 的 `wss://u:p@host` 原本就被拒且不带值。
- Quality：在干净克隆（`git clone` 到 scratchpad，`uv sync --all-packages --locked --offline`）里照 `quality.yml` 的 install 任务执行，pytest 之后 `git status --porcelain --ignored` 多出 70 个 `__pycache__` 目录，`diff` 退出 1。单跑 `test_choices.py -k bare` 的 3 个用例就能多出全部 70 个：`bare()` 用只含 `PATH`、`HOME` 的环境起子进程，丢掉了 `PYTHONDONTWRITEBYTECODE=1`。

### 2. 修复

- `host/sessions/livekit/config.py` `websocket_url`：解析和读端口放在 `try` 里，失败时在 `except` 之外抛出，错误文字固定为 `LiveKit URL is not valid: give wss://host[:port][/path] (ws:// only on this machine), the port a number and an IPv6 address in brackets`，不引用原值，也不链接解析器的异常（`__context__` 为空）。scheme、主机缺失和空白字符归到这一条；userinfo、query、fragment 仍是原来那条。`connection.py`、`dispatch.py` 和 `start` 用的是同一个函数。
- `cli/commands/setup.py`：两条路径共用 `_session_credentials(rtc, env)`。
  - `setup <bundle>`：照旧在第 02 步、安装前检查合并了 `.env` 和已存凭据的环境。
  - 首次交互：先把参考 bundle 写成单文件读出 `host.rtc`，再在 `_credentials` 收齐答案后、问是否保存之前，用最终生效值（`os.environ | 输入值`：输入优先，回车沿用已设置的值）检查。不通过就报 `… cannot start: …, as typed or in the environment, .env or the stored credentials`，退出 1：不问保存、不写文件、不安装。
  - `--plan` 在第 02 步之前就返回，仍然只读。
- `tests/setup/test_choices.py` `bare()`：子进程加 `-B`。工作区检查保留。

### 3. 测试

- `test_setup.py` 参数化新增 `userinfo`、`port`（key:secret 写成 host:port）、`IPv6`（括号里是 secret）三种 URL，走真实的 `main(["setup", "reference", ...])`：安装前拒绝，home 下文件不变，stdout、stderr 和 DEBUG 级别的日志记录里都没有虚构凭据。
- 新增 `test_typed_session_credentials_are_checked_before_anything_is_stored_or_installed`：交互输入的 URL 是 `wss://lk-key:lk-fictional-secret`，覆盖环境里的有效值；在问是否保存之前拒绝，三处输出都没有 secret，home 为空，`install` 未调用。
- 变异：换回旧的 `websocket_url`，`port`、`IPv6` 和交互用例失败（输出里出现 `lk-fictional-secret`）；去掉交互路径的检查，交互用例失败。
- 字节码：干净克隆里修复前 70 个、修复后 0 个（同一组 3 个用例）；套用本轮全部改动后，干净克隆的 Quality 同等命令 524 项通过、ignored 状态前后一致（Doctor 日志「Doctor 第一批」第 6 节）。
- `docs/cli/cli.html` 的 Setup 面板已用本批构建在干净根目录重录，见 Doctor 日志「Doctor 第一批」第 9 节。
