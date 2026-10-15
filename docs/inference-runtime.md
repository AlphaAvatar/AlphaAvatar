# Inference process ownership

`InferenceRuntime` owns the local Unix-domain socket and independent runner processes.
`InferenceExecutor` is a client; closing it does not close the server or shared runners.
The existing worker still creates the runtime before accepting RTC jobs. This change
hardens that dependency; it does **not** replace LiveKit dispatch, JobContext or its worker.

## Components

```text
runtime/inference/
    bootstrap.py   plugin-selected import plan, unchanged
    runner.py      model/storage execution contract, unchanged
    protocol.py    bounded length-prefixed local messages
    process.py     one serial runner and owned exchanges
    runtime.py     endpoint, client admission and process ownership
    executor.py    bounded local client connections
```

These modules introduce no new distribution, plugin registry, event bus or model client.
One runner remains serial because its model/storage state may require serialization.
Different runners progress independently. Startup remains ordered to avoid introducing
a new simultaneous model-loading memory peak.

## Startup

Call `prepare_inference_runners(config)` before creating worker processes. The existing
bootstrap reconstructs that exact plan. `start()` owns initialization; concurrent callers
share it, and failed or cancelled startup closes all constructed runners, including the
runner whose initialization did not return successfully. An empty plan remains valid.

The socket is bound in a private temporary directory, but does not serve clients until
all runners are initialized. The final endpoint is exported before starting a forkserver,
so subsequently created job processes inherit it. Another runtime cannot overwrite the
process's existing endpoint. The losing runtime removes only its own resources.

Use `spawn` or `forkserver`, not `fork`. The default is `spawn`; the existing Host worker
passes its selected context explicitly. Process launch and joins execute off the event
loop. This remains Unix-domain-socket infrastructure; it is not a Windows/iOS port.

An existing forkserver captures process environment. Reconfiguration or a fresh runtime
under the same long-lived forkserver is not a supported hot-reload mechanism: restart the
worker process after changing the plan, model configuration or endpoint.

## Requests, cancellation and outcomes

A runner owns each admitted request exchange through completion or its deadline. Cancelling
a direct caller after dispatch does not cancel the response reader and leave stale bytes
for another request. That exchange consumes its own response. A locally queued request
can be withdrawn before it dispatches; no new write is automatically retried.

The client drops its connection after cancellation, transport failure or an incomplete
response. A later request uses another connection; it never reuses an abandoned response.
A fully read runner error is different: the channel remains synchronized and may be reused.

Cancellation is not rollback. Once bytes have been submitted to the server, the request
may already be running **or queued on the server**. Closing the client does not promise to
withdraw that accepted work. The runtime still owns it; the cancelled caller does not get
its eventual result. Application tools must preserve their own unknown-outcome semantics
and must not replay state-changing operations to obtain a replacement response.

Deadlines include queue waiting. Expiration before dispatch does not kill another active
request. Expiration, framing failure or owner shutdown during an exchange retires the
process/channel rather than risking reply misassociation. There is no automatic runner
restart or replay. A dead runner makes the runtime unhealthy.

## Bounds

Defaults are constructor options except for the wire-frame limit:

| Boundary | Default |
| --- | --- |
| Initialization deadline per runner | 300 seconds |
| Runner request deadline, including runner queue wait | 30 seconds |
| Server client count, including handshakes | 256 |
| Pending requests per runner | 64 |
| Initial client handshake | 10 seconds |
| Executor method connections | 128 |
| Pending/retiring operations per client method | 64 |
| Executor request deadline, including connection and queue wait | 35 seconds |
| Close/individual process-wait budget | 5 seconds |
| Length-prefixed frame, including operation byte | 64 MiB |
| Method name | 512 UTF-8 bytes |

Oversized frame headers fail before reading/allocating their claimed bodies. Requests
require immutable bytes. Unknown methods, exhausted capacity and malformed messages are
not silently dispatched. Limits bound counts and individual messages; they are **not**
a whole-process RSS guarantee. Large queued messages, model memory and OS buffers still
need deployment-level sizing. Existing workloads that exceed the new frame limit need
an explicit chunking/data-reference design, not an unbounded allocation bypass.

The executor and server have separate deadlines. Applications with longer runner work
must configure both appropriately; increasing just the server timeout is insufficient.
No YAML/profile system or new CLI is introduced here.

## Shutdown

`close()` stops new admission immediately and shares one owned cleanup task. Cancelling
one or several callers does not abandon cleanup; caller cancellation propagates after
the owned task settles. Stopping the listener must not wait for open clients before
closing those clients, which would create a shutdown dependency cycle.

Clients and queued exchanges are stopped, all runner cleanup is attempted, and the owned
socket directory/environment entry is removed. Unrelated environment values are not
removed. Normal runner cleanup has an acknowledgement, including an error reply when
`runner.close()` fails. Peer cleanup still runs, and failures remain observable on repeated
close calls. Failed process owners are retained for diagnostics, not discarded as success.

Processes that cannot exit within their wait budget receive terminate, then kill; joins
run off-loop and process handles are closed only after exit. Forced termination does not
prove model/storage finalization or rollback. Normal shutdown should settle tools and
consumers before shutting down this shared infrastructure.

Acquisition already handed to the OS is owned until it returns. A stuck OS process-launch
call cannot be interrupted safely by cancelling an asyncio waiter. Consequently, the
initialization/close settings do not promise a universal wall-clock bound on arbitrary OS
or third-party cleanup behavior. There is no detached cleanup thread or task left to
produce an unowned process later.

The old private framing names in `runtime.py` are replaced by the internal `protocol.py`
module. Existing public imports for `InferenceRuntime`, `InferenceExecutor`,
`InferenceRunner` and `INFERENCE_ENDPOINT_ENV` are unchanged. Restart the complete worker
and its clients when applying these files; do not mix old and new process modules.

## Verification scope

The delivery's verification record describes actual spawned/forkserver processes, local
IPC, cancellation and failure-injection checks. Fixture runners replace real models and
storage engines. Those checks are not a real LiveKit dispatch, GPU model, database or
whole-application startup qualification. There is also no claim of whole-repository Ruff
or integration-test completion.
