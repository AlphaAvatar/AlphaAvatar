# AlphaAvatar 缺陷记录

这里记录当前已知缺陷和已修复项。复现细节和历史验证见 [2A 开发日志](agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md)、[Doctor 开发日志](agent-logs/2026-11/2026-11-03/claude-code-doctor-zh.md)及 [Context 开发日志](agent-logs/2026-11/2026-11-04/claude-code-context-zh.md)。设计限制和延期的产品决策与已确认缺陷分开记录。

## 已知缺陷

| 编号 | 问题 | 当前状态 |
| --- | --- | --- |
| KD-7 | 工具默认审批行为与部分示例文档不一致。 | 待单独审查工具执行授权和用户确认策略。 |
| O-10 | 缺少 `voice.stt.model` 时，配置检查可能通过，直到装配会话才报错。 | Doctor 可定位到 `session.start`。静态校验待统一。 |
| O-11 | 离线且模型缺失时，模型解析可能留下空缓存目录和锁文件。 | 待修复。 |
| KD-19 | 固定的两句样本经分段 STT（`gpt-4o-transcribe`）转写时，经常只剩第一句。 | 遗漏发生在端点返回的文字里，插件如实传递。只改停顿或只换声线都没有改善（各 10 次，0～2 次两句都在）；被丢的总是指令式的第二句，内容是否是原因待验证。通用提示在固定样本上把完整率从 1/10 提到 8/10，独立多句样本本就完整，默认值未改（Doctor 日志第四批）。 |

## 已修复

按代码所在的位置分节：插件分 foundation、perception、tools 三类；插件之外，Host、运行时与核心库、工具脚本与测试基础设施各一节。插件的配置模型在 `avatar-agents/alphaavatar/agents/configs/plugins/` 等处，按它所属的插件类别归入。

### 插件 · foundation（context、loop、provider、voice）

| 编号 | 问题 | 修复 |
| --- | --- | --- |
| KD-18 | context：每轮请求都重发 History 中的全部图片，累计内联字节超过 Responses `max_inline_bytes` 后，此后每一轮都被拒，纯文字轮也一样。 | History 仍完整保存。请求把历史图片（用户消息和工具输出）在原位置换成 `<image_not_replayed />`，只有本轮图片内联发送。 |
| KD-22 | provider：OpenAI Responses 的 `model.request_sent` 在 `create()` 返回或抛错后才记，晚于请求真正交给传输层，Doctor 据此算的发送时刻偏晚。 | 发送时刻改由 httpx 请求钩子在交给传输层时逐次记录，每次尝试一条。 |
| KD-27 | voice：分段 STT 请求计时（`stt.request`）的首事件和终稿两项，起点取成请求头写完，而不是收到应答头，多算了上传和服务等待。 | 两项改从 `receive_response_headers.complete` 起算，真实基线里首事件为 0.4～3.0 ms。 |
| KD-28 | voice：没有 trace 的 STT 请求（调用方自带 `client=`，或在交给传输层之前就失败）被记成 `reused=True`。 | 只有 trace 看到请求头发出且没有建连才记复用，未观测时不记；Doctor 对这类请求只给排队一行，其余写 "not observed"。只有离线验证。 |
| KD-30 | voice：每个进程第一段 STT 请求要在事件循环上做 openai SDK 的懒加载（首次访问 `client.audio.transcriptions`），约 95～103 ms 落在首段的请求路径上。 | STT stream 打开时在线程里预先访问，请求等它完成，不在事件循环上导入。真实运行里，首段没有落在任何网络段的时间从约 98 ms 降到约 3～6 ms，本次未观察到输入延迟增加；约 97 ms 的首次加载已移出请求关键路径，端到端收益仍待验证。 |
| KD-20 | 同一 STT stream 连续多段时，每段都新建 TCP 和 TLS 连接。 | 读原始响应，过了 `[DONE]` 仍读到 body 结束，读取与关闭共用期限。真实端点上同一 stream 连续 5 段，后 4 段都复用连接（2 次共 8/8），收尾 0.3～3.9 ms（Doctor 日志第四批）。 |
| KD-32 | SSE 只按 LF 分行，CR 换行的事件被拼成错误的 JSON。 | 用 `iter_text()` 解码字符，按 CR、LF、CRLF 分行；不用会在 `\u2028` 处断行的 `iter_lines()`。 |
| KD-33 | 无效终稿（`text: null`）在请求日志里被记成成功的 final。 | 有效终稿发出后才记录；日志的 outcome 与消费者收到的终态一致。 |

