# Virtual Character Plugin for AlphaAvatar

A modular virtual-character middleware that brings advanced real-time avatar rendering into the AlphaAvatar agent ecosystem. This plugin enables any AlphaAvatar-driven AI agent to seamlessly control high-fidelity virtual characters—handling lip-sync, facial expressions, emotional states, and synchronized video generation.

## Installation

```bash
pip install alpha-avatar-plugins-character
```

---

## Supported Open-Source Virtual Character Frameworks

### Default: AIRI [Github](https://github.com/moeru-ai/airi)

High-fidelity Live2D/VRM real-time renderer, enabling lip-sync, emotion control, and avatar video generation.

```shell
curl https://get.volta.sh | bash

volta install node
volta install pnpm

alphaavatar-airi-install
```

> Note: AIRI performs a Chromium preflight check on startup.
> If Chromium cannot start in headless mode, actionable system dependency
> installation hints will be printed based on your Linux distribution.
