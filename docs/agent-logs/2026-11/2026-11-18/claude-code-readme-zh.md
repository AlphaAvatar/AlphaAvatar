# AlphaAvatar v0.6.9 README 全局核对与 `.env` 加载移到 Host — Claude Code 日志

- 分支：`dev/v0.6.9`；日期为 CST。
- 依据：用户 2026-11-18 的要求，即更新 `.env.template`，全局检查 README，把 `agents/env.py` 移出 Agents；审批默认值、RAG `monologue`、Core `livekit` extra 三项由用户决定。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 模板 | `.env.template` 按代码实际读取的变量重写 | 2026-11-18 | `9d71447e` | `c044922a`（用户提交） | 已提交 |
| README 与 `.env` 加载 | 21 个 README 逐句对照源码；`.env` 加载移到 Host；删 RAG `monologue` 和 Core `livekit` extra | 2026-11-18 | `c044922a` | `174d1632`（用户提交） | 已提交 |

`174d1632` 之后的收尾各批次见 [v0.6.9 收尾日志](claude-code-v0.6.9-closing-zh.md)。

## 1. `.env.template`

- 第一版（`c044922a`）：
  - 删了没有代码读取的 `AVATAR_NAME`；注释掉和默认值相同的 `ALPHAAVATAR_MAX_SESSION_SECONDS`。
  - 可选项一律注释：留空的 `NAME=` 会把变量设成空串，挡住 setup 存的同名凭据。
- 本批：
  - `TAVILY_API_KEY` 改为待填，因为 `mm/` 和 `roles/demo.yaml` 启用了 DeepResearch，没有它启动就失败。
  - `GITHUB_PAT` 的注释改用 MCP README 的 `<GITHUB_PAT>` 写法；OpenAI 一行补上 RAG。

## 2. 更正：MCP 的 `<NAME>` 占位符

我曾说 MCP 插件不替换 `<GITHUB_PAT>`，会原样发出，并据此改了 MCP README。这个判断是错的：

- `avatar-agents/alphaavatar/agents/utils/env_utils.py` 的 `resolve_env_placeholders` 在 MCP 启用时替换 `tools.mcp.servers` 里的 `<大写名>`；变量未设时报错，并写出变量名。
- 当时只搜了 MCP 插件目录，漏了 Agents 包。
- MCP README 已恢复原文。`${oc.env:NAME}` 同样可用。

## 3. `.env` 加载移到 Host

`init_env()` 只有 Host 和一个示例脚本调用，而 Host 的 `credentials.py` 直接 `import dotenv`，依赖却只声明在 Agents。现在改为：

- `host/configs/credentials.py` 新增 `load_env_file()`，挨着 `load_environment()`；
- `cli/commands/config.py`、`cli/commands/upgrade.py`、`examples/scripts/stop_demo_livekit_rooms.py` 都改用它；
- 删除 `avatar-agents/alphaavatar/agents/env.py`，和它那条写着 loaded、文件不存在时也照样打印的日志；
- `python-dotenv` 从 Agents 依赖移到 Host 依赖；`uv.lock` 只改了这两处元数据，版本不变；
- 新回归测试 `test_each_variable_comes_from_the_environment_then_the_env_file_then_those_stored`：环境 > `ENV_FILE` 指定的文件 > 存储的凭据，且 `.env` 里的 `ALPHAAVATAR_HOME` 决定读哪个 home。4 个变异（`.env` 覆盖环境、忽略 `ENV_FILE`、先定 home 再读 `.env`、存储的凭据覆盖已设变量）都被抓到。

## 4. README 核对

方法：五路子代理逐句对照源码；凡是会误导或照做会失败的条目，由我再核对源码后才改。按用户决定：

- 工具审批默认 `approval_required: false` 是有意为之，只改文档：
  - `examples/README.md`、`avatar-agents/README.md`、MCP README；
  - 4 个示例 YAML 的注释对齐 `mm/` 示例。
- 删除 RAG `RAGRequest.monologue`，新增 `avatar-plugins/tools/avatar-plugins-rag/tests/test_request.py`；字段放回时测试失败。
- 删除 `avatar-core` 的 `livekit` extra，`uv.lock` 去掉对应条目。
- 根 README 删除整个 Usage 段（用户要求）。

| 范围 | 改正 |
|---|---|
| 根 README | 插件目录锚点（`<h2 id>`）；简介里 Reflection/Planning/Behavior 标为 planned，Character 标为渲染待验证；`config init` 补 `--avatar-id` |
| examples、Agents、plugins | history 完整保留（`history_max_*` 接受但忽略）；删“SDK worker hosting 仍在”；配置第六段 `host`；`application` 段同样由 Host 移除 |
| Host、Core、Agents、RTC、CLI | 目录树补 `upgrade`、`cleanup`、`session/`、`time.py`、`ipc.py`，删 `env.py`；`AvatarCapabilityRegistry`；`reflection/` 是空包；用户字幕读 PerceptionRuntime；`upgrade`、`cleanup` 同一套报告，`cli.html` 未收录 |
| Voice | `tts/codec/pcm.py`；OpenAI 走 SDK + httpx；首包前默认重试 1 次，2.5 s 时可能发第二个请求抢首包（可能计费两次）；`timeout` 不含队列等待；URL 规则只适用于 TTS |
| Provider、Router、Memory、Persona、Character | `langchain` embedding；语义寻址的标签 POSITIVE/NEGATIVE/UNKNOWN；`transcript_timeout_sec` 是硬截止；pip extras；Memory 以 SQLite 为准、其余为投影；人脸跳过屏幕共享帧；按参与者缓存；Character 归 SessionAttachment，停止顺序和故障上报路径 |
| RAG、DeepResearch、MCP | RAG 索引按会话、只收 Host 本地路径、需要用户授权才建、配置与模型；`research` 只是一次 advanced 搜索；Tavily key 必需、插件默认启用、Pango；MCP 审批、compact 截断 |

## 5. 验证

- `ruff check`、`ruff format --check`、`git diff --check`、`uv lock --check`、`check_workspace.py` 均通过。
- README 和 AGENTS 的相对链接与锚点重新检查，0 处问题。
- 5 个示例离线 `config check` 都通过。
- 离线全量测试：
  - `.env` 移动之后：779 passed（302 s）。
  - 本批全部改动之后：779 passed，1 failed（300 s）。失败的是 Router 的 `test_a_final_later_than_the_transcript_wait_still_commits_before_the_deadline`，测得 0.749986 s，要求至少 0.75 s；单独重跑 5 次都通过。本批没有改 Router。

## 6. 发现未改

- RAG 能力描述（`service.py`）仍写 “changes the persistent index”，但索引是按会话的。这是给模型看的文字，不在 README 范围内。
- `${oc.env:NAME}` 缺变量时，`config check` 只显示 `ValueError`，不写出是哪个变量。
- `.github/assets/web-demo-screenshot.png` 随 Usage 段删除后已无引用。
- 根 README 的 Laptop、Mobile 两个标题下没有内容。
- `docs/ROADMAP.md` 里 2026-05 的条目仍提到 monologue，是历史记录，未改。
- Router 的两项计时测试偶发失败，都是测得的等待略短于配置值：一次 199.91 ms 对 200 ms，一次 0.749986 s 对 0.75 s。负载通常只会让等待变长，所以更可能是测量起点或时钟取法的问题，而不是机器慢。未改，等用户决定。
