# AlphaAvatar Provider 插件

[English](README.md)

公开的模型、prompt、工具结果、请求和流契约位于 `alphaavatar.agents.avatar.provider`。SDK 构造、消息转换、结构化解析和用量归一化仍保留在本插件中。

## 共享所有权

每个 FoundationRuntime 拥有一个 ProviderService，以 `runtime.foundation.provider` 暴露。它属于当前运行时，而不是进程全局的注册表，也不是另一个 ProviderRuntime。

Memory Conversation、Environment、Tool 和 Persona Profiler 从该服务借用网关（gateway）。网关保留不可变的任务快照、业务任务名称、追踪策略和 prompt。完整内容相同的模型配置可以在同一个服务内复用一个绑定；不同的服务／配置相互隔离。

Provider 既不存储对话历史，也不存储工具授权。资源池不是结果缓存。凭据在客户端初始化时读取；更改凭据需要新的运行时，而不是修改活动中的网关。池键不包含明文凭据。

## 后端选择

`backend` 选择一个已安装的实现；`provider` 选择其供应商／API 系列。工厂发现使用 AvatarModulePlugin，其本身不会发起模型请求。

| 后端 | 当前角色 |
| --- | --- |
| `openai` | 前台实时 Loop 使用的原生 Responses 流式输出。 |
| `langchain` | 插件自身的提取网关使用的结构化任务模型绑定。 |
| `langchain`（embedding） | 向量存储 runner 使用的 embedding 绑定 `alphaavatar.provider.embedding`。 |

流式契约是公开的，并不代表每个后端都支持流式。当前的 LangChain 任务后端不声明 StreamingLLMBase。Loop 初始化会检查所选的模型绑定；原生主模型需要显式使用 `backend: openai`。

```yaml
loop:
  plugin: realtime
  init_config:
    model:
      backend: openai
      provider: openai
      model: YOUR_MODEL_ID
      temperature: null
```

Memory 和 Persona 保留各自处理器级别的 provider 设置。它们的结构化任务不必仅为共享客户端所有权而改用前台后端。

## 构造与调用

LangChain LLM 的构造是惰性的、单飞（single-flight）的，并在事件循环之外进行。取消第一个等待者不会遗弃初始化。后续调用复用已初始化的客户端和绑定了 schema 的结构化 runnable；远程请求期间不持有锁。

模型调用使用异步 SDK 路径。配置的结构化调用超时包含重试，而消费者期限约束整个工作流。不支持的媒体和无效的结构化输出仍作为显式错误。初始化失败后，该绑定保持失败状态；不存在隐式的凭据刷新。

## 客户端资源

OpenAI/OpenRouter 的 LangChain 绑定接收由其自身拥有的同步和异步 HTTP 传输。Anthropic 适配器避免使用进程级缓存的 HTTP 传输，Google 包装器的异步／同步客户端会被显式关闭。阻塞的构造和同步关闭操作在 worker 线程中运行，而不是在实时事件循环上。

LangChain 资源适配器遵循仓库约束的集成版本。升级依赖时，重新核对 Anthropic 缓存客户端和 Google 所有权的细节。共享任务绑定不支持任务 `extra` 中的外部客户端句柄，也不支持有状态的 Anthropic 容器复用。

## 关闭

在 Foundation 释放 Provider 之前，消费者先完成各自的收尾。关闭时拒绝新调用，完成残留的自有请求和初始化的收尾，关闭绑定，并排空追踪器。普通的同级关闭失败不会跳过其余清理。

并发调用方共享同一个关闭任务；取消在自有清理完成后才会传播。LLMBase.aclose 是契约的一部分，所有者必须先停止生产者，再关闭其模型资源。

## 追踪

每个追踪策略都有一个由服务拥有的有界写入队列（`max_pending`，默认 256）。不存在同步回退，也没有未被跟踪的逐次写入任务。文件操作在事件循环之外进行。当取消到达追踪阶段时，会产生一条终态追踪记录。

追踪是尽力而为的诊断，不是无损的审计日志。队列饱和时递增丢弃写入计数器，失败会被记录／报告，关闭时等待已接受的写入完成。缺少 `provider_dir` 目标时会跳过，而不会创建写入器。

## 当前边界

原生 Engine/Loop 生成、类型化的 Output 发布以及 Router/RTC 交付均已实现。过时的 SDK 模型／工具／记录桥接已移除。Voice 拥有原生的 OpenAI 与 Voice.ai HTTP/PCM 合成；它不借用 ProviderService 的 LLM 绑定。Character 使用原生的浏览器／传输生命周期，不借用 ProviderService。真实的渲染器／RTC 验证仍是单独的要求。

VDB worker 进程仍拥有各自的 Embedding 实例；不会跨进程边界传递 SDK 客户端。执行仍限定在 Host 范围内，没有新增持久恢复或 Dream 调度。
