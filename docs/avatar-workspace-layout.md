# Your Avatar workspace

An Avatar workspace contains your saved user information, memories, session records and
files produced by enabled features. It is separate from the source checkout and from the
[downloaded model cache](models-cache-layout.md).

Treat the workspace as private data. Keep a backup before moving it, clearing files or
changing the Avatar ID.

## Choose where your data is stored

Set a stable ID and, when needed, the complete workspace directory in your configuration:

```yaml
avatar:
  id: my_avatar
  name: My Avatar
  workspace_root: /srv/AlphaAvatarData/my_avatar
```

This stores the workspace at exactly `/srv/AlphaAvatarData/my_avatar/`. AlphaAvatar does
not append the Avatar ID to `avatar.workspace_root`. Use an absolute path without `..`;
relative paths and a literal `~` in YAML are rejected.

When `avatar.workspace_root` is omitted, the workspace is
`<application-home>/avatars/<avatar_key>/`. Choose the application home with the
`ALPHAAVATAR_HOME` launch environment variable, or set `application.home` in YAML to
override that environment-selected home. Both values must be complete absolute paths.
Without either setting, Host uses the service account's platform data directory:

| Platform | Default application home |
| --- | --- |
| Linux | `$XDG_DATA_HOME/alphaavatar/`, or `~/.local/share/alphaavatar/` |
| macOS | `~/Library/Application Support/AlphaAvatar/` |
| Windows | `%LOCALAPPDATA%/AlphaAvatar/`, or `~/AppData/Local/AlphaAvatar/` |

The application home contains `configs/profiles/`, `configs/bundles/`,
`settings/settings.yaml`, `cache/` and `avatars/`. These paths do not imply that every
configuration UI or settings workflow has already been implemented. `cache/` contains
`models/`, `downloads/`, `providers/`, `diagnostics/` and `avatars/<avatar_key>/`.
Set `application.cache_root` to an absolute path to place the whole application cache
elsewhere; it is separate from the workspace and its own `.cache/` directory.

Legacy `avatar.work_dir` and `AVATAR_WORK_DIR` settings are rejected. Remove them and set
`avatar.workspace_root` to the existing complete Avatar directory. For example, an old
base `/srv/AlphaAvatarData` with `avatar.id: my_avatar` usually means that the existing
root is `/srv/AlphaAvatarData/my_avatar`, not `/srv/AlphaAvatarData`. The former
`/var/lib/<avatar-id>/` fallback is no longer selected automatically. Host may refuse a
new default workspace when older data is detected; explicitly point to the existing root.
No existing directory is moved or deleted by changing this setting.

`avatar.id` is required; a configuration without it is rejected. Keep it unchanged when
upgrading or restoring data: with the default path, a different ID selects a different
workspace. An explicit root keeps its path, but does not migrate records to a new Avatar ID.
Changing `avatar.name` does not rename the data directory, but it changes the dispatch
name used by the current LiveKit configuration.

## What the folders contain

The workspace root below is the **complete Avatar directory**, for example
`/srv/AlphaAvatarData/my_avatar/`. It is the exact `avatar.workspace_root` when configured.

Some folders are prepared before they contain any data. Other files appear only when
an enabled feature saves something. Items marked **reserved** show intended locations
for future use; they are not files you should create yourself or expect after startup.

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

`<user_key>`, `<memory_key>` and the other names in angle brackets stand for the
filesystem-safe names AlphaAvatar chooses. They are not literal folder names. They
can differ from the original IDs when those IDs contain characters unsuitable for a
filename. For a memory export, the IDs inside the document identify the saved record.
Do not rename folders to make them match a display name.

For the default local storage, a feature index can live at
`data/indexes/memory/lancedb/`. Other features can use their own namespaces below
`indexes/`. A custom database path or an external database can store the corresponding
data elsewhere. The layout is a guide to locations, not a list of identical folders
that every installation must have.

### Find your memories

`data/memory/records.sqlite3` is the main Memory store shared by sessions **within this
Avatar workspace**. It is not one public database for every Avatar or every user;
individual memories still retain their ownership and scope. The `exports/` folder
provides Markdown copies that you can open in a text editor.

The export location depends on what the memory belongs to:

| Memory belongs to | Look under `data/memory/exports/` |
| --- | --- |
| The Avatar | `owners/avatar/<avatar_key>/<memory_key>.md` |
| A user | `owners/user/<user_key>/<memory_key>.md` |
| An episode, or interaction grouping | `episodes/<episode_key>/memories/<memory_key>.md` |
| A context, or related task grouping | `contexts/<context_key>/memories/<memory_key>.md` |

For example, an Avatar-owned memory for `my_avatar` can appear at
`data/memory/exports/owners/avatar/my_avatar/<memory_key>.md`.
An owner-scoped memory with more than one owner can have more than one readable copy.
An episode- or context-scoped memory uses that grouping's export directory; it is not
automatically copied into all four locations in the table.

