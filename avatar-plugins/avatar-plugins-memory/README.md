# Memory Plugin for AlphaAvatar

Support for storing and managing conversational memory within Avatar, with a unified interface to open-source memory frameworks.
This plugin simplifies memory management so developers don’t need to worry about storage limits, or backend details.

## Features

* **Global Memory (Avatar-wide):** Retrieval and updates of cross-user, Avatar-level memories. This includes memories derived from automatically identified users as well as memories created through the Avatar’s interactions with external tools and the environment.
* **Real-time Context Updates:** Memories are written and refreshed on the fly based on the current dialogue context.

## Installation

```bash
pip install alpha-avatar-plugins-memory[mem0]
```

---

## Supported Open-Source Memory Frameworks

| Framework | Description                                                                                   | Docs                                                             |
| --------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| **mem0**  | Lightweight memory framework with APIs for creating, searching, and updating long-term memory | [https://github.com/mem0ai/mem0](https://github.com/mem0ai/mem0) |

> More frameworks (e.g., xxx) will be added soon.
