# `alphaavatar start`

[English](start.md)

将 AlphaAvatar Host 作为长期运行的服务运行。

```bash
alphaavatar start [<bundle> | <file>] [KEY=VALUE ...]
```

- 按名称加载 bundle，或加载 YAML／JSON 文件，省略时加载默认 bundle；见[选择配置](config.md#choosing-a-configuration)。
- 每个变量依次从环境、`.env`（`ENV_FILE`）、[`alphaavatar setup`](setup.md) 存储的凭据中读取；见[凭据](config.md#credentials)。
- INFO 级别日志；健康检查服务器位于 `127.0.0.1:8081`。
- 首次运行时创建应用主目录和 Avatar 工作区。
- Ctrl+C 或 SIGTERM 会在其拥有的所有资源释放后停止它。
- 启动前校验配置；[`alphaavatar config check`](config.md#config-check) 执行相同的校验，但不启动。

| 退出码 | 含义 |
| --- | --- |
| 0 | 正常停止 |
| 1 | 运行中失败 |
| 2 | 配置或启动错误 |
| 130 | 被中断 |

开发时请使用 [`alphaavatar dev`](dev.md)。