Exports are produced from the database and may appear later than the saved record.
Editing or deleting a Markdown export does **not** update or delete the original
memory, and copying exports back does not restore the database. Do not use these
files as an unofficial way to change what the assistant remembers.

`data/memory/exports/episodes/` is different from `data/episodes/`: the former holds
readable memory copies, while the latter is a separate area for episode information.
The same distinction applies to the two context locations. **An exported memory does
not mean an interrupted task can resume after a restart.** Persistent task recovery
is not delivered by the current version. The episode summary manifest remains reserved;
Host creates each Session's `manifest.json` during execution setup.

### Find your profiles and session files

User-related files remain together under `users/<user_key>/`. This keeps the existing
`runtime/`, `persona/`, `identity/`, `.cache/` and `.logs/` structure. Keep the whole user
folder when making a backup; copying only the readable profile can leave out the data
needed to associate it with that user.

Session files are grouped by date under `data/sessions/`. `provider/` can contain model
traces and prompts when their recording settings are enabled. `artifacts/` contains
files produced for that session. The presence of `observations/` or `turns/` does not
promise that all audio, camera frames or conversation turns have been recorded.

Extracted memories and Memory extraction checkpoints are stored in
`data/memory/records.sqlite3`. Pending Conversation, Tool and Persona extraction inputs
are held in memory; the current plugins do not archive those inputs or restore them
after a process restart.

`graph/memory/` keeps relationships derived from memories. The `persona/` and
`documents/` graph directories in the diagram are reserved separation points, not
completed additional graph features. Leave these directories to the features that own
them rather than moving unrelated files into them.

### Find your logs and temporary files

The startup line `Diagnostic log file=...` gives the actual service-log path. By
default, logs go to `.logs/host/`; `host.log.directory` can place them elsewhere and
`host.log.file: false` disables file logging. A `.jsonl` file can be read with a text
editor. It is a diagnostic log, not a conversation backup.

Each launch creates a separate log file. With the default settings, that launch keeps
the current file and up to three rotated parts (`.1`, `.2`, `.3`). Files from older
launches are not automatically removed. Logs can include paths or private information,
so inspect them before sharing and remove unneeded old logs only after the relevant
Host has stopped.

The workspace `.cache/` is separate from downloaded model weights, which normally
live under `<application-cache>/models/`. Follow the
[model cache guide](models-cache-layout.md) when moving or clearing model downloads.
`env/` is not a replacement for your launch `.env` file and is not automatically a
credential vault. Keep API keys and configuration files in their intended protected
locations rather than copying them into a reserved workspace folder.

## Back up or move a workspace

Stop the Host normally and wait for its execution processes to finish before copying the
workspace. Copying a live database directory can produce an inconsistent backup.

Back up the entire Avatar directory, including hidden files and subdirectories, rather
than copying only Markdown exports or one database file. Keep the configuration and
required credentials separately in protected storage. Back up an external database through
its own backup procedure; copying this directory does not copy data held by another service.

To move the data, copy the stopped complete workspace directory, retain the same Avatar ID,
and set `avatar.workspace_root` to the copied directory itself. For example, after copying
to `/mnt/avatars/my_avatar/`, configure that exact root. Give the service account read/write
access to the copied files. Start one Host
against the new location and verify that the expected profiles and memories appear before
removing the old copy. Do not run the old and new deployment against the same local files
as an informal migration test.

A model-cache move is a separate operation. Follow the
[model cache guide](models-cache-layout.md) rather than moving model files into `data/`.

## Free up space without losing your data

Use your file manager's size view to identify the large folders first. Stop the service
and make a backup before removing anything.

`data/memory/`, `users/`, `graph/`, indexes and session artifacts can contain information
that cannot be recovered by downloading a model again. Do not treat them as disposable
model caches. Removing an index can require rebuilding it from the original documents;
removing an artifact can break a saved reference to that file.

Logs and provider traces can contain sensitive text or prompts. Retain only what you need,
and review files before sharing them for troubleshooting. No general automatic retention
or safe-cleanup command is provided by this guide.

## Common problems

**A new empty workspace appeared.** Check `avatar.id`, `avatar.workspace_root`,
`application.home`, `ALPHAAVATAR_HOME`, the selected YAML and the service account. A path
change does not move your existing data automatically.

**The path contains the Avatar ID twice.** `avatar.workspace_root` is already complete;
remove the duplicate component from that explicit setting. Host does not append an ID to it.

**Startup rejects `work_dir` or an old cache environment variable.** Replace
`avatar.work_dir` with the complete `avatar.workspace_root`, unset `AVATAR_WORK_DIR` and
`ALPHAAVATAR_MODEL_CACHE`, and use `application.cache_root` for the application cache.
Check both the service environment and its selected `.env` file.

**Startup reports a permission error.** Make the intended directory writable by the service
account instead of running the entire assistant with elevated privileges.

**A file is absent.** Check whether the corresponding feature or trace setting was enabled.
An empty reserved directory or a completed response is not evidence that a particular
trace, export or media recording was written.
