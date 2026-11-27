# Application data layout

What AlphaAvatar keeps on a machine sits under three roots: the **application home**, the
**application cache** and one **Avatar workspace** per Avatar. Unless configured otherwise, the
cache and the workspaces are inside the application home. This page says how each root is chosen,
what the application home holds, and which directories are created on demand or reserved; the
[Avatar workspace](avatar-workspace.md) and [models and cache](models-cache.md) pages describe the
other two roots.

The Linux package's program files are not under any of them: the installer puts them in
`~/.local/lib/alphaavatar` and the `alphaavatar` command in `~/.local/bin`. Upgrading writes
nothing in the application home, and cleanup never removes the home or its cache
([setup](../cli/setup.md), [upgrade](../cli/upgrade.md), [cleanup](../cli/cleanup.md)).

## Three roots

| Root | Holds | Set with | Default |
| --- | --- | --- | --- |
| Application home | Bundles, profiles, settings and stored credentials; by default the cache and the Avatar workspaces | `application.home`, or `ALPHAAVATAR_HOME` | Per platform, below |
| Application cache | Downloaded model files | `application.cache_root` in YAML | `<application-home>/cache/` |
| Avatar workspace | One Avatar's users, memories, sessions, logs and temporary files | `avatar.workspace_root` in YAML | `<application-home>/avatars/<avatar_key>/` |

Every path must be absolute, without `..`; a relative path or a literal `~` in YAML is rejected.
`application` takes only `home` and `cache_root`. Changing a root moves nothing: point it at the
existing directory, or copy the data there first. Host rejects the former settings
`avatar.work_dir`, `AVATAR_WORK_DIR` and `ALPHAAVATAR_MODEL_CACHE`.

## Choose the application home

The home is, in this order:

1. `application.home` given as a configuration override on the command line, or set in a
   configuration file that a command loads;
2. `ALPHAAVATAR_HOME` from the environment, or from the `.env` file that `ENV_FILE` names when the
   environment's is unset or empty;
3. the service account's platform data directory:

| Platform | Default application home |
| --- | --- |
| Linux | `$XDG_DATA_HOME/alphaavatar/`, or `~/.local/share/alphaavatar/` |
| macOS | `~/Library/Application Support/AlphaAvatar/` |
| Windows | `%LOCALAPPDATA%/AlphaAvatar/`, or `~/AppData/Local/AlphaAvatar/` |

Settings never choose the home. A named bundle belongs to the home that stores it: if the bundle
sets `application.home`, it must name that same home. See
[choosing a configuration](../cli/config.md#choosing-a-configuration).

## What the application home holds

```text
<application-home>/
├── configs/
│   ├── bundles/<name>.yaml        # Startable configurations.
│   └── profiles/<name>.yaml       # Sections that bundles share; a name may have / parts.
├── settings/
│   ├── settings.yaml              # default_bundle and the name of the stored credentials.
│   └── credentials-<id>.env       # Credentials setup stored, readable only by you.
├── cache/                         # The application cache, unless application.cache_root moves it.
│   ├── models/                    # Downloaded model files.
│   ├── downloads/                 # Reserved.
│   ├── providers/                 # Reserved.
│   ├── diagnostics/               # Reserved.
│   └── avatars/                   # Reserved.
└── avatars/
    └── <avatar_key>/              # An Avatar workspace, unless avatar.workspace_root moves it.
```

`<name>`, `<id>` and `<avatar_key>` stand for real names: a bundle or profile name, a random
identifier, and the filesystem-safe form of the Avatar ID.

- **Bundles and profiles** are written by `alphaavatar config init` and `alphaavatar setup`, and
  can be edited by hand; [config](../cli/config.md#bundles-and-profiles) describes them.
- **Settings**: `settings.yaml` names the default bundle and the stored credentials file;
  `config init` and setup write it. A credentials file exists only once you agreed in setup to
  store what you typed; [credentials](../cli/config.md#credentials) says where else a command
  finds them.
- **The cache** keeps model files under `models/`; it can be cleared and downloaded again, unlike
  the rest of the home. [Models and cache](models-cache.md) covers moving, reusing and clearing
  it.
- **Avatar workspaces** hold private data that cannot be downloaded again; see
  [Avatar workspace](avatar-workspace.md).

## Created on demand, and reserved

`start` and `dev` create every directory in the tree above, and the Avatar workspace's own
directories, before Host starts; `config init` and `setup` create what they write. Files appear
only when something writes them: an empty `models/` means no model has been downloaded yet, and an
existing directory is no evidence that a feature has run.

**Reserved** directories are created but not used by this version: `downloads/`, `providers/`,
`diagnostics/` and `avatars/` in the cache. The workspace has its own reserved directories, listed
in its [layout](avatar-workspace.md#what-the-folders-contain). Do not put other files in them.

## Back up

Stop Host first. Keep the home's `configs/` and `settings/` together with the workspaces you
need, and protect the credentials file like any other secret. The cache needs no backup: what it
holds can be downloaded again.
