# 应用数据目录布局

AlphaAvatar 在一台机器上保存的内容分属三个根目录：**应用主目录**、**应用缓存**，以及每个 Avatar 各自的 **Avatar 工作区**。除非另行配置，应用缓存和各工作区都位于应用主目录之内。本页说明每个根目录如何选定、应用主目录存放什么，以及哪些目录按需创建、哪些是预留的；另外两个根目录见 [Avatar 工作区](avatar-workspace-zh.md)和[模型与缓存](models-cache-zh.md)。

Linux 包的程序文件不在其中任何一个目录下：安装程序把它们放在 `~/.local/lib/alphaavatar`，把 `alphaavatar` 命令放在 `~/.local/bin`。升级不会写入应用主目录，清理也从不删除应用主目录及其缓存（[setup](../cli/setup-zh.md)、[upgrade](../cli/upgrade-zh.md)、[cleanup](../cli/cleanup-zh.md)）。

## 三个根目录

| 根目录 | 存放 | 设置方式 | 默认位置 |
| --- | --- | --- | --- |
| 应用主目录 | bundle、profile、设置和已保存的凭据；默认还包括缓存和各 Avatar 工作区 | `application.home`，或 `ALPHAAVATAR_HOME` | 按平台而定，见下文 |
| 应用缓存 | 已下载的模型文件 | YAML 中的 `application.cache_root` | `<application-home>/cache/` |
| Avatar 工作区 | 单个 Avatar 的用户、记忆、会话、日志和临时文件 | YAML 中的 `avatar.workspace_root` | `<application-home>/avatars/<avatar_key>/` |

每个路径都必须是绝对路径，且不含 `..`；YAML 中的相对路径或字面量 `~` 会被拒绝。`application` 只接受 `home` 和 `cache_root`。修改根目录不会移动任何内容：请把它指向已有的目录，或先把数据复制过去。Host 会拒绝旧的设置 `avatar.work_dir`、`AVATAR_WORK_DIR` 和 `ALPHAAVATAR_MODEL_CACHE`。

## 选择应用主目录

应用主目录按以下顺序确定：

1. 在命令行以配置覆盖项给出的 `application.home`，或命令所加载的配置文件中设置的 `application.home`；
2. 环境中的 `ALPHAAVATAR_HOME`；环境中未设置或为空时，取 `ENV_FILE` 指定的 `.env` 文件中的值；
3. 服务账户所在平台的数据目录：

| 平台 | 默认应用主目录 |
| --- | --- |
| Linux | `$XDG_DATA_HOME/alphaavatar/`，或 `~/.local/share/alphaavatar/` |
| macOS | `~/Library/Application Support/AlphaAvatar/` |
| Windows | `%LOCALAPPDATA%/AlphaAvatar/`，或 `~/AppData/Local/AlphaAvatar/` |

设置从不决定应用主目录。命名 bundle 属于存放它的那个应用主目录：bundle 若设置了 `application.home`，必须指向同一个目录。见[选择配置](../cli/config-zh.md#选择配置)。

## 应用主目录的内容

```text
<application-home>/
├── configs/
│   ├── bundles/<name>.yaml        # 可直接启动的配置。
│   └── profiles/<name>.yaml       # 供多个 bundle 共用的配置段；名称可以含 / 分段。
├── settings/
│   ├── settings.yaml              # default_bundle 以及已保存凭据的文件名。
│   └── credentials-<id>.env       # setup 保存的凭据，仅你本人可读。
├── cache/                         # 应用缓存，除非 application.cache_root 将其移到别处。
│   ├── models/                    # 已下载的模型文件。
│   ├── downloads/                 # 预留。
│   ├── providers/                 # 预留。
│   ├── diagnostics/               # 预留。
│   └── avatars/                   # 预留。
└── avatars/
    └── <avatar_key>/              # 一个 Avatar 工作区，除非 avatar.workspace_root 将其移到别处。
```

`<name>`、`<id>` 和 `<avatar_key>` 代表实际名称：bundle 或 profile 的名称、一个随机标识，以及 Avatar ID 适合用作文件名的形式。

- **bundle 与 profile** 由 `alphaavatar config init` 和 `alphaavatar setup` 写入，也可以手动编辑；见 [config](../cli/config-zh.md#bundle-与-profile)。
- **设置**：`settings.yaml` 指明默认 bundle 和已保存凭据所在的文件；`config init` 和 setup 会写入它。只有在 setup 中同意保存所输入的凭据后，才会有凭据文件；命令还会从哪里读取凭据，见[凭据](../cli/config-zh.md#凭据)。
- **缓存**把模型文件保存在 `models/` 下；与应用主目录的其他内容不同，它可以清除后重新下载。移动、复用和清理缓存见[模型与缓存](models-cache-zh.md)。
- **Avatar 工作区**保存无法重新下载的私有数据；见 [Avatar 工作区](avatar-workspace-zh.md)。

## 按需创建与预留目录

`start` 和 `dev` 会在 Host 启动前创建上图中的所有目录，以及 Avatar 工作区自身的目录；`config init` 和 setup 会创建它们要写入的内容。文件只有在有内容写入时才会出现：`models/` 为空表示尚未下载任何模型，某个目录存在也不能证明相应功能已经运行过。

**预留**目录会被创建，但当前版本不使用：缓存中的 `downloads/`、`providers/`、`diagnostics/` 和 `avatars/`。工作区有自己的预留目录，列在其[目录说明](avatar-workspace-zh.md#各目录的内容)中。不要把其他文件放进这些目录。

## 备份

先停止 Host。把应用主目录的 `configs/` 和 `settings/` 与所需的工作区一起保存，并像保护其他机密一样保护凭据文件。缓存无需备份：其中的内容可以重新下载。
