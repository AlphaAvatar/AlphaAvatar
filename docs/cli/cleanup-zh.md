# `alphaavatar cleanup`

删除升级和 setup 在 Linux x86_64 安装中留下的内容：先删除 `current` 不运行的环境，再删除不再作为任何保留环境基础的基础包。
与 [`alphaavatar upgrade`](upgrade.md) 一样属于 Linux 包；upgrade 会保留原版本和原环境，留给 cleanup 处理。

```bash
alphaavatar cleanup --dry-run    # what would go, the space it takes, and what stays and why
alphaavatar cleanup              # remove it
```

| 选项 | 含义 |
| --- | --- |
| `--dry-run` | 列出将要删除的内容及其大小，以及保留的内容和原因；不写入任何内容 |

**先停止 Host。** cleanup 会获取 `<prefix>/.install.lock`，即 `install.sh`、`alphaavatar setup` 和 `alphaavatar upgrade` 获取的同一把锁，因此它不会与安装同时运行；但这把锁只约束安装，不约束正在运行的 Host。
升级前启动的 Host 仍从原环境和原基础包运行，而 cleanup 正会删除它们：删除前停止此安装的所有 `alphaavatar start`、`dev` 和 `doctor`，之后再重新启动。
`--dry-run` 可以随时运行。

## 删除与保留的内容

只有 prefix 下的 `envs/` 和 `versions/` 会变化，且只涉及安装程序创建的目录：

| 删除 | 条件 |
| --- | --- |
| `envs/<plan>/` | Setup 创建的环境（有其标记，以及以其命名的规划的 `plan.json`），且 `current` 不运行它 |
| `versions/<build>/` | 由 `install.sh` 或 `upgrade` 解包的基础包（由其清单给出名称），且没有任何保留环境基于它 |
| `envs/.setup-*/`、`versions/.install-*/` | 被中止的运行遗留的暂存目录，带有安装程序的标记 |

先删除环境，再删除基础包。
保留的内容会连同原因一起列出：

- `current`：它指向的环境及该环境所基于的基础包，或者它直接指向的基础包；
- 保留的环境所基于的每个基础包；
- 运行本命令的构建和环境；
- cleanup 无法确认由安装程序创建的内容：符号链接、文件、没有 setup 标记的目录、缺失、不可读、所指基础包在 `versions/` 之外或所指规划不是该环境名称的 `plan.json`，以及没有任何清单为其命名的 `versions/` 目录。不属于其环境的 `plan.json` 无论指向哪个基础包，都不能据此确定基础包。只要某个保留环境的基础包无法确定，就不删除任何基础包；
- 包含应用主目录或其缓存的目录，或位于应用主目录或其缓存之中的目录，包括被中止的运行遗留的暂存目录。主目录指 `start` 会使用的那个：环境变量中的 `ALPHAAVATAR_HOME`；环境变量中未设置或为空时，取 `ENV_FILE` 指定的 `.env` 文件中的值；否则为默认值。

应用主目录（bundle 和 profile、设置、已存储的凭据、Avatar 工作区和模型缓存）位于 `envs/` 和 `versions/` 之外，从不改变；`current`、`alphaavatar` 命令和锁也不会改变。

删除时会在持有锁的情况下重新勘查：`current` 指向什么、每个环境基于哪个基础包，都按当时的状态读取，不论此前 `--dry-run` 显示的是什么。
每个目录先移入带标记的暂存目录，再删除；中断的 cleanup 不会在原位置留下环境的任何部分，只会留下一个由下一次 cleanup 或安装删除的暂存目录。

```text
AlphaAvatar / Cleanup

01  Survey         2 to remove · 2,034 MB · 2 kept

  Prefix       ~/.local/lib/alphaavatar
  Current      envs/e003187213a2f154 · AlphaAvatar 0.6.9-f3ffa11c18dd

Would remove
  envs/7c360b3f811392e7         1,816 MB · environment over AlphaAvatar 0.6.9-62c87e3d33de
  versions/0.6.9-62c87e3d33de     219 MB · AlphaAvatar 0.6.9-62c87e3d33de

Kept
  envs/e003187213a2f154         current
  versions/0.6.9-f3ffa11c18dd   kept environments are over it: envs/e003187213a2f154 (current)

OK    Would free 2,034 MB; nothing was removed

Next
  With every `alphaavatar start` of this installation stopped:
  alphaavatar cleanup
```

如果改由原构建的环境（`<prefix>/envs/<old>/bin/alphaavatar`）运行，同样的勘查会保留该环境（因为它在运行本命令），以及该环境的基础包（因为有保留的环境基于它）：

```text
Kept
  envs/7c360b3f811392e7         runs this command
  envs/e003187213a2f154         current
  versions/0.6.9-62c87e3d33de
    kept environments are over it: envs/7c360b3f811392e7 (runs this command)
  versions/0.6.9-f3ffa11c18dd   kept environments are over it: envs/e003187213a2f154 (current)

OK    Nothing to remove
```

## 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 已删除、没有可删除的内容，或已打印 `--dry-run` 的结果 |
| 1 | 被拒绝：另一个安装正在运行，`current` 缺失或不是安装程序创建的，某个目录无法删除，不是从 Linux 包运行；会说明在此之前已删除的内容 |
| 2 | 其他错误 |
| 130 | 被 Ctrl+C 中断；SIGTERM 为 143，SIGHUP 为 129：正在删除的内容留在带标记的暂存目录中 |
