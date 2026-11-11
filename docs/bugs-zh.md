# AlphaAvatar 缺陷记录

这里记录当前已知缺陷和已修复项。复现细节和历史验证见 [2A 开发日志](agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md)、[Doctor 开发日志](agent-logs/2026-11/2026-11-03/claude-code-doctor-zh.md)及 [Context 开发日志](agent-logs/2026-11/2026-11-04/claude-code-context-zh.md)。设计限制和延期的产品决策与已确认缺陷分开记录。

## 已知缺陷

| 编号 | 问题 | 当前状态 |
| --- | --- | --- |
| KD-7 | 工具默认审批行为与部分示例文档不一致。 | 待单独审查工具执行授权和用户确认策略。 |
| O-10 | 缺少 `voice.stt.model` 时，配置检查可能通过，直到装配会话才报错。 | Doctor 可定位到 `session.start`。静态校验待统一。 |
| O-11 | 离线且模型缺失时，模型解析可能留下空缓存目录和锁文件。 | 待修复。 |
| KD-19 | 固定的两句样本经分段 STT（`gpt-4o-transcribe`）转写时，经常只剩第一句。 | 遗漏发生在端点返回的文字里，插件如实传递；改停顿、换声线无效，指令式第二句最容易整句丢失（第五批）。第六批用当前可用、插件支持的模型对照（同一批样本、自动语言、不加提示）：`gpt-4o-transcribe` 两句都在 7/20，`gpt-4o-mini-transcribe`、`gpt-transcribe`、`whisper-1` 都是 20/20；但在独立多句、中英混合和同会话切换语言的 27 段里，默认 27/27，`gpt-transcribe` 24/27（英文句中的中文词改写成拼音），mini 21/27（中文词译成英文或拼音、一次地名错、切换后输出繁体）；`whisper-1` 慢约一倍。没有候选全部通过，默认仍为 `gpt-4o-transcribe`、自动语言、不加提示（Doctor 日志第六批）。 |

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
| KD-32 | SSE 只按 LF 分行，CR 换行的事件被拼成错误的 JSON；第一次修复把块末尾的 CR 暂存，以 `\r\r` 结束的完整终稿要等下一块数据才发布，收尾期限也不启动。 | 用 `iter_text()` 解码字符，按 CR、LF、CRLF 分行；不用会在 `\u2028` 处断行的 `iter_lines()`。CR 立即结束一行，跨块 CRLF 的 LF 跳过（第五批）。 |
| KD-33 | 无效终稿（`text: null`）在请求日志里被记成成功的 final。 | 有效终稿发出后才记录；日志的 outcome 与消费者收到的终态一致。 |
| O-15 | provider：每个 runtime 的第一个模型请求，在 Context built 之后多约 90～160 ms：client 构建，以及 SDK 在事件循环上首次加载 `client.responses`。 | Loop 初始化时在线程里构建 client 并加载 Responses 资源，请求等同一个任务。同一 WAV 的真实对照里，第 1 轮 Context built → Model request sent 从 122 ms 降到 6.7 ms（视觉开从 151 降到 8.2）。第 1 轮首音频没有下降（4,137 对 4,276 ms），仍比后续轮慢约 0.7 s，主要是模型首事件多约 450 ms、终稿到提交多约 130 ms（Doctor 日志第五批）。 |
| O-17 | loop：Engine 关闭时打断一个刚答完、正在回收身份监视任务的 run，取消落在 `finally` 的这一步，run 没有给出结果而是自己以取消结束；它的 watcher 随之失败，Engine 关闭报错，Doctor 的 Ctrl+C 用例 `session.cleanup` 判 FAIL（进程组和资源都已回收）。第六批 20 次中复现 3 次。 | 回收身份监视任务时的取消与其他收尾步骤一样处理：监视任务照常结束，run 仍归结为 CANCELLED 结果。确定性用例复现修复前的失败；修复后两个 Ctrl+C 用例 40/40 通过，变异被抓到（第六批）。 |

### 插件 · perception（memory、persona、router）

