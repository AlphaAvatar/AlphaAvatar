# AlphaAvatar Virtual Character Plugin

AIRI presentation uses the native Character lifecycle. It does not receive an
AgentSession, generate answers, synthesize speech, or publish a second audio track.
The renderer consumes the Agent's existing RTC audio and publishes its canvas video.

## Ownership

Agents exposes `VirtualCharacterSession`, `CharacterTransport`, and the immutable
`CharacterConnection` contract. Host supplies `LiveKitCharacterTransport`, which
owns room callbacks and mints a short-lived, room-scoped renderer token. The token's
participant identity is unique for each execution. Master service credentials are
not included in the connection object supplied to the renderer.

The AIRI plugin owns its Playwright driver, browser, context and page, plus its
injected transport lifecycle. HostExecution owns the Character session. No AIRI
inference runner, loop thread, untracked browser task or shared fixed-port server
is created by the realtime Host.

```text
HostExecution start:
    Character READY + video publication -> RTC outputs -> Engine -> RTC inputs

HostExecution stop:
    RTC inputs -> Engine/tool settlement -> RTC outputs -> Character -> AvatarRuntime
```

Starting Character before the audio output matters for the pinned frontend: it
registers its audio subscription handler before sending READY. Publishing the Agent
track first could lose that subscription event. Character does not replace the
existing OutputRuntime, Router synthesis, transcript or playback-feedback paths.

Host excludes the exact renderer participant from audio and video perception.
Other participants remain eligible. An avatar video is output, not user evidence.

## Frontend preparation

A trusted AIRI frontend must be served separately. This intentionally replaces the
old inference runner's automatic `pnpm dev` startup. One frontend service can serve
multiple isolated execution browsers. The Host does not stop that shared service.

The repository retains the `third_party/airi` gitlink. Initialize it from the
AlphaAvatar repository root, install the Node/pnpm versions required by that
checkout, then prepare its dependencies and the matching Playwright Chromium:

```bash
git submodule update --init --recursive
alphaavatar-airi-install
cd avatar-plugins/perception/avatar-plugins-character/third_party/airi
pnpm --filter @proj-airi/stage-web dev --host 127.0.0.1 --port 5173 --strictPort
```

`alphaavatar-airi-install` uses `pnpm install --frozen-lockfile`, with no npm
fallback for this pnpm workspace, and runs Playwright's Chromium installer. It is
an explicit setup command, not work performed during plugin import or live calls.
Set `AIRI_REPO_DIR` only when using a separately checked-out frontend. Browser OS
libraries and an appropriate runtime user still need to be provided by deployment.
A development server is not a production hosting recommendation; production must
serve the trusted build with routing appropriate for `/livekit-avatar`.

## Configuration

Enable Character explicitly in an otherwise complete native configuration:

```yaml
character:
  plugin: airi
  init_config:
    frontend_url: http://127.0.0.1:5173/livekit-avatar
    video_width: 1280
    video_height: 720
    startup_timeout: 60.0
    close_timeout: 10.0
    chromium_sandbox: true
```

Width/height configure the browser viewport; actual encoded video resolution and
frame rate belong to the frontend. The old ignored `video_fps`, `audio_sample_rate`
and `audio_channels` options are removed and rejected. Unknown keys are rejected.
The renderer consumes the existing Agent audio; it has no separate PCM settings.

Chromium sandboxing is enabled by default. Use a deployment user/container setup
that supports it; no automatic `--no-sandbox` fallback is performed. An optional
`executable_path` selects an explicitly managed Chromium. Prefer the browser
matching the installed Playwright version. The supplied examples remain unchanged
with `character.plugin: null`, including the AIRI-named voice-persona examples.

## Readiness, failure and cleanup

A READY message is accepted only from the exact token-bound participant, on the
renderer status topic. It is insufficient without that participant's video
publication. Messages from another participant, invalid JSON and oversized data
cannot make the session ready. Missing READY/video is a startup failure, not a
warning followed by success. The transport also rejects observed renderer audio
publication instead of accepting a second playback path.

The browser/page and transport are monitored after startup. A crash, renderer
participant loss or video unpublication is reported to LiveKitConnection, which
closes the current execution. There is no silent renderer retry or duplicate join.
Publication readiness is not proof of decoded frame quality, continuing frame
liveness, or audio/video synchronization at a viewer.

Driver and browser acquisition have independent task ownership. Cancellation
cannot discard a late-created handle. Cleanup joins these acquisitions, closes
context/browser/driver, removes transport callbacks and reports failures. Repeated
callers share cleanup. `close_timeout` applies to each resource-close operation,
not an absolute total shutdown deadline; local driver acquisition must settle
before release, and cleanup can outlast the presentation startup deadline.

## Credential boundary

The initial HTTP navigation URL contains no token. A scoped initialization script
makes connection parameters available to the pinned frontend's existing query
reader through browser-local history; the query is removed after readiness.
Requests use a token-free Referer, and browser console/page-error/request logging
is not forwarded to application logs. Session errors expose only safe stage/type
information. This is an adaptation to the pinned frontend, not a new frontend
credential protocol, and the configured frontend remains trusted code.

Remote frontend and LiveKit connections require TLS; loopback development is
allowed. Configured frontend URLs cannot contain credentials, query or fragment.
Redirecting away from the configured origin/route is rejected. Browser contexts
are isolated, service workers are blocked and automatic downloads are disabled.
No TLS verification is disabled.

The gitlink and frontend code are unchanged by this block. Real AIRI build,
LiveKit server/client, canvas video and listening/synchronization tests remain
required. SDK worker hosting is still separate work; this is not a claim of
complete `livekit.agents` removal from the workspace.
