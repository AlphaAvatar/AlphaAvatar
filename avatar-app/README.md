# AlphaAvatar App

This directory is reserved for the AlphaAvatar client application. It currently contains
only this README; no installable app, mobile runtime or configuration UI is delivered here.

## 📦 Package structure

```text
avatar-app/
└── README.md            # Current scope and package boundary.
```

## Boundary

The server command, configuration loading and application lifecycle belong to
[Avatar Host](../avatar-host/README.md). App is not required to install or run Host.
Future app integration should use the same application configuration and lifecycle
contracts rather than introduce a second backend startup implementation.
