# AlphaAvatar MCP 插件

MCP 通过 AlphaAvatar 的原生能力系统，在已配置的远程服务器上提供发现和调用。传输层和 ClientSession 的所有权直接使用 MCP Python 客户端；不涉及 LiveKit AgentSession 或 Agents SDK 的 MCP 基类。

## 架构

```text
AvatarEngine -> Loop -> CapabilityRegistry -> MCPHost
    -> shared inference client -> isolated MCP runner
    -> native MCP clients -> configured remote servers
```

前台 facade 从不阻塞在数据库调用或线程 future 上。现有的串行推理 runner 负责同步的 embedding 和 LanceDB 工作；它单独拥有的事件循环执行异步的 MCP 网络操作。这并不会让单个 runner 进程并行处理相互独立的推理请求。在一个已接纳的工具批次内，远程调用可以并发运行。

本插件呈现一个聚合能力，而不是把每个远程 schema 作为单独的前台工具暴露。发现阶段的标注不授予权限。

## 配置

在完整的 Avatar 配置中，MCP 配置在 `tools.mcp` 下：

```yaml
tools:
  mcp:
    plugin: default
    enabled: true
    init_config: {}

    vdb_config:
      collection_name: mcp
      embedding:
        provider: openai
        model: text-embedding-3-small

    servers:
      livekit-docs:
        url: https://docs.livekit.io/mcp/
        transport: streamable_http
        client_session_timeout_seconds: 60.0
        close_timeout: 10.0
        max_in_flight: 32
        max_tools: 4096
        max_pages: 64
        instruction: >
          Search the configured LiveKit documentation server.
```

服务器设置经过严格校验。`streamable_http` 是默认值；SSE 服务器需显式选择 `transport: sse`。没有自动的传输回退、重连后重放，也没有隐藏的 SDK 兼容路径。远程服务器要求 HTTPS；本地开发支持本机回环 HTTP。URL 中嵌入的凭据和片段（fragment）会被拒绝。服务器和返回的工具内容仍是因部署而异的外部服务。

凭据可以使用现有的环境变量占位符机制，例如：

```yaml
headers:
  Authorization: "Bearer <GITHUB_PAT>"
```

通过环境提供 `GITHUB_PAT`，绝不要以提交到仓库的 token 提供。`Bearer ${oc.env:GITHUB_PAT}` 也会读取它。`<NAME>` 占位符出现在服务器设置的任何位置都是凭据，`${oc.env:NAME}` 只有在 `Authorization` 头中才是凭据：其值为空或只含空白时，取 `.env` 文件中的值或已存储的值，日志会隐藏它（[凭据](../../../docs/cli/config.md#credentials)）。在其他任何位置，例如 `X-Region: ${oc.env:REGION}`，`${oc.env:NAME}` 按环境中的原样读取一个普通变量，空值也一样，日志会显示它。上面的配置只是片段；参见[完整示例](../../../examples/README.md)。修改已配置的服务器、传输设置或凭据后，需重启 Host。

## 发现与刷新

`op="tool_search"` 接受一个查询、`top_k`（1–50，默认 8）、可选的精确 `server_keys`，以及类别 `read`、`write` 或 `unknown`。类别依据服务器的 `readOnlyHint`；它们不授权调用。

工具列举按配置的页数／工具数上限处理分页。名称重复、游标重复和结果过多会使列举失败，而不是把部分目录当作完整目录发布。工具标识仍为 `<server_key>.<tool_name>`。

`op="refresh_tools"` 显式刷新选定的目录，并报告新增、移除和更新的标识。列举失败时保留之前的目录，但旧条目不能证明已断开的服务仍可调用。只有在前一个客户端被干净地释放之后，之后的显式刷新才能打开新客户端。调用本身从不重连，也不重试工具调用。

LanceDB 的替换条目在 upsert 之前先完成 embedding。embedding 失败不能删除已有条目。只对完整目录列举成功的服务器修剪过期行，不对暂时不可用的服务器修剪。该索引是发现数据，不是执行日志或授权数据库。

## 调用、结果与取消

`op="tool_call"` 接受 1 到 64 个具名操作。每个服务器的 `max_in_flight` 限制已接纳的请求；超出的请求不派发，直接失败。每个已派发的请求拥有自己的超时和清理。超时或调用方取消不能证明远程写入没有提交。

`output_mode: raw` 保留完整的结果内容和回显的参数。`compact` 省略回显的参数，并把单个结果文本截断到 2000 个字符，附带说明。结构化的 MCP 结果内容保存在结果文本中，因此 compact 也会截断它。成功的空结果表示为空列表，不会被误判为工具失败。服务器报告的错误仍是错误。不会仅因同一批次中另一个操作失败，就丢弃其他操作的成功结果。

每个原生 MCP 传输和 ClientSession 只由一个任务进入和退出。关闭时拒绝新工作，允许已接纳的工作在宽限期内完成，然后取消剩余的本地请求并等待其清理完成，再释放连接。隔离的 runner 关闭其客户端，并等待其事件循环线程结束。关闭失败仍是失败；它并不意味着远程已成功回滚。

## 授权与隐私

远程标注不会批准调用；启用本插件即向每个 Run 授予其能力。使用 `tool_policies: {}` 时，每个 MCP 调用（包括写操作）都无需第二次批准即可运行。精确的策略可以用 `enabled: false` 拒绝该能力，或要求 `approval_required: true`；原生 Host 不提供授权器，因此此时该能力不会提供给模型。不要因为某个已配置的工具是只读的，就把整个 MCP 能力标记为只读。

工具实现返回结果；它们既不接收 StatusEmitter，也不接收 `monologue`。Loop 负责规范的工具记录。Memory 和 Status 各自独立消费各自的流。服务器返回的内容是数据，不是修改应用策略的许可。

连接错误暴露安全的阶段／类型信息，而不是原始请求头、凭据或响应体。现有的日志脱敏仍是纵深防御，不是记录任意机密的许可，也不能证明第三方日志是安全的。

## 安装与启动

一起安装工作区的 Host、MCP、embedding 和数据库依赖，然后使用完整配置：

```bash
ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/voice/pipeline_openai_tools_minimal.yaml
```

使用 Host 的 `dev` / `start` 命令，而不是 `alphaavatar serve`。仍需要模型和远程服务的凭据。原生传输／生命周期的实现不能替代针对你所配置 MCP 服务器的集成检查。
