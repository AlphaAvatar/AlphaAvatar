# AlphaAvatar Host

`alpha-avatar-host` owns application startup, shared inference and hosted execution.
`sessions/` owns interaction attachments; `sessions/livekit/` implements the LiveKit backend.
Core, Agents and RTC do not depend on Host.

## 📦 Package structure

```
avatar-host/alphaavatar/host/
├── main.py                         # 唯一公开命令入口
├── version.py
│
├── cli/
│   ├── app.py                      # 命令路由、帮助、退出码
│   └── commands/
│       └── run.py                  # v0.6.8 的最小 dev/start 命令
│
├── configs/
│   ├── application.py              # HostConfig 与 AvatarConfig 的组合
│   └── loader.py                   # 配置文件读取、分流和整体校验
│
├── application/
│   ├── application.py              # AvatarHost：应用级协调
│   ├── bootstrap.py                # 组件构造与所有权移交
│   ├── config.py                   # 应用级运行设置
│   ├── health.py                   # 存活、就绪与依赖健康状态
│   └── signals.py                  # 进程信号到应用关闭请求的转换
│
├── execution/
│   ├── execution.py                # HostExecution：一个托管执行实例
│   ├── manager.py                  # 执行实例的接纳、查找与释放
│   ├── policy.py                   # 执行保留、结束与接入变化策略
│   └── schemas/                    # 执行管理所需的数据契约
│
├── processes/
│   ├── supervisor.py               # 托管执行进程的启动、监控与回收
│   ├── process.py                  # 单个子进程的资源所有权
│   ├── config.py                   # 容量、启动和关闭限制
│   └── schemas/                    # 进程启动参数、状态与结果
│
└── sessions/
    ├── base.py                     # 接入后端的中立契约
    ├── factory.py                  # 按配置选择后端，集中进行惰性加载
    ├── manager.py                  # 接入登记、绑定与解绑
    ├── attachment.py               # 一次接入及其适配器资源
    ├── mode.py                     # 文字、语音、视频等交互模式
    ├── config.py                   # RTC 后端选择和通用接入配置
    ├── schemas/                    # 接入请求、身份关联和结束原因
    │
    └── livekit/
        ├── backend.py              # LiveKit 接入实现与适配器组装
        ├── config.py               # LiveKit 专属配置
        ├── dispatch.py             # 原生注册、派工与状态上报
        ├── connection.py           # RTC 房间连接及连接事件
        └── character.py            # Character 凭证与就绪检查
```

## Run

The public entrypoint is `alphaavatar.host.main:main`:

```bash
alphaavatar --help

alphaavatar --version

ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/mm/pipeline_openai_tools.yaml

alphaavatar start examples/agent_configs/mm/pipeline_openai_tools.yaml
```

`dev` enables debug logging and an ephemeral health port by default; it does not watch
files or restart executions. `start` uses INFO logging and health port 8081 by default.
Help and version do not initialize models, inference or RTC. Configuration overrides
remain `key=value` arguments after the filename. App, installer, TUI and Doctor are
not required to use this command.

## Ownership

`application/` coordinates services. `execution/` owns admission and Engine/Runtime
lifetimes; a parent process holds execution handles, not the child's Engine objects.
`processes/` owns real execution subprocesses and their authenticated local IPC.
InferenceRuntime remains the sole owner of its own serial runner processes.

Session startup orders Character readiness, outputs, Engine and inputs. A
SessionAttachment releases its adapters, subscriptions and connection; it does not
close HostExecution. The explicit `finish_execution` Host policy then settles Engine
and Runtime. Shared inference is released after execution processes are reaped.
Core LifecycleGroup and managed cleanup remain the underlying lifecycle mechanisms.

The current policy supports one attachment per execution. Detachment does not imply
room deletion. Execution persistence, reattachment, Episode recovery, sleep/wake and
Dream scheduling are not implemented here. Force-killed or unconfirmed processes are
reported with an unknown outcome, never automatically retried.

## LiveKit

The `livekit` extra selects RTC/API/protocol libraries, not the Agents SDK. Native
control dispatch handles registration, capacity reservation, assignment, termination,
status and reconnection. Reconnection republishes execution status, not tool calls.
Direct room access is an explicitly configured alternative, not a dispatch substitute.

For credentials, configuration, health endpoints and limitations, see
[Host operation](../docs/worker-hosting.md). Optional Character presentation uses the
existing [Character setup](../avatar-plugins/perception/avatar-plugins-character/README.md).
A real RTC/renderer integration check is still required before deployment.
