# Your Avatar workspace

An Avatar workspace contains your saved user information, memories, session records and
files produced by enabled features. It is separate from the source checkout and from the
[downloaded model cache](models-cache-layout.md).

Treat the workspace as private data. Keep a backup before moving it, clearing files or
changing the Avatar ID.

## Choose where your data is stored

Set a stable ID and a workspace base directory in your configuration:

```yaml
avatar:
  id: my_avatar
  name: My Avatar
  work_dir: ~/AlphaAvatarData
```

This stores the Avatar's workspace at `~/AlphaAvatarData/my_avatar/`. AlphaAvatar appends
`avatar.id` to the base directory once. Use the base directory in your configuration,
not the already-expanded `my_avatar/` directory.

An `AVATAR_WORK_DIR` value in your launch environment overrides `avatar.work_dir` and is
also interpreted as a base directory. Check your selected `.env` file when changing the
YAML appears to have no effect. An environment variable exported in your shell can also
override what you expect from a configuration file.

A relative path such as `.alphaavatar_workspace/` is relative to the directory from which
you start the command, not to the YAML file's directory. Use an absolute path or `~` when
you want the same location regardless of how you launch AlphaAvatar. The resolved absolute
path is used throughout that launch.

Without a configured base directory, AlphaAvatar first tries `/var/lib/<avatar-id>/`.
When that location is not writable, it uses `$XDG_DATA_HOME/<avatar-id>/` when configured,
or `~/.local/share/<avatar-id>/`. The home directory belongs to the account running the
service; a container or service account may have a different home from your login shell.

`avatar.id` is required; a configuration without it is rejected. Keep it unchanged when
upgrading or restoring data: a different ID selects a different workspace rather than
finding the old one automatically.
Changing `avatar.name` does not rename the data directory, but it changes the dispatch
name used by the current LiveKit configuration.

## What the folders contain

The workspace root below is the **resolved Avatar directory**, for example
`~/AlphaAvatarData/my_avatar/`. It is not the base `avatar.work_dir` setting to which
AlphaAvatar still needs to append the ID.

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
│   │       ├── manifest.json                 # Reserved summary; not made by workspace setup.
│   │       ├── provider/                     # Model/provider traces, when enabled.
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
is not delivered by the current version. Workspace setup does not create the reserved
manifest files shown above; their absence is not an error.

### Find your profiles and session files

User-related files remain together under `users/<user_key>/`. This keeps the existing
`runtime/`, `persona/`, `identity/`, `.cache/` and `.logs/` structure. Keep the whole user
folder when making a backup; copying only the readable profile can leave out the data
needed to associate it with that user.

Session files are grouped by date under `data/sessions/`. `provider/` can contain model
traces and prompts when their recording settings are enabled. `artifacts/` contains
files produced for that session. The presence of `observations/` or `turns/` does not
promise that all audio, camera frames or conversation turns have been recorded.

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
live under `~/.cache/alphaavatar/models/`. Follow the
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

To move the data, copy the stopped `my_avatar/` directory into the new base directory,
retain the same Avatar ID, and update `avatar.work_dir` or the overriding environment
setting. Give the service account read/write access to the copied files. Start one Host
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

**A new empty workspace appeared.** Check `avatar.id`, the selected YAML, your launch
directory, the service account and any `AVATAR_WORK_DIR` override. A path change does not
move your existing data automatically.

**The path contains the Avatar ID twice.** Use the parent/base directory in the user
configuration. The running application passes its resolved path to children itself.

**Startup reports a permission error.** Make the intended directory writable by the service
account instead of running the entire assistant with elevated privileges merely to access
`/var/lib`.

**A file is absent.** Check whether the corresponding feature or trace setting was enabled.
An empty reserved directory or a completed response is not evidence that a particular
trace, export or media recording was written.
