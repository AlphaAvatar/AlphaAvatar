# Model loading and inference selection

## Startup contract

The CLI validates the agent configuration, then calls `prepare_inference_runners()`.
Each plugin contributes its own required runner classes. The resulting
`ALPHAAVATAR_INFERENCE_PLAN` contains only method identifiers and import paths,
not configuration values or credentials.

The worker reconstructs exactly that plan. A missing plan is an error; an empty
plan is valid. `InferenceRuntime` requires an explicit runner mapping and does
not fall back to `InferenceRunner.registered_runners`.

Plan preparation must precede worker/forkserver creation. This is a startup
snapshot, not live reconfiguration of an already-running worker or forkserver.
Stop and relaunch the CLI after changing the enabled model configuration.

Selected runners initialize before the worker accepts realtime sessions. This
warms configured capabilities before the first turn; it is not a first-request
lazy initialization mechanism. File resolution, downloads and model loading run
inside inference initialization processes, not the realtime event loop.

## Selection rules

- Persona speaker and face runners follow their own processor `enabled` fields.
- Router semantic addressing requires both its enabled processor and configured STT.
  Turn taking follows its own enabled flag and selected model.
- Silero follows `voice.vad.plugin`. Disabling a Router consumer alone does not
  disable an explicitly configured, reusable Foundation VAD service.
- Selected Memory and Persona runtimes keep their storage runner. Storage remains
  a runtime dependency even when individual extraction processors are disabled.
- MCP requires `enabled`, a selected default plugin, and nonempty server settings.
- Character selection uses the current configuration, not a stale character
  environment variable.

## Cache layout

The root is `ALPHAAVATAR_MODEL_CACHE`, defaulting to
`~/.cache/alphaavatar/models`. Paths are resolved during initialization, not when
model metadata modules are imported.

```text
models/
├── voice/vad/silero/v6.2.1/
├── router/addressing/semantic/hub/
├── router/turn_taking/smart_turn/v3.2-cpu/hub/
└── persona/
    ├── speaker/vector/hub/
    ├── speaker/attribute/hub/
    └── face/buffalo_l/v0.7/
        ├── archives/
        └── models/buffalo_l/
```

Hugging Face manages revision snapshots and blob deduplication under each `hub/`.
Old cache layouts are not automatically migrated. Initial startup with the new
layout can download the same pinned weights again.

## Offline startup and integrity

Set `ALPHAAVATAR_MODEL_OFFLINE=1` or `HF_HUB_OFFLINE=1` to prevent model downloads.
Populate this cache with the intended configuration on a connected machine first,
then copy the complete cache including manifests. Missing or invalid files fail
initialization. Offline mode covers these local model resolvers, not remote STT,
LLM, embedding, MCP or other network services.

Semantic addressing, Smart Turn and Silero retain their configured SHA256 values.
Speaker weights retain their exact Hugging Face commit revisions. When available,
the Hugging Face LFS blob filename supplies a content digest; otherwise a local
manifest records the first accepted file's digest.

The upstream `buffalo_l.zip` release has no published SHA256 in its asset metadata.
Its resolver uses the existing v0.7 URL, declared 288621354-byte archive size,
ZIP validation, selected filenames and locally recorded SHA256 values. These
locally recorded hashes detect subsequent corruption; they are trust on first use,
not an independently authenticated upstream digest. Only detection, recognition
and gender/age model files are extracted for the existing allowed modules.

Explicit `SMART_TURN_MODEL_PATH` and `SILERO_VAD_MODEL_PATH` files remain user-owned
overrides. They must be nonempty regular files but are not forced to match the
bundled model digest.

Per-artifact file locks coordinate concurrent initialization. URL downloads use
unique temporary files, validate before replacement and remove temporary files
on failure. Archive extraction uses a staging directory and rejects unsafe,
duplicate or symbolic-link members before installation. The cache must be writable
for lock files and manifests, including during offline initialization.

There is no required `download-files` step. Browser/frontend installation for
Character remains a separate dependency-installation concern; importing its runner
must not run the browser installer.
