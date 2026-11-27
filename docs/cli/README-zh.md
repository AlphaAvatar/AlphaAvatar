# `alphaavatar` 命令

`alphaavatar` 用于运行和配置 AlphaAvatar Host。在 Linux x86_64 上，`install.sh` 会连同它自带的 Python 一起安装它；见 [DEPLOY.md](../DEPLOY.md#or-install-the-linux-package-then-choose-capabilities)。在源码检出中，它是 `alpha-avatar-host` 包提供的命令。

| 命令 | 作用 |
| --- | --- |
| [`alphaavatar setup`](setup.md) | 安装 bundle 所需的内容、检查它，然后启用它：可以是现有 bundle，也可以是根据参考配置逐项询问得到的新 bundle；属于 Linux 包 |
| [`alphaavatar upgrade`](upgrade.md) | 将安装升级到另一个构建，默认为最新 release：在当前构建旁准备并检查，然后一次性切换过去；属于 Linux 包 |
| [`alphaavatar cleanup`](cleanup.md) | 在 Host 停止时，删除升级留下的、`current` 未使用的环境和构建；`--dry-run` 列出它们；属于 Linux 包 |
| [`alphaavatar config init`](config.md#config-init) | 创建参考 bundle 及其 profile |
| [`alphaavatar config check`](config.md#config-check) | 校验配置，不启动任何东西 |
| [`alphaavatar doctor`](doctor.md) | 诊断安装和配置：先进行静态检查，再进行运行时诊断，其语音场景分轮进行 |
| [`alphaavatar start`](start.md) | 将 Host 作为长期运行的服务运行 |
| [`alphaavatar dev`](dev.md) | 为开发运行 Host |
| [`alphaavatar test`](test.md) | 计划中，尚不可用；是否提供尚未决定：场景与基准测试 |

`config check`、`doctor`、`start` 和 `dev` 以相同方式选择配置和读取凭据：见[选择配置](config.md#choosing-a-configuration)和[凭据](config.md#credentials)。`alphaavatar <command> --help` 列出选项，`alphaavatar --version` 输出版本。

## 输出

`config init`、`config check`、`setup`、`upgrade`、`cleanup` 和 `doctor` 以相同方式输出文本报告。[cli.html](cli.html) 是一个可离线打开的页面，按终端中的样子（包括颜色）展示除 `upgrade` 和 `cleanup` 以外各命令的报告。该页面是录制的示例输出，不是当前源码的运行结果，也不能作为行为或性能的证据。报告开头如下：

```text
AlphaAvatar / Doctor
OK    9 passed · 6 skipped

Checks
  PASS  Environment            3 checks passed
  PASS  Configuration          my-avatar · 8 runners
```

| 部分 | 样式 |
| --- | --- |
| `AlphaAvatar / …` 标题 | 品牌蓝，`#60a5fa` |
| setup 的当前步骤、该步骤的问题，以及供复制的命令 | 信号青，`#22d3ee` |
| 行分组：config check 的 `Configuration`、`host`、`agent`、`plugins/…`；setup 的安装摘要 | 粗体信号青 |
| 其他标题：`Scenarios`、`Next`、… | 粗体，终端自身的颜色 |
| 值得注意但并非故障的状态：未开启的工具（`none`、`None enabled (default)`） | 黄色，并用文字写明状态 |
| `OK`、`PASS` | 绿色 |
| `WARN` | 黄色 |
| `FAIL`、`ERROR` | 红色 |
| `SKIP` | 灰色 |
| 其余一切：标签、值、路径、数字 | 终端自身的颜色 |

- 各值共用一列。在较窄的终端上，一行放不下的值在空格处换行，续行与该值的起始位置对齐；如果标签旁空间太小，或某个词（例如路径或模型 ID）在那里放不下，该值就移到标签下方。路径、模型 ID 和供复制的命令保持完整。诊断信息和命令也完整输出，便于搜索和复制。出错的设置一行放不下时（例如缺少的包，或没有值的变量），改为拆开显示：设置、问题、包以及安装它的方式，各占一行。
- 宽度取 `COLUMNS`，否则取终端宽度；输出到管道或文件时为 100。
- 颜色以及原地重绘的行（setup 正在进行的步骤、Doctor 正在运行的测试）只在终端中出现：管道、`NO_COLOR` 和 `TERM=dumb` 得到相同的行，但不带样式，每条进度各占一行，不擦除任何内容。无法编码 `·`、`→` 或 `—` 的输出流分别得到 `-`、`->` 和 `-`。
- `--json` 和 `setup --plan` 只在 stdout 输出 JSON；此时步骤和问题输出到 stderr。
