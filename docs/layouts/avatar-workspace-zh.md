# 你的 Avatar 工作区

Avatar 工作区保存你的用户信息、记忆、会话记录，以及已启用功能生成的文件。它与源码检出目录分开，也与[已下载的模型缓存](models-cache.md)分开。

请把工作区当作私有数据。移动工作区、清理文件或更改 Avatar ID 之前，先做好备份。

## 选择数据的存放位置

在配置中设置一个稳定的 ID，需要时再设置完整的工作区目录：

```yaml
avatar:
  id: my_avatar
  name: My Avatar
  workspace_root: /srv/AlphaAvatarData/my_avatar
```

这样工作区正好位于 `/srv/AlphaAvatarData/my_avatar/`。AlphaAvatar 不会在 `avatar.workspace_root` 后追加 Avatar ID。请使用不含 `..` 的绝对路径；YAML 中的相对路径和字面量 `~` 会被拒绝。

省略 `avatar.workspace_root` 时，工作区为 `<application-home>/avatars/<avatar_key>/`。应用主目录如何通过 `ALPHAAVATAR_HOME` 或 `application.home` 选定、其中还存放什么，见[应用数据目录布局](application-home-zh.md)。其中包括应用缓存，`application.cache_root` 可以把它放到别处；它与工作区以及工作区自己的 `.cache/` 目录相互独立。

旧的 `avatar.work_dir` 和 `AVATAR_WORK_DIR` 设置会被拒绝。删除它们，并将 `avatar.workspace_root` 设为现有的完整 Avatar 目录。例如，旧的基础目录 `/srv/AlphaAvatarData` 加上 `avatar.id: my_avatar`，通常表示现有根目录是 `/srv/AlphaAvatarData/my_avatar`，而不是 `/srv/AlphaAvatarData`。以前的回退目录 `/var/lib/<avatar-id>/` 不再被自动选用。检测到旧数据时，Host 可能拒绝使用新的默认工作区；请显式指向现有根目录。更改这项设置不会移动或删除任何现有目录。

`avatar.id` 是必填项；缺少它的配置会被拒绝。升级或恢复数据时保持它不变：使用默认路径时，不同的 ID 会选中不同的工作区。显式指定的根目录保持其路径，但记录不会迁移到新的 Avatar ID 下。更改 `avatar.name` 不会重命名数据目录，但会改变当前 LiveKit 配置使用的 dispatch 名称。

## 各目录的内容

下文的工作区根目录指**完整的 Avatar 目录**，例如 `/srv/AlphaAvatarData/my_avatar/`。配置了 `avatar.workspace_root` 时，它就是该值本身。

有些目录在存入任何数据之前就已准备好。其他文件只在已启用的功能保存内容时出现。标为 **reserved**（预留）的条目表示留给将来使用的位置；你不应自行创建这些文件，也不应期望启动后会出现它们。

```text
<workspace>/
├── env/                                      # Reserved environment-related area.
│
├── users/
│   └── <user_key>/
│       ├── runtime/                          # Saved user runtime information.
│       ├── persona/                          # Saved profiles and preferences.
│       ├── identity/                         # Identity-related feature data.
│       ├── .cache/                           # User-specific temporary data.
│       └── .logs/                            # User-specific diagnostic files, if used.
│
├── graph/
│   ├── memory/                               # Relationships derived from saved memories.
│   ├── persona/                              # Reserved; not populated by this layout.
│   └── documents/                            # Reserved; not populated by this layout.
│
├── data/
│   ├── memory/
│   │   ├── records.sqlite3                   # Main Memory database for this workspace.
│   │   └── exports/                          # Readable copies, not another main database.
│   │       ├── owners/
│   │       │   ├── avatar/
│   │       │   │   └── <avatar_key>/<memory_key>.md
│   │       │   └── user/
│   │       │       └── <user_key>/<memory_key>.md
│   │       ├── episodes/
│   │       │   └── <episode_key>/memories/<memory_key>.md
│   │       └── contexts/
│   │           └── <context_key>/memories/<memory_key>.md
│   │
│   ├── episodes/
│   │   └── <episode_key>/
│   │       └── manifest.json                 # Reserved summary; not made by workspace setup.
│   │
│   ├── contexts/
│   │   └── <context_key>/
│   │       ├── checkpoints/                  # Reserved task-recovery location.
│   │       └── artifacts/                    # Files belonging to a context, when used.
│   │
│   ├── sessions/
│   │   └── <YYYY-MM-DD>/<session_key>/
│   │       ├── manifest.json                 # Host-created Session identity and creation time.
│   │       ├── provider/                     # Provider traces, when enabled.
│   │       ├── observations/                 # Observation-related files, when saved.
│   │       ├── turns/                        # Turn-related files, when saved.
│   │       ├── artifacts/                    # Files produced for this session.
│   │       └── .logs/                        # Session diagnostics, when used.
│   │
│   ├── indexes/
│   │   └── <feature>/<backend>/              # Local indexes, when the feature uses them.
│   │
│   └── artifacts/
│       └── <feature>/                        # Feature-owned output files, when used.
│
├── .logs/
│   └── host/
│       ├── alphaavatar-<timestamp>-<pid>.jsonl
│       └── alphaavatar-<timestamp>-<pid>.jsonl.1  # Older part after log rotation.
│
└── .cache/                                   # Workspace-local temporary data.
```

