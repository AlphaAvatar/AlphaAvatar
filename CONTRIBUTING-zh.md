# 为 AlphaAvatar 做贡献

[English](CONTRIBUTING.md)

## Python 3.13 开发环境

开发目标是标准 CPython 3.13，而不是 free-threaded 解释器。
`.python-version`、所有包的 `requires-python` 声明、Ruff、mypy 和 CI 都使用这一目标。
根目录的 `pyproject.toml` 负责工作区策略和开发工具；每个发行包各自负责其运行时依赖、入口点和打包的资源。
共享的 `alphaavatar` 命名空间不得添加根级 `__init__.py`。

### 迁移现有的 Python 3.11 检出

停止 Host 并等待资源清理完成。
保留可用的环境和工作区备份；不要为了让新安装成功而删除它们。
在单独的 worktree 或检出中应用源码改动，然后使用新的虚拟环境：

```bash
uv python install 3.13
uv lock --python 3.13
git diff -- uv.lock
UV_PROJECT_ENVIRONMENT=.venv313 uv sync --all-packages --locked --python 3.13
uv pip check --python .venv313/bin/python
.venv313/bin/alphaavatar --help
.venv313/bin/alphaavatar --version
```

审查后，将解析器生成的锁文件与元数据一起提交。
绝不要只修改锁文件的 Python 头部、用 `--frozen` 接受过期的锁文件，或删除失败的功能来声称完整安装已通过。
起初保留现有的第三方版本固定；只更新已证实不兼容的依赖，然后重新进行解析、安装和相关功能检查。
`uv sync --all-packages` 是集成环境；仅用于 lint 的环境刻意与之不等价。

用新环境，针对你打算使用的服务运行所选配置。
在更新服务可执行文件之前，验证启动、一次真实的 dispatch 与交互、启动期间和工作进行中的取消，以及正常关闭。
仅凭元数据、导入和 wheel 检查，无法验证模型、音频、工具效果、RTC 或 AIRI 浏览器。
保留旧的检出／环境以便回滚；恢复代码不会撤销外部工具产生的效果，也不能替代工作区备份。

### 不加载模型的可重复检查

使用已提交的锁文件和 uv 0.10.0 或更新版本。
CI 使用 uv 0.10.0。
质量工具有自己的环境，因此检查代码不会卸载或替换运行时依赖：

```bash
UV_PROJECT_ENVIRONMENT=.venv-quality uv sync --locked --only-group lint --no-install-workspace
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync python scripts/quality/check_workspace.py
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff check .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff format --check .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync pre-commit validate-config
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync python scripts/docs/check_docs.py
uv lock --check
```

`scripts/docs/check_docs.py` 检查 [docs/manifest.yaml](docs/manifest.yaml)、其中所列文档的相对链接和锚点，以及[路线图](docs/ROADMAP.md)的结构及其两种语言版本。
新文档须列入清单，否则检查失败。

`scripts/quality/check_workspace.py` 在不导入运行时的情况下检查包元数据、依赖关系、入口点文件、许可证和锁文件策略。
其 `--metadata-only` 模式在编写期间有用，但会明确跳过源码／锁文件校验；它不是发布关卡。
解析器层面的时效性仍需要 `uv lock --check`。
这里的任何命令都不会悄悄把不可用的工具或空的测试集当作检查成功。

Ruff 在依赖组、`required-version` 和 pre-commit 中固定为 **0.12.9**。
保持 100 列格式和紧凑的导入；尾随逗号不会强制展开。
未启用 unsafe fix。
提交前检查安全修复和格式化的结果：

```bash
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff check --fix .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff format .
git diff --check
git diff
```

保留现有的 E501 和 B904 例外；不要添加整体的 F/I/B/UP 排除来掩盖迁移失败。
vendored 的 `third_party` 代码、生成的环境和工作区数据被排除在外，但 `.github` 没有被整体排除。
TID251 拒绝静态导入 `livekit.agents`；依赖／锁文件检查也会拒绝已移除的 Agents SDK。
这并不是对动态导入字符串或任意第三方代码的安全分析。

仓库的 `/tests/` 目录目前仅保存在本地。
存在时，用运行时环境运行维护中的本地测试；pytest 退出码 5 表示没有收集到测试，而不是回归测试通过。
质量工作流运行安装／导入／构建检查，但不会声称并不存在的已提交测试集已通过。

### 安装本地 commit 和 push hook

提交了 `.pre-commit-config.yaml` 并不会安装 Git hook。
在每个检出中运行：

```bash
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync pre-commit install \
  --hook-type pre-commit --hook-type pre-push
```

