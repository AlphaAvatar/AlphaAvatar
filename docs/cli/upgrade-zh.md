# `alphaavatar upgrade`

[English](upgrade.md)

将 Linux x86_64 安装升级到另一个构建：升级其基础包；当 `current` 运行的环境由 [`alphaavatar setup`](setup.md) 创建时，还升级默认 bundle 的环境。
两者都先在当前基础包和环境旁边准备并检查，然后一次性切换。
该命令属于 Linux 包；在源码检出中，用 `git pull` 和 `uv sync --all-packages --locked` 更新。

```bash
alphaavatar upgrade --check                 # the current build, the latest release's, and whether it upgrades
alphaavatar upgrade                         # to the latest release
alphaavatar upgrade --version 0.6.9         # to that release
alphaavatar upgrade --file ./alphaavatar-0.6.9-<commit>-linux-x86_64.tar.gz   # a CI build
```

| 选项 | 含义 |
| --- | --- |
| `--check` | 显示当前构建、目标构建以及是否属于升级；不做任何更改，对发布版本只下载其清单 |
| `--version X.Y.Z` | 使用该发布版本，而不是最新版本 |
| `--file PACKAGE` | 已下载的包，例如某个提交的 CI 构建；其 SHA-256 取自 `--sha256` 或其旁边的 `PACKAGE.sha256` |
| `--sha256 HEX` | 包的 SHA-256，代替其旁边的 `.sha256` 文件 |
| `--artifacts DIR\|URL` | 目标构建自身 wheel 所在的位置；CI 构建默认在 `--file` 旁边，发布版本默认在该发布中 |

升级前停止 `alphaavatar start`，升级后再重新启动。

## 构建

构建以其 ID `<version>-<commit>` 区分（由带改动的检出构建时还会加上 `-dirty.<time>`），以其包清单中的记录为准。
同一版本的两份构建，例如 0.6.9 的两份 CI 构建，是两个不同的构建，任一个都可以升级到另一个：

```text
AlphaAvatar / Upgrade

OK    Upgradable to AlphaAvatar 0.6.9-3ade593c77ca
      Current      0.6.9-0600b13e01d0
      Target       0.6.9-3ade593c77ca
      From         /srv/ci/alphaavatar-0.6.9-3ade593c77ca-linux-x86_64.tar.gz

Next
  alphaavatar upgrade --file /srv/ci/alphaavatar-0.6.9-3ade593c77ca-linux-x86_64.tar.gz
```

若目标就是 `current` 正在运行的构建，则它已是当前构建：`--check` 会如此说明，`upgrade` 立即结束，不做任何更改。
包文件在原位置识别，依据其 SHA-256 和包内的清单，因此无需复制，也无需暂存。
较旧的版本不算升级：`--check` 会如此说明，`upgrade` 会拒绝。

发布版本在其包旁边发布 `alphaavatar-linux-x86_64.manifest.json`，因此下载包之前即可知道其构建：`--check` 只读取该文件，升级到已是当前构建的目标时也是如此。
发布版本的包是 `alphaavatar-<version>-linux-x86_64.tar.gz` 及其 `.sha256`，与 `install.sh --version` 获取的相同；其自身的 wheel 也在该发布的文件中。

要复现两份 CI 构建之间的升级，将每份构建的文件（Linux 包工作流的 `alphaavatar-linux-x86_64-<commit>` artifact）分别下载到各自的目录，用 `install.sh --file` 安装第一份并完成 setup，再用 `--file` 升级到第二份：其 wheel 取自它的旁边。

## 执行过程

```text
AlphaAvatar / Upgrade

01  Package        AlphaAvatar 0.6.9-3ade593c77ca · SHA-256 checked
02  Plan           Bundle my-avatar · 105 packages · 514 MB
03  Install        105 packages · 514 MB
04  Validate       PASS · 8 runners

OK    Upgraded to AlphaAvatar 0.6.9-3ade593c77ca
      Previous     0.6.9-0600b13e01d0
      Current      ~/.local/lib/alphaavatar/envs/73bcf97c85db5e92
      Bundle       my-avatar
      The previous version and its environment stay until `alphaavatar cleanup` removes them.

Next
  alphaavatar doctor my-avatar
```

