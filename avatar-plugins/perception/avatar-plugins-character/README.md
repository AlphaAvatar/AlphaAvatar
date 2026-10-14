# AlphaAvatar Virtual Character Plugin

The Character package contains virtual-character integration code, including the AIRI submodule. It is retained while transport/lifecycle integration is migrated.

## Native Host status

**The current native Engine/Host does not support the SDK-dependent Character adapters.** Their interfaces still require an AgentSession; native Host explicitly rejects `character.plugin` when it is enabled. It does not create a hidden SDK generator or silently pretend animation is connected.

```yaml
character:
  plugin: null
  init_config: {}
```

The `pipeline_openai_airi.yaml` and `pipeline_voiceai_airi.yaml` examples retain Hiyori-style persona and voice, not animated AIRI transport. Audio delivery remains available through Router and RTC independently of Character.

Native lip-sync, character presentation and any new transport contract require a separate implementation/validation step. Installing a renderer does not complete that integration.

## Package installation

```bash
pip install alpha-avatar-plugins-character
```

## AIRI development setup

The retained renderer integration uses [AIRI](https://github.com/moeru-ai/airi). The existing setup commands are for renderer development, not a supported native Host launch recipe:

```shell
curl https://get.volta.sh | bash
volta install node
volta install pnpm
alphaavatar-airi-install
```

AIRI performs a Chromium preflight at startup and reports dependency hints when headless Chromium cannot start. Preserve the submodule identity and gitlink revision when moving its checkout. Do not delete the Character package or submodule merely because native runtime wiring is pending.
