# `alphaavatar test`

[中文](test-zh.md)

**Planned — not available.** `alphaavatar` has no `test` command. Whether to offer one is
undecided ([Roadmap QA-06](../ROADMAP.md#backlog)); this page is a proposal, and the commands
below do not run.

The proposal: run selected scenarios and benchmarks to measure correctness, latency and
reliability of a specific capability.

```bash
alphaavatar test list                                   # Available suites and requirements
alphaavatar test run multimodal-smoke                   # Bounded end-to-end scenario
alphaavatar test runner semantic --samples 100          # One runner, fixed requests
alphaavatar test stress multimodal --concurrency 8 --duration 120
alphaavatar test runner semantic --samples 100 --format json
```

Tests use deterministic fixtures by default; real paid services require explicit live mode.
