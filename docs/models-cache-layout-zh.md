# 已下载的模型与缓存目录

[English](models-cache-layout.md)

AlphaAvatar 在启动时下载所选配置需要的本地模型，因此首次启动可能比之后的启动耗时更长。模型与你的 [Avatar 工作区](avatar-workspace-layout.md)分开：删除模型缓存不等于删除记忆、画像或对话数据。

## 查找或选择缓存位置

默认的模型位置在应用主目录下：

```text
<application-home>/cache/models/
```

在 Linux 上，默认应用主目录是 `$XDG_DATA_HOME/alphaavatar/` 或 `~/.local/share/alphaavatar/`；macOS 使用 `~/Library/Application Support/AlphaAvatar/`，Windows 使用 `%LOCALAPPDATA%/AlphaAvatar/` 或 `~/AppData/Local/AlphaAvatar/`。`~` 指服务账户的用户目录。将 `ALPHAAVATAR_HOME` 设为一个绝对路径作为应用主目录，或在所选 YAML 中用 `application.home` 覆盖它。

要选择其他应用缓存目录，添加以下顶层 YAML 部分：

```yaml
application:
  cache_root: /srv/alphaavatar-cache
```

使用不含 `..` 或字面量 `~` 的绝对路径，并为服务账户授予读写权限。这项设置选择的是整个应用缓存，因此模型存放在 `/srv/alphaavatar-cache/models/` 下；其他缓存区域包括 `downloads/`、`providers/`、`diagnostics/` 和 `avatars/`。它不会自动移动现有文件。

Host 会拒绝旧的 `ALPHAAVATAR_MODEL_CACHE` 环境变量。取消设置它，改用 `application.cache_root`。如果之前的模型目录是 `/srv/alphaavatar-models/`，在更改配置之前，把它的全部内容复制到新缓存的 `models/` 目录中。不要把 `application.cache_root` 直接设为那个旧模型目录，否则新布局会在其中再查找一层 `models/` 子目录。

## 了解布局

只会下载已启用的本地功能所需的模型。你的缓存可能只包含以下布局的一部分：

```text
models/
├── voice/
│   └── vad/silero/v6.2.1/
├── router/
│   ├── addressing/semantic/hub/
│   └── turn_taking/smart_turn/v3.2-cpu/hub/
└── persona/
    ├── speaker/
    │   ├── vector/hub/
    │   └── attribute/hub/
    └── face/buffalo_l/v0.7/
        ├── archives/
        └── models/buffalo_l/
```

`hub/` 目录可以包含 Hugging Face 的 blob、snapshot 和引用。多个 snapshot 可能共用同一个底层文件。保持其内部名称和链接不变；重命名 snapshot 或只复制单个权重文件，可能导致缓存不可用。完整性 manifest 和锁文件属于缓存管理的一部分，不应手动编辑。

托管的语言模型、远程语音服务、embedding API 和 MCP 服务器不会因为这项缓存设置而变成本地模型。可选的 Character 展示所需的浏览器安装和前端文件也是分开的；见 [Character 设置](../avatar-plugins/perception/avatar-plugins-character/README.md)。

## 移动或复用缓存

移动文件之前，先停止 Host 及其模型进程。复制整个模型缓存根目录，保留子目录、隐藏文件、manifest 和符号链接。将它复制到 `<new-application-cache>/models/`，并将 `application.cache_root` 改为其上一级的缓存目录。先保留原副本，然后用预定的配置重新启动，确认所需模型能够加载。

更改缓存设置不会迁移旧布局。新位置缺少的文件在允许联网时可能被重新下载。模型兼容性还取决于所选配置和包的版本；目录以正确的功能命名，并不保证其中是正确的模型版本。

在容器中，如果希望下载内容在替换容器后仍然保留，就把缓存放在持久、可写的挂载目录上。不要把缓存设为只读：即使禁用了模型下载，启动时也可能需要创建锁文件或完整性 manifest。

## 不下载模型启动

先在联网状态下运行预定的配置，使其所需的本地模型齐备并通过校验。要转移到另一台机器时，停止服务并复制完整的缓存。然后在启动环境中启用离线模型加载：

```dotenv
ALPHAAVATAR_MODEL_OFFLINE=1
```

`HF_HUB_OFFLINE=1` 同样会禁用受支持的模型解析器下载。此时缺失或无效的文件会导致启动失败，而不是下载替换文件。

这是**离线模型加载**，不是完全离线的助理。使用远程 LLM、STT、TTS、embedding 或工具服务的配置仍然需要这些服务。仅凭模型预热成功，不能证明每个已启用的功能都能在没有网络连接时工作。

原生 Host 没有必须单独运行的 `download-files` 命令。启动所选配置即可准备模型。

## 使用自己的受支持模型文件

受支持的本地文件覆盖项包括：

```dotenv
SMART_TURN_MODEL_PATH=/srv/custom-models/smart-turn.onnx
SILERO_VAD_MODEL_PATH=/srv/custom-models/silero.onnx
```

提供相应实现所期望的文件，而不是目录或名称相近的任意模型。这些文件仍归用户所有，不会被移入默认缓存。文件非空并不能证明模型兼容。

内置的模型校验和不会施加于显式覆盖的文件，因此你需要自行负责其来源和适用性。备份部署时，保留覆盖文件及其版本信息的副本。

## 清理或修复已下载的文件

删除缓存文件之前，先停止服务。可以联网时，缺失的必需默认模型可以在下次启动时重新下载。在离线模式下则会加载失败。在离线机器上清理缓存之前，先保留一份已知完好的副本。

优先在备份后将受影响的功能／版本缓存作为整体删除，而不是删除共享的 Hugging Face blob 或编辑 manifest。尝试修复模型下载时，不要删除你的 Avatar 工作区。

配置提供了已发布的校验和时，AlphaAvatar 会进行校验。有些来源改用首次使用时在本地记录的校验和。它能发现之后的损坏，但不能独立保证最初的下载可信。显式的本地模型覆盖遵循上文所述的单独规则。

## 常见问题

**同一个模型又被下载了一次。** 检查服务账户、缓存根目录设置、配置／模型版本、容器的持久挂载和写权限。

**离线启动失败。** 确认完整的缓存属于预定的配置。只复制一个 snapshot 文件，或启用了新的本地功能，都可能导致缺少必需的文件。

**缓存文件被报告为无效。** 保留失败详情，恢复已知完好的副本，或允许重新下载受影响的模型。不要绕过校验，也不要编辑完整性 manifest 让未经验证的文件看起来有效。

**助理仍然连接外部服务。** 检查所选的云服务供应商和工具。模型缓存的离线设置不会替代或禁用这些集成。