`<user_key>`、`<memory_key>` 以及其他尖括号中的名称，代表 AlphaAvatar 选定的文件系统安全名称，并不是字面上的目录名。原始 ID 含有不适合用作文件名的字符时，这些名称可能与原始 ID 不同。对于记忆导出文件，由文档内部的 ID 标识所保存的记录。不要为了与显示名称一致而重命名目录。

使用默认本地存储时，功能索引可以位于 `data/indexes/memory/lancedb/`。其他功能可以在 `indexes/` 下使用各自的命名空间。每个文本向量表旁边的 `<table>.embedding.json` 记录生成这些向量的 embedding 模型（Qdrant collection 的记录在 `<collection>__embedding` 中，以其唯一的命名向量标明是 AlphaAvatar 的记录）：其他模型或其他向量维度的索引会被拒绝，而不是混在一起；与记录同名、但并非这种记录的文件或 collection 保持原样。备份记录时连同它的表一起备份。Host 在记录新的 Qdrant collection 时被停止，可能在那里留下一条待定记录：没有 Host 依赖它，该处仍会拒绝其他模型，也没有任何机制会自动删除它。自定义数据库路径或外部数据库可以把相应数据存到别处。这里的布局是位置指南，不是每个安装都必须具备的统一目录清单。

### 查找记忆

`data/memory/records.sqlite3` 是**本 Avatar 工作区内**各会话共享的 Memory 主存储。它不是供所有 Avatar 或所有用户使用的一个公共数据库；每条记忆仍保留自己的归属和作用范围。`exports/` 目录提供可以用文本编辑器打开的 Markdown 副本。

导出位置取决于记忆属于什么：

| 记忆属于 | 在 `data/memory/exports/` 下查找 |
| --- | --- |
| Avatar | `owners/avatar/<avatar_key>/<memory_key>.md` |
| 某个用户 | `owners/user/<user_key>/<memory_key>.md` |
| 某个 episode，即交互分组 | `episodes/<episode_key>/memories/<memory_key>.md` |
| 某个 context，即相关任务分组 | `contexts/<context_key>/memories/<memory_key>.md` |

例如，属于 `my_avatar` 的 Avatar 记忆可能出现在 `data/memory/exports/owners/avatar/my_avatar/<memory_key>.md`。按 owner 划定范围、且有多个 owner 的记忆可能有多份可读副本。按 episode 或 context 划定范围的记忆使用该分组的导出目录，不会自动复制到表中全部四个位置。

导出文件由数据库生成，可能比保存的记录晚出现。编辑或删除 Markdown 导出文件**不会**更新或删除原始记忆，把导出文件复制回去也不会恢复数据库。不要把这些文件当作修改助理记忆内容的非正式途径。

`data/memory/exports/episodes/` 与 `data/episodes/` 不同：前者存放可读的记忆副本，后者是存放 episode 信息的独立区域。两个 context 位置也是同样的区别。**记忆已导出，并不表示中断的任务能在重启后恢复**。当前版本尚未提供持久的任务恢复。episode 摘要 manifest 仍是预留的；Host 在准备执行时创建每个 Session 的 `manifest.json`。

### 查找画像和会话文件

与用户相关的文件集中在 `users/<user_key>/` 下，沿用现有的 `runtime/`、`persona/`、`identity/`、`.cache/` 和 `.logs/` 结构。备份时保留整个用户目录；只复制可读的画像，可能遗漏将其与该用户关联所需的数据。

会话文件在 `data/sessions/` 下按日期分组。启用相应的记录设置后，`provider/` 可以包含模型 trace 和提示词。`artifacts/` 包含为该会话生成的文件。存在 `observations/` 或 `turns/` 并不保证所有音频、摄像头帧或对话轮次都已被记录。

