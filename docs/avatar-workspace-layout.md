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
path is retained by execution subprocesses.

Without a configured base directory, AlphaAvatar first tries `/var/lib/<avatar-id>/`.
When that location is not writable, it uses `$XDG_DATA_HOME/<avatar-id>/` when configured,
or `~/.local/share/<avatar-id>/`. The home directory belongs to the account running the
service; a container or service account may have a different home from your login shell.

Keep `avatar.id` unchanged when upgrading or restoring data. An omitted ID is generated;
a different ID selects a different workspace rather than finding the old one automatically.
Changing `avatar.name` does not rename the data directory, but it changes the dispatch
name used by the current LiveKit configuration.

## What the folders contain

Some folders are created in advance and remain empty until a feature uses them. The
following layout shows where to look; it is not a promise that every conversation, media
frame or in-progress task has been saved.

```text
my_avatar/
├── env/                         # Reserved environment-related workspace area.
├── users/
│   └── <user-id>/
│       ├── runtime/
│       ├── persona/             # Saved user-profile material.
│       ├── identity/            # Identity-related material.
│       ├── .cache/
│       └── .logs/
├── graph/                       # Graph-related feature data, separated by source.
├── data/
│   ├── memory/
│   │   ├── records.sqlite3      # Memory records when the feature uses this store.
│   │   └── exports/
│   │       ├── owners/
│   │       ├── episodes/
│   │       └── contexts/
│   ├── sessions/
│   │   └── <date>/<session-id>/
│   │       ├── provider/        # Provider traces when recording is enabled.
│   │       ├── observations/
│   │       ├── turns/
│   │       ├── artifacts/       # Files produced for this session.
│   │       └── .logs/
│   ├── indexes/                 # Feature indexes and local database files.
│   ├── artifacts/               # Feature-owned output files.
│   ├── episodes/                # Reserved episode-related data area.
│   └── contexts/                # Reserved context/checkpoint data areas.
├── .logs/
└── .cache/
```

Names in angle brackets are examples, not folders to create manually. Session dates use
`YYYY-MM-DD`. Features can add their own subdirectories below these locations.

The presence of `episodes/`, `contexts/` or a checkpoint directory does not mean that an
interrupted task can resume after a restart. Persistent task recovery is not delivered by
this version. Session traces and exported memory are also different from a complete backup.

`env/` is not a replacement for your launch `.env` file. Configuration files, API keys,
external database storage and the model cache may live outside the workspace.

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