### 插件 · perception（memory、persona、router）

| 编号 | 问题 | 修复 |
| --- | --- | --- |
| KD-2 | memory、persona 的向量库配置（`avatar-agents/alphaavatar/agents/utils/vdb/config.py`）：校验时写入 `*_VDB_*` 环境变量（配置被拒绝时也写），并构造 QdrantClient，构造时还会发出一次 HTTP 版本请求，客户端从不关闭。 | `snapshot_vdb_config` 只读取 `QDRANT_URL`、`QDRANT_API_KEY` 作快照，不写环境变量、不构造客户端；Runner 只从启动快照取配置。 |
| KD-4、KD-5 | persona：LanceDB 用户筛选未转义，保存错误未完整传播。 | 校验并转义筛选值，显式处理保存失败。 |
| KD-6 | memory：被动 Memory 检索的完成状态不完整。 | 在完成边界记录诊断状态。 |
| KD-12、KD-13 | router（语音合成）：取消准备中的 TTS 被误报为合成失败；打断后漏计已交付给消费者的音频。 | 准备阶段的取消在 output 已失效时按打断处理；按 Output 的接纳序号对齐已交付的音频。 |
| KD-14 | router（音频活动）：VAD 积压导致语音前缀丢失，余段仍被作为完整语音发布。 | 缺口后先恢复可信的静音或结束边界，再接纳新的语音段。 |
| KD-17 | 已决定回应的语音轮在短暂等待 STT 后被取消，迟到的有效终稿无法提交。 | 0.75 秒只做观察，3 秒期限后才取消。真实 STT 加受控终稿延迟（测试包装器、测试终点模型）3/3：期限内的终稿并入原轮；超时后同源下一轮正常提交，旧终稿按退役片段拒收、不串入新轮（Doctor 日志第四批）。 |

### 插件 · tools（mcp）

| 编号 | 问题 | 修复 |
| --- | --- | --- |
| KD-3 | Tools 配置（`avatar-agents/alphaavatar/agents/configs/plugins/tools/tools_config.py`）把解析后的 MCP secret 写入 `MCP_*` 环境变量。 | `<ENV>` 占位符在校验时解析进 `servers` 快照，不写环境变量；子进程使用启动快照。 |
| O-7 | `MCPConfig` 的校验错误可能带出原始 `servers` 输入，其中可能有明文 secret。 | `MCPConfig` 与实际校验入口 `AvatarConfig` 都设置 `hide_input_in_errors=True`。 |

### Host（CLI 与 Setup、Doctor、执行进程、日志、Health）

| 编号 | 问题 | 修复 |
| --- | --- | --- |
| KD-8、KD-9 | Health 默认监听所有网卡，Host 另有重复诊断模块。 | 默认监听回环地址，移除重复模块。 |
| KD-15、KD-16 | Host 日志 socket 启动失败留下目录，关闭时可能遗漏末条日志。 | 失败时回收目录，关闭前有界排空记录。 |
| KD-21 | `setup <bundle>` 的错误会带出 URL 片段或校验输入里的原值。 | URL 错误改为固定文字；传输设置的校验错误只列字段位置。 |
| KD-23 | Doctor：`runtime_start` 计时包含缓存扫描，说明还按扫描结果写「downloaded」。 | 计时止于启动自身结束，缓存扫描移到计时之后；说明只写缓存净变化。 |
| KD-24 | Doctor：合并标注打在没有值的行上，例如模型什么都没回答时，最后一行被写成「从更早的节点并入」。 | 没有值的行不带 `merged`，改为写明哪个节点没有观测到。 |
| KD-25 | Doctor：Context built 取 `model.started`，把 build 返回之后的请求组装也算进了这一节点。 | loop 插件在 build 返回处记录 `context.built`，带同一个请求号，由 Doctor 读取。 |
| KD-29 | 安装后的命令以 `python -I` 运行 Host，但执行子进程不带 `-I`，调用方的 `PYTHONPATH` 和 `sitecustomize` 仍能进入子进程。 | Host 以 `-I` 运行时，子进程也加 `-I`，环境变量照常继承；开发环境不变。离线用 editable 环境和真实子进程验证。 |

### 运行时与核心库（avatar-agents、avatar-core）