commit hook 修复／检查暂存的文件。
只读的 push hook 对整个工作区运行 Ruff lint 和格式检查，即使只改动了配置文件也是如此。
它们不构建发行包，也不调用模型服务。
CI 仍是权威：本地 hook 可以被绕过，也不会随提交带到另一台机器上。

修改 lint 策略或 Python 语法目标后，对完整基线统一对齐一次：

```bash
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff check --fix .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff format .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff check .
UV_PROJECT_ENVIRONMENT=.venv-quality uv run --no-sync ruff format --check .
git diff --check
git diff
```

显式审查 PEP 695 类型别名和泛型声明；不要在 hook 中添加 `--unsafe-fixes`。
未改动的文件不会被只检查暂存文件的 commit 检查注意到，却可能在全树 CI 检查中失败。
诊断 hook 安装问题时，检查 `git config --show-origin --get core.hooksPath` 以及实际生效的 hook 目录中的 hook 文件；没有配置 `core.hooksPath` 本身并不是错误。

### 构建所有发行包

构建工具与运行时环境和 lint 环境相互独立：

```bash
UV_PROJECT_ENVIRONMENT=.venv-build uv sync --locked --only-group build --no-install-workspace
(
  set -e
  constraints="$(mktemp)"
  trap 'rm -f "$constraints"' EXIT
  uv export --locked --only-group build --no-emit-workspace --no-hashes \
    --output-file "$constraints" > /dev/null
  uv build --all-packages --no-sources --build-constraints "$constraints"
  UV_PROJECT_ENVIRONMENT=.venv-build uv run --no-sync twine check dist/*
)
```

build 组中的 Twine 7 和 packaging 26.1 及以上版本的读取器支持 Core Metadata 2.5。
在已提交的锁文件中保持元数据写入器与读取器相互兼容。
隔离构建使用从该锁文件导出的约束；仅在 `.venv-build` 中安装固定版本的 Hatchling，并不能约束隔离的 PEP 517 构建。
wheel 构建成功不能代替 `twine check`。
不要为了让发布通过而编辑产物元数据或跳过校验。

每个发行包都包含根目录 Apache-2.0 `LICENSE` 的副本，以及自己的 README、`pyproject.toml`、命名空间源码和现有的包资源。
会检查许可证副本是否与原件偏离。
`--no-sources` 用于验证构建不依赖 uv 的可编辑工作区覆盖；它不能证明所有运行时依赖都可以安装。
审查发布产物时使用干净的输出目录。

### 网络与安装失败

区分 DNS 错误、TCP 连接失败、TLS 验证失败和解析器冲突。
连接 GitHub 失败并不表示仓库或依赖版本不存在。
使用该环境经批准的网络／代理配置。
不要禁用 TLS 验证，也不要把猜测的 IP 地址写入永久的 Git／DNS 设置。
没有出站连接的容器，无法通过修改包约束来修复。

离线工作时，使用事先填充好的 uv 缓存，或包含所需 Python 3.13 产物的受控包镜像。
不要用语法检查代替运行时安装的结果。
记录失败的命令和阶段，但不要公开代理凭据、访问令牌或环境文件。

## 插件开发

插件包按职责分组：

| 层 | 包位置 | 职责 |
| :--- | :--- | :--- |
| Foundation | `avatar-plugins/foundation/` | 供其他插件使用的共享服务组件。 |
| Perception | `avatar-plugins/perception/` | 用户理解、记忆、身份和交互。 |
| Tools | `avatar-plugins/tools/` | 研究、文档访问和外部操作。 |

添加或移动包之前，先阅读[插件布局与边界](avatar-plugins/README.md)。

公共命名空间保持在 `alphaavatar.plugins.<plugin>` 之下。
不要把层名称写入 Python 导入或 YAML 插件选择中。
处理器专属的配置、提示词、模型规格和业务逻辑由其所属处理器维护。

消费者管理自己的任务、流和请求状态；`FoundationRuntime` 管理共享服务组件。
插件注册不得初始化模型。
根据当前生效的配置选择推理 runner，并在 runner 初始化过程中解析模型文件。

包的改动必须保持工作区成员、`[tool.uv.sources]`、`scripts/maintenance/release.sh`、依赖元数据和 `uv.lock` 一致。
提交前审查锁文件的变化，然后验证：

```bash
uv lock --check
uv sync --all-packages --locked
```

在根目录的插件目录中更新简明的能力描述和准确的状态。
已有插件链接到其 README；计划中的插件不得使用占位链接，也不得暗示已有实现可用。

## 代码约定

