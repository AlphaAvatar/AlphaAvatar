# `alphaavatar dev`

为开发运行 AlphaAvatar Host。

```bash
ENV_FILE=.env.dev alphaavatar dev [<bundle> | <file>] [KEY=VALUE ...]
```

与 [`alphaavatar start`](start.md) 相同，但有以下区别：

- DEBUG 级别日志。
- 健康检查服务器使用任意空闲端口。

它不监视文件，也不重新加载代码。
