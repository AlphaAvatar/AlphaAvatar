# Downloaded models and cache folders

AlphaAvatar downloads the local models needed by your selected configuration during
startup. A first launch may therefore take longer than later launches. Models are separate
from your [Avatar workspace](avatar-workspace-layout.md): removing a model cache is not the
same as removing memories, profiles or conversation data.

## Find or choose the cache location

The default location is:

```text
~/.cache/alphaavatar/models/
```

`~` refers to the home directory of the account running AlphaAvatar. A container or service
account can use a different location from your interactive terminal.

Set `ALPHAAVATAR_MODEL_CACHE` in your launch environment to choose another directory:

```dotenv
ALPHAAVATAR_MODEL_CACHE=/srv/alphaavatar-models
```

Use an absolute path and give the service account read/write permission. The setting
selects the model-cache root itself; AlphaAvatar creates the feature subdirectories below
it. It does not move an existing cache automatically.

## Understand the layout

Only the models required by enabled local features are downloaded. Your cache may contain
just part of this layout:

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

`hub/` directories can contain Hugging Face blobs, snapshots and references. Several
snapshots may share the same underlying file. Leave their internal names and links intact;
renaming a snapshot or copying only an individual weight file can make the cache unusable.
Integrity manifests and lock files are part of cache management and should not be edited
by hand.

Hosted language models, remote speech services, embedding APIs and MCP servers are not
turned into local models by this cache setting. Browser installation and frontend files
for optional Character presentation are also separate; see
[Character setup](../avatar-plugins/perception/avatar-plugins-character/README.md).

## Move or reuse a cache

Stop the Host and its model processes before moving files. Copy the entire model-cache
root, preserving subdirectories, hidden files, manifests and symbolic links. Update
`ALPHAAVATAR_MODEL_CACHE` to the new root, keep the original copy initially, then restart
with the intended configuration to verify that the required models load.

Changing the cache setting does not migrate an older layout. A missing file at the new
location may be downloaded again when network access is allowed. Model compatibility also
depends on the selected configuration and package revision; a directory named after the
right feature does not guarantee that it contains the right model revision.

For containers, keep the cache on a persistent, writable mounted directory when you want
downloads to survive container replacement. Do not make the cache read-only: startup may
need to create lock files or integrity manifests even when model downloads are disabled.

## Start without downloading models

First run the intended configuration with network access so its required local models are
present and validated. Stop the service and copy the complete cache when moving it to
another machine. Then enable offline model loading in the launch environment:

```dotenv
ALPHAAVATAR_MODEL_OFFLINE=1
```

`HF_HUB_OFFLINE=1` also disables the supported model-resolver downloads. Missing or invalid
files then cause startup to fail instead of downloading replacements.

This is **offline model loading**, not a fully offline assistant. A configuration using
remote LLM, STT, TTS, embedding or tool services still needs those services. Successful
model warmup alone does not establish that every enabled feature can work without a
network connection.

There is no separate required `download-files` command in the native Host. Models are
prepared by starting the selected configuration.

## Use your own supported model file

The supported local-file overrides include:

```dotenv
SMART_TURN_MODEL_PATH=/srv/custom-models/smart-turn.onnx
SILERO_VAD_MODEL_PATH=/srv/custom-models/silero.onnx
```

Provide the file expected by the corresponding implementation, not a directory or an
arbitrary model with a similar name. These files remain user-owned and are not moved into
the default cache. A nonempty file is not proof of model compatibility.

The bundled model checksum is not imposed on an explicit override, so you are responsible
for its origin and suitability. Keep a copy of your override and its version information
when backing up a deployment.

## Clear or repair downloaded files

Stop the service before removing cache files. When network access is available, a missing
required default model can be downloaded again on the next startup. In offline mode it
will instead fail to load. Keep a known-good copy before clearing a cache on an offline
machine.

Prefer removing the affected feature/version cache as a unit after making a backup rather
than deleting shared Hugging Face blobs or editing manifests. Do not delete your Avatar
workspace while trying to repair a model download.

Where the configuration supplies a published checksum, AlphaAvatar verifies it. Some
sources instead use a locally recorded first-use checksum. That detects later corruption;
it is not an independent guarantee that the original download was trustworthy. Explicit
local model overrides follow the separate rule described above.

## Common problems

**The same model downloads again.** Check the service account, cache-root setting,
configuration/model revision, persistent container mount and write permissions.

**Offline startup fails.** Confirm that the complete cache belongs to the intended
configuration. Copying only one snapshot file or enabling a new local feature can leave
required files missing.

**A cached file is reported as invalid.** Keep the failure details, restore a known-good
copy or allow the affected model to be downloaded again. Do not bypass validation or edit
an integrity manifest to make an unverified file appear valid.

**The assistant still contacts an external service.** Review the selected cloud providers
and tools. Model-cache offline settings do not replace or disable those integrations.