遵循[编码约定](docs/coding-conventions.md)：模块和类的排列顺序，以及它们使用的命名。

---

## 🧩 发布流程

GitHub Release 和 Python 包索引上传是**相互独立**的操作。
推送正式的 `vX.Y.Z` 标签会运行以下流水线：

```text
push v* tag
    ↓
Quality checks (lint, build, install)
    ↓                                    ↓
Linux package                            Generate Release Notes
  built in manylinux_2_28 for the tag,     docs/releases/vX.Y.Z.md
  installed and set up on a clean          + GitHub's PR changelog
  Ubuntu 24.04
    ↓                                    ↓
Create GitHub Release (after both)
  a draft with the notes → attach the package files → download them from the
  draft and check names, sizes and SHA-256s → publish
```

只有当标签对应 Host 版本（`v` + `avatar-host` 的 `__version__`）并指向正在构建的提交时，Linux 包作业才会构建。
已发布的 Release 会保留其文件：一旦公开，重新运行不会改变任何内容。

`.github/workflows/release.yml` 不会向 PyPI 或 TestPyPI 上传任何内容。
源码构建通过并不能证明某个发行包在这两个包索引中的任何一个上可用。

### 1. 在 `main` 上准备发布

使用 CPython 3.13 和已提交的锁文件。
确保 `main` 是最新且干净的。
确认所有包的 `__version__` 值一致，且质量工作流通过。
推送标签前准备好人工撰写的发布说明：

```bash
git switch main
git pull --ff-only origin main
make prepare-release VERSION=0.6.9
# Edit docs/releases/v0.6.9.md and update README.md as needed.
git add docs/releases/v0.6.9.md README.md
git commit -m "docs: prepare v0.6.9 release notes"
make release VERSION=0.6.9 TYPE=prod
```

最后的 `make release` 推送 `v0.6.9` 标签；GitHub Actions 运行上图所示的质量、Linux 包、发布说明和 Release 阶段。
`make release` 本身既不修改版本，也不构建任何内容。
也可以在确认现有的本地 `vX.Y.Z` 标签指向预期的源码提交后推送该标签。
工作流会把 `docs/releases/vX.Y.Z.md`（如果存在）与 GitHub 配置的 PR 变更日志（`.github/release.yml`）合并。
重新运行发布作业会保留现有的 GitHub Release，而不会覆盖其说明。

不要创建 `test-v*` 标签来触发 TestPyPI：这类标签已不再有自动发布工作流。

### 2. 可选：手动发布到 PyPI／TestPyPI

如果需要上传某个特定的 Python 发行包，在 `main` 上打开 GitHub **Actions** → **Publish Package to PyPI (manual)** → **Run workflow**。
选择现有的 `vX.Y.Z` **标签**、要发布的**单个包**，以及 `testpypi` 或 `pypi`（默认为 TestPyPI）。
所需的仓库 secret：

* `TEST_PYPI_API_TOKEN`，用于 TestPyPI。
* `PYPI_API_TOKEN`，用于 PyPI。

手动作业会校验：该标签存在于 `main` 的历史中，所选包属于工作区，且其打包版本与标签一致。
上传前，它只构建并检查所选的发行包。
它**不会**重新打标签、改写包版本，也不会发布工作区中的其他包。
另一个包失败时，已成功上传的产物不会被删除。

对于拥有仓库写权限的 CLI 用户，对应的手动调用方式是：

```bash
gh workflow run publish-pypi.yml --ref main \
  -f tag=v0.6.9 \
  -f package=alpha-avatar-core \
  -f repository=testpypi
```

**可用性警告**：源码工作区目前包含 16 个 Python 包，但 GitHub Release **不**保证全部 16 个包或其对应版本都存在于 PyPI 或 TestPyPI 上。
在文档中写入 `pip install` 命令之前，先在包索引中核实确切的包和版本。
如需完整且版本匹配的安装，请使用发布标签对应的源码检出及其已提交的 `uv.lock`，如主 README 所述。

### 3. 验证结果

确认 GitHub Actions 完成了四个发布阶段，并且 `https://github.com/AlphaAvatar/AlphaAvatar/releases/tag/vX.Y.Z` 包含预期的人工撰写说明和生成的说明，以及 Linux 包文件（`install.sh`、包及其 `.sha256`、清单、wheel 和 `SHA256SUMS`）。
**只**对有意发布的包单独验证 PyPI。

在 `main` 上修改 `.github/workflows/release.yml` 不会追溯修复旧的、由标签触发且已失败的运行。
之前创建的 GitHub Release 和已上传到 PyPI 的发行包仍会保留。