| 编号 | 问题 | 修复 |
| --- | --- | --- |
| KD-1 | `AvatarConfig` 校验时创建 Workspace、写入 `AVATAR_WORK_DIR` 和 `AVATAR_TIMEZONE`；同一进程里重复校验会让路径层层嵌套。 | `AvatarInfoConfig` 只做纯校验，loader 不建目录、不写环境变量；资源由启动流程管理。 |
| KD-10 | 身份改绑可能影响旧工作区和画像增量（运行时的工作区与参与者，以及 persona、memory）。 | 改绑移除磁盘迁移，画像按参与者隔离并保留已提交轮次的身份历史。 |
| KD-11 | 任一 Runner 处于故障状态时，Inference 运行时拒绝所有新连接，会话首次使用另一个健康的方法时得到裸 `ConnectionResetError`。 | 服务准入与目标 Runner 的健康分开判断，健康的方法照常可用；总体存活状态保留给 Host 监测和恢复。 |
| KD-31 | 设置检查把「能收任意关键字」当成「支持该选项」，给只接受 `model` 的转发型 STT 也传入默认 `delay`。 | `supports()` 只认明确写出名字的参数。 |
| KD-34 | `speaker.association` 记录的时刻和结果不对：显式实体已就绪却晚记，短句已绑定却记成 unbound，失败、退役等路径没有记录。 | 在 `ParticipantRuntime` 释放等待的唯一入口记录首次就绪的时刻、结果和原因（`participant.segment_ready`）。 |
| O-1 | Runner 初始化期间被取消，要先等满 `close_timeout`（默认 5 秒）才终止。 | 从未就绪的进程直接终止并回收；已就绪的照旧走关闭握手。 |
| O-3 | Inference 和 Host 日志的 Unix socket 建在临时目录下，路径过长时启动失败，没有预检。 | core 的 `private_socket_path`：超过 100 字节时回退到 `/tmp` 下新建的私有（0700）目录，都不满足时明确报错。 |

### 工具脚本与测试基础设施

| 编号 | 问题 | 修复 |
| --- | --- | --- |
| KD-26 | `scripts/quality/doctor_compare.py` 起初只照抄报告自带的汇总；之后改为重算统计值，但仍不核对场景分组、指标集合和 `stopped_at`：删掉一个汇总或指标、写入矛盾的停止计数都能通过。 | 从逐轮数据重算并核对每项统计、场景分组、指标集合和 `stopped_at`，不一致时写到 stderr 并以 1 退出。 |
| O-13 | 测试基础设施：pytest-asyncio 新建的事件循环无人关闭，全量运行结束时报 `unclosed event loop`，pytest 以 1 退出。 | 根 `conftest.py` 在 `pytest_configure` 里清掉当前事件循环，不再新建。 |

## 观察与延期

| 编号 | 项目 |
| --- | --- |
| KD-10 | 跨身份访问旧 Memory 记录属于延期的多人历史策略，历史所有者继续保留。 |
| O-2、O-4、O-6、O-9 | 分别跟踪插件导入副作用、感知任务取消、LanceDB 弃用警告和 Host 校验错误的展示边界。 |
| O-12 | 默认 LanceDB Runner 启动时会探测 embedding 维度，Doctor 需获得相应的外部调用授权。 |
| O-14 | Context 的 `<committed_text>` 回退只在本轮既无转录也无打字时生效。如果感知缺口丢了转录事件却保留了打字事件，语音会静默缺失。尚未复现。 |
| O-15 | 每个 runtime 的第一个模型请求，在 Context built 之后多约 90～160 ms：client 就绪 5～59 ms，其余在 SDK 交给传输层之前；之后各轮约 9 ms（Doctor 日志第四批）。 |
| O-16 | 视觉关时，终稿到 Turn 提交之间多出 36～155 ms。真实运行里关联在语音段结束后 73～89 ms 已就绪，提交等待为 0；这段时间花在 hold 到 commit 的再判定上，来源待计时定位。离线证据：慢窗口和串行队列积压会让关联变晚（Doctor 日志第四批）。 |
| O-18 | 静音或低噪声单独送给 STT 时，所有语言设置都会编出文字，加了提示时输出 `context:` 之类。 |
| O-17 | 2026-11-07 一次全量运行里，Doctor 的 Ctrl+C 中断用例报 `session.cleanup` FAIL；之后单独运行 3 次、整个文件运行 2 次、全量运行 1 次都没有复现。失败那次留下了什么没有记录，原因未定位。 |