| 编号 | 问题 | 修复 |
| --- | --- | --- |
| KD-2 | memory、persona 的向量库配置（`avatar-agents/alphaavatar/agents/utils/vdb/config.py`）：校验时写入 `*_VDB_*` 环境变量（配置被拒绝时也写），并构造 QdrantClient，构造时还会发出一次 HTTP 版本请求，客户端从不关闭。 | `snapshot_vdb_config` 只读取 `QDRANT_URL`、`QDRANT_API_KEY` 作快照，不写环境变量、不构造客户端；Runner 只从启动快照取配置。 |
| KD-4、KD-5 | persona：LanceDB 用户筛选未转义，保存错误未完整传播。 | 校验并转义筛选值，显式处理保存失败。 |
| KD-6 | memory：被动 Memory 检索的完成状态不完整。 | 在完成边界记录诊断状态。 |
| KD-12、KD-13 | router（语音合成）：取消准备中的 TTS 被误报为合成失败；打断后漏计已交付给消费者的音频。 | 准备阶段的取消在 output 已失效时按打断处理；按 Output 的接纳序号对齐已交付的音频。 |
| KD-14 | router（音频活动）：VAD 积压导致语音前缀丢失，余段仍被作为完整语音发布。 | 缺口后先恢复可信的静音或结束边界，再接纳新的语音段。 |
| KD-17 | 已决定回应的语音轮在短暂等待 STT 后被取消，迟到的有效终稿无法提交。 | 0.75 秒只做观察，3 秒期限到时：有转录的轮照常提交；没有的经 STT 的 fallback 提交缺失转录提示。正常配置验收（`avatar-host/tests/test_transcript_deadline.py`）用 `create_execution` 装配 Router、分段 STT、Context、Loop、Engine，替身只有回环转写服务、VAD 输出、轮次判断模型、模型 provider、TTS、Memory、Persona：1.5 s 的终稿并入原轮；4.5 s 的终稿在 3 s 时变成提示提交，要求重说，提示进入本轮模型输入和之后的历史；迟到终稿被拒收，不进任何请求，下一轮正常；带说话人实体的两段轮保留第一段文字、标出缺失的第二段（Doctor 日志第五批）。 |
| KD-35 | persona（说话人）：身份检索、属性推理与窗口推理共用一个串行队列，前一段的属性推理（真实约 100 ms）和身份检索会推迟下一段的窗口和关联，队列满时还会丢掉窗口；拆出窗口队列后，身份与属性仍共用一条，前一段慢的属性会挡住后一段的身份。 | 三条有界队列：窗口与关联、身份、属性。Turn 的 Context 只等本轮语音段的身份，上限 `speaker.identity_wait_sec`（默认 0.1 s，真实检索 1～8 ms）；身份完成即释放等待，到期的属性才入队，队满只丢属性工作；来源取消、换代和停止回收三条队列的任务；迟到的属性只写回推理时的那个身份。离线通过（第五批、第六批，变异全部被抓到）；真实服务里身份在提交前完成，属性队列未单独压测。 |
| O-21 | router（字幕同步）：关会话时 worker 被取消，若它正在发布回答的转录 final，取消传进输出运行时的终态发布，判为投递失败并关闭实时投递；之后对同一输出再发 `transcript_stopping` final 又失败，`execution.aclose()` 抛 ExceptionGroup。 | 终态 final 由处理器自己的任务发布，worker 只等它；关闭时先回收 worker，再在输出运行时的终态期限内等已开始的 final，每个输出的 final 只发一次。运行期的真实取消、超时和半投递失败照常报错。离线通过：受控背压覆盖一个订阅者已收到、另一个阻塞，单次、并发和调用方被取消的关闭，未开始的 final，以及超期未送达仍报错；变异 4 个全部被抓到（第六批）。 |
| O-20 | router（轮次判断）：麦克风的语音不带说话人实体时，每个 VAD 语音段成了独立候选，段间停顿超过 VAD 阈值，一句话就被切成多个 Turn（第五批 VAD 300 下 18 轮只过 1 轮）。 | 轮次判断重构为一个开放的时序输入窗口，人物实体不再拆分轮次判断的候选，匿名片段在 HOLD 后续接（已合入）。第六批离线用例覆盖匿名、同一实体、不同实体的续接；真实服务中，VAD 300 和 200 下 hesitate、multi（含视觉开）都切成 2～3 段并入同一输入，21 轮都只提交一次，失败只有 pause_in 的 STT 丢句（KD-19）。 |
| KD-37 | router（语义 addressing）：仍按说话人分组——有实体时按来源、代、实体，没有实体时按语音段，连续几段的文字不能合在一起判断，后一段看不到前一段的称呼；Turn 结束按提出的终态决定清理，而不是实际提交。 | 改为与轮次判断一致的时序输入窗口：上一次实际提交覆盖的输入之后的全部转录，按媒体时间排列，匿名、同一实体、不同实体同在；每个转录到达即异步重评，读到它为止的窗口，结果只标注它自己的 observation，证据记实际读到的上下文，主体用它自己的实体或段关联；完成时校验上下文未变，过期结果丢弃。消费真实 `TurnSnapshot`：只回收其覆盖的片段并转为有界历史，早于该 Turn 开始就已结束的语音视为被取代；提出的 COMMIT、被拒或延迟的确认都不推进。来源取消与换代、context 切换、缺口、stop 各自清理并回收任务。模型输入协议不变，在适配边界投影为文本。离线通过，变异 17 个全部被抓到（第六批）。 |
| O-23 | router（轮次判断）：分段 STT 下语义 addressing 实际不参与提交判定。VAD 关闭、轮次判断模型评估后就开始等 addressing（0.5 s），这时还没有转写，超时后按 `addressing_timeout` 提交；语义推理在终稿到达后才开始，随即因 Turn 结束被取消，第六批的真实轮次里没有一次赶在提交前（Doctor 日志第六批）。 | 轮次判断重构（`d5491418`）后，需要文字的 addressing 先等本输入的转写（`awaiting_transcript_for_addressing`），转写到达后才开始 `addressing_wait_sec` 的计时；轮次判断与 addressing 都不确定时共用一次 `input.hold`，等到两者中较晚的期限。`input.addressing_wait` 和 `addressing_timeout` 已删除。离线回归 `test_smart_turn_hears_each_sound_once_however_often_its_input_is_reassessed` 覆盖先等文字、再等 addressing、addressing 到达后提交。真实服务未重测，终稿到提交因此增加的时长还没有测量。 |

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
| KD-36 | Doctor：`association_wait` 只取最后一次关联检查，漏掉重新判定前的等待；"none needed" 只看最后一段是否就绪。 | 第五批改为汇总全部检查。轮次判断重构后 router 不再等关联，Engine 在准入时直接解析 actor，这项指标随之删除，不改名保留；`association_ready` 在关联晚于该 Turn 的准入时注明该段未归属（第六批）。 |

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
| O-22 | 测试：`test_check_reports_valid_and_invalid_configurations_with_effective_overrides` 断言 `COLUMNS=200` 下每行完整，临时目录路径超过约 200 字符时 workspace 一行折行，用例失败。 | 该用例改用 `COLUMNS=10000`，比任何路径都宽；折行仍由渲染器自己的用例覆盖。约 330 字符的临时路径与默认路径下都通过（第六批）。 |
| O-13 | 测试基础设施：pytest-asyncio 新建的事件循环无人关闭，全量运行结束时报 `unclosed event loop`，pytest 以 1 退出。 | 根 `conftest.py` 在 `pytest_configure` 里清掉当前事件循环，不再新建。 |