1. **Package**：与 `install.sh` 相同，包须与其 SHA-256 一致：给定的文件先在原位置校验，再校验本次运行自己的副本；或者校验下载的包；解包的正是该副本或下载的包。它被解包到 `<prefix>/versions/<build>/`，并按 `install.sh` 的方式检查：其命令报告自身版本，帮助能够运行，基础包的原生库能够加载。`current` 不受影响。
2. **Plan**：目标构建用它自己的 `alphaavatar setup <bundle> --plan` 为默认 bundle 规划环境，因此由它的配置解析器读取 bundle 的设置，由它的包目录给出所需的包。规划还会保留当前环境已有的内容，因此之前 setup 过的 bundle 仍可使用。当 `current` 运行的是没有 setup 环境的基础包时，只切换到目标构建的基础包。
3. **Install**：将规划中的每个包安装到当前环境旁边的 `<prefix>/envs/<plan>/`，每个包须与目标构建的包目录记录的大小和 SHA-256 一致。
4. **Validate**：新环境的命令报告目标版本，其原生库能够加载，其 `config check` 接受默认 bundle。所用凭据来自环境变量、`.env` 和已存储的凭据，与 `start` 的取法相同，每项取第一个有值的来源：环境变量中为空或只有空白的值让位于文件中的值，再让位于已存储的值。

只有到这时，`<prefix>/current` 才切换，且只切换一次，随后经由它运行命令；如果命令报告的不是目标版本，`current` 会切回原处。
升级会获取 `<prefix>/.install.lock`，即 `install.sh`、`setup` 和 `cleanup` 获取的同一把锁：一次安装运行期间，向该 prefix 的其他安装会被拒绝。
默认 bundle 以及目标构建的命令读取的已存储凭据，在持有锁之后才读取，规划和检查使用同一份：刚刚结束的 `setup` 留下的状态，就是规划和检查所依据的状态。
这些命令从 `/` 运行：它们读取的 `.env` 就是 `upgrade` 启动时读取的内容，不会再次读取该文件，即使 `ENV_FILE` 是相对路径也是如此。

切换前发生失败或收到信号时，`current`、命令以及原版本和原环境保持原样，本次运行创建的内容会被删除：它创建的每个目录都在信号暂缓处理期间移入目标位置，并记录为本次运行所有，因此无论信号何时到达，都不会遗留目录。
它删除的基础包或环境先整体移入带标记的暂存目录；每个暂存目录，无论是它自己的还是被中止的运行遗留的，最后才去掉标记：即使在那时被中止，运行也只会留下带标记的暂存目录，由下一次 `install.sh`、`setup`、`upgrade` 或 `cleanup` 删除。
失败原因输出到 stderr：

```text
FAIL  Upgrade failed; AlphaAvatar 0.6.9-0600b13e01d0 stays current
      The new environment fails check my-avatar:
        error: RuntimeError
          at alphaavatar.agents.runtime.plugin.resolution:189 in plan
        caused by: ValidationError
          fields: acceptance_marker
          at pydantic.main:705 in model_validate
      Fix what it names, then run `alphaavatar upgrade` again
```

目标构建不接受的 bundle 会在规划或检查时失败；修正 bundle（或它读取的凭据）后再次升级。
包与其 SHA-256 不一致、wheel 无法获取或不一致、机器缺少目标构建所需的 glibc 或 CPU、可用空间不足，都会以同样的方式失败。

不会写入应用主目录中的任何内容：默认 bundle 及其 profile、Avatar ID、设置、已存储的凭据、工作区和模型缓存都保持原样。
原版本及其环境保留在 prefix 中，直到在 Host 停止后由 [`alphaavatar cleanup`](cleanup.md) 删除；没有回退到它们的命令。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 已升级、目标已是当前构建，或已打印 `--check` 的结果 |
| 1 | 未做任何更改：下载、SHA-256、包、规划、安装或检查失败；版本较旧；另一个安装正在运行；不是从 Linux 包运行 |
| 2 | 未做任何更改：其他错误 |
| 130 | 被 Ctrl+C 中断；SIGTERM 为 143，SIGHUP 为 129 |
