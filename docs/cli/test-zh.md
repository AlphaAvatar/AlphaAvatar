# `alphaavatar test`

[English](test.md)

**计划中——尚不可用。** `alphaavatar` 没有 `test` 命令。是否提供该命令尚未决定（[Roadmap QA-06](../ROADMAP.md#backlog)）；本页是一份提案，下面的命令无法运行。

提案内容：运行选定的场景和基准测试，衡量某项具体能力的正确性、延迟和可靠性。

```bash
alphaavatar test list                                   # Available suites and requirements
alphaavatar test run multimodal-smoke                   # Bounded end-to-end scenario
alphaavatar test runner semantic --samples 100          # One runner, fixed requests
alphaavatar test stress multimodal --concurrency 8 --duration 120
alphaavatar test runner semantic --samples 100 --format json
```

测试默认使用确定性的 fixture；使用真实的付费服务需要显式启用 live 模式。