## 观察与延期

| 编号 | 项目 |
| --- | --- |
| KD-10 | 跨身份访问旧 Memory 记录属于延期的多人历史策略，历史所有者继续保留。 |
| O-2、O-4、O-6、O-9 | 分别跟踪插件导入副作用、感知任务取消、LanceDB 弃用警告和 Host 校验错误的展示边界。 |
| O-12 | 默认 LanceDB Runner 启动时会探测 embedding 维度，Doctor 需获得相应的外部调用授权。 |
| O-14 | Context 的 `<committed_text>` 回退只在本轮既无转录也无打字时生效。如果感知缺口丢了转录事件却保留了打字事件，语音会静默缺失。尚未复现。 |
| O-18 | 静音或低噪声单独送给 STT 时，所有语言设置都会编出文字，加了提示时输出 `context:` 之类；加通用提示的 60 次里有 6 次原样回显提示全文。该矩阵绕过了 VAD。第六批经正常链路（真实 Silero VAD）各跑一轮静音和噪声样本：都没有形成语音段，STT 没有被调用。其他噪声与 VAD 误触发的组合未覆盖；默认不加提示。 |
| O-19 | Context 的历史按构建时原样保存用户消息，缺失转录提示在之后的请求里仍是 `current="true"` 并带指令，只靠系统提示中「只执行最新用户消息里的指令」来区分。第六批用真实模型（`gpt-5.6-luna`）经正常装配链路各跑 3 次：提示后接问题、部分转录后接问题、连续两次提示后接问题，9 次正常输入都直接作答，没有一次再要求重说；提示轮按当轮提示请求重说或追问缺失部分。现有协议在该模型上成立，不改写历史；换模型时需复验。 |
| O-16 | 第五批的后续轮终稿到提交多出 66～169 ms：轮次判断模型在终稿后对同一段音频再跑 1～2 次，加上等语义 addressing 证据。轮次判断重构后（Smart Turn 复用同一段 PCM 的结果，离线验证转写与 addressing 更新不再重跑、新音频才重跑），第六批两轮真实对照共 80 轮终稿到提交中位数约 2 ms（1.7～3.3 ms），终稿后的轮次判断与等待都是 0。但这是因为 addressing 等待在终稿之前就已超时，语义证据并未参与判定，见 O-23。第 1 轮另有的 addressing 等待已定位：首个语义请求要从 Avatar 身份开始评估（runner 只缓存了常量前缀），比之后慢 40～60 ms（真实首个任务 131～191 ms，之后中位数 76～89 ms），排队 0.05～0.3 ms；在 runner 里预热默认请求无效（已撤回），按会话身份预热可省约 30～50 ms。O-23 已改为转写到达后才开始等 addressing，预热要不要做，待真实服务复测终稿到提交后再定（Doctor 日志第六批）。 |
| O-24 | persona（说话人）：正常运行时，碎片轨迹和陌生人都以生成的 user_id 存进用户库，之后每次身份检索都把它们当作候选；误绑到碎片或陌生人的用户，再经会话结束的保存写回库里。第四批默认值下的回放中，正常运行绑到他人的段有 46%～75% 绑到了这类生成用户（校准 45/60，独立测试 1 13/28）。延期到 0.6.9 之后的版本：生成用户和碎片在确认之前不进入身份检索（Speaker Vector 日志第三、四批）。 |