提取出的记忆和 Memory 提取 checkpoint 存储在 `data/memory/records.sqlite3` 中。待处理的 Conversation、Tool 和 Persona 提取输入保存在内存中；当前插件不会归档这些输入，也不会在进程重启后恢复它们。

Conversation 和 Tool 处理器在收尾时提取全部未处理的输入。Persona 在关闭时根据缓存的完整对话更新画像。Memory 不安排定期提取，这些更新也不会把输入拆成更小的批次。Memory 提取失败时不会推进其 checkpoint。保留的输入以及对现有 Turn 快照的引用会随会话增长；它们不是另一个媒体归档，也不是持久的恢复队列。

`graph/memory/` 保存从记忆推导出的关系。上方目录树中的 `persona/` 和 `documents/` 图目录是预留的分隔位置，不是已完成的附加图功能。把这些目录留给拥有它们的功能，不要把无关文件移入其中。

### 查找日志和临时文件

启动时输出的 `Diagnostic log file=...` 一行给出服务日志的实际路径。默认情况下，日志写入 `.logs/host/`；`host.log.directory` 可以把日志放到别处，`host.log.file: false` 关闭文件日志。`.jsonl` 文件可以用文本编辑器阅读。它是诊断日志，不是对话备份。

每次启动创建单独的日志文件。使用默认设置时，该次启动保留当前文件和最多三个轮转分卷（`.1`、`.2`、`.3`）。之前启动留下的文件不会被自动删除。日志可能包含路径或私人信息，因此分享前先检查；只在相关 Host 停止后再删除不需要的旧日志。

工作区的 `.cache/` 与已下载的模型权重分开，后者通常位于 `<application-cache>/models/` 下。移动或清理已下载的模型时，请按照[模型缓存指南](models-cache.md)操作。`env/` 不能代替启动用的 `.env` 文件，也不会自动成为凭据保管库。将 API key 和配置文件放在各自预定的受保护位置，不要复制到预留的工作区目录中。

## 备份或移动工作区

复制工作区之前，先正常停止 Host，并等待其执行进程结束。复制正在使用的数据库目录可能得到不一致的备份。

备份整个 Avatar 目录，包括隐藏文件和子目录，不要只复制 Markdown 导出文件或某一个数据库文件。将配置和所需凭据另行存放在受保护的存储中。外部数据库通过其自身的备份流程备份；复制这个目录不会复制其他服务保存的数据。

要移动数据，复制已停止使用的完整工作区目录，保留相同的 Avatar ID，并将 `avatar.workspace_root` 设为复制后的目录本身。例如，复制到 `/mnt/avatars/my_avatar/` 后，就配置这个根目录。为服务账户授予复制文件的读写权限。针对新位置启动一个 Host，确认预期的画像和记忆都在，然后再删除旧副本。不要让新旧两个部署同时使用同一份本地文件，作为非正式的迁移测试。

移动模型缓存是另一项操作。请按照[模型缓存指南](models-cache.md)操作，不要把模型文件移入 `data/`。

## 释放空间而不丢失数据

先用文件管理器的大小视图找出占用空间大的目录。删除任何内容之前，先停止服务并做好备份。

`data/memory/`、`users/`、`graph/`、索引和会话产物可能包含无法通过重新下载模型恢复的信息。不要把它们当作可随意丢弃的模型缓存。删除索引后可能需要从原始文档重建；删除产物可能使已保存的对该文件的引用失效。

日志和 provider trace 可能包含敏感文本或提示词。只保留需要的内容，分享文件用于排查问题前先检查。本指南不提供通用的自动保留策略或安全清理命令。

## 常见问题

**出现了一个新的空工作区。** 检查 `avatar.id`、`avatar.workspace_root`、`application.home`、`ALPHAAVATAR_HOME`、所选 YAML 和服务账户。路径变更不会自动移动现有数据。

**路径中出现了两次 Avatar ID。** `avatar.workspace_root` 本身已是完整路径；从这项显式设置中去掉重复的部分。Host 不会在它后面追加 ID。

**启动时拒绝 `work_dir` 或旧的缓存环境变量。** 用完整的 `avatar.workspace_root` 替换 `avatar.work_dir`，取消设置 `AVATAR_WORK_DIR` 和 `ALPHAAVATAR_MODEL_CACHE`，并用 `application.cache_root` 指定应用缓存。服务环境和它所选的 `.env` 文件都要检查。

**启动时报告权限错误。** 让服务账户对目标目录有写权限，不要以提升的权限运行整个助理。

**缺少某个文件。** 检查相应的功能或 trace 设置是否已启用。空的预留目录或已完成的响应，都不能证明某个 trace、导出文件或媒体录制已被写入。
