# Timeout clock investigation

Investigated experiment 3, attempt 17 / run 22 without launching model attempts or changing stored results.

## Finding

The timing disagreement is consistent with host suspend and mismatched clock domains, not evidence that high reasoning effort was slower. The run timestamps span 668.449 seconds, but the recorded agent duration is 50.473 seconds, a difference of about 618 seconds.

Read-only `pmset -g log` inspection found these events during the run (local time, UTC+05:30):

| Time | Event | Reported sleep interval |
| --- | --- | --- |
| 13:00:25 | Idle Sleep | 490 seconds |
| 13:08:35 | DarkWake | — |
| 13:08:42 | Maintenance Sleep | 133 seconds |
| 13:10:55 | Wake | — |

The run began at 12:59:48.907469 and completed at 13:10:57.356277, shortly after wake. The sleep log is rounded and its two intervals total 623 seconds; it is corroborating evidence, not an exact reconstruction of every clock tick or process scheduling interval.

The local Python monotonic clock reports `mach_absolute_time()`. Installed uvloop is 0.22.1, with libuv 1.48.0 (numeric version 77824). Uvicorn's default auto-loop factory resolves to uvloop in this environment. The runtime enforces its deadline with `asyncio.wait_for`, while the scheduler previously measured phase durations with Python `time.monotonic()`.

Python's macOS clock excludes system sleep; uvloop delegates its clock to libuv, whose Darwin implementation selects sleep-inclusive `mach_continuous_time` when available. Local clock readings also showed different epochs; the diagnosis relies on the source semantics and overlapping sleep events, not subtracting those epochs.

Primary references:

- [Python clock implementation](https://docs.python.org/3/library/time.html#time.monotonic)
- [CPython system-sleep discussion](https://github.com/python/cpython/issues/85475)
- [uvloop 0.22.1 clock implementation](https://github.com/MagicStack/uvloop/blob/v0.22.1/uvloop/loop.pyx)
- [libuv 1.48.0 Darwin clock implementation](https://github.com/libuv/libuv/blob/v1.48.0/src/unix/darwin.c#L52-L65)

## Source correction

Future scheduler setup, agent, and scoring duration measurements use the running event loop's clock, matching asyncio deadlines. This is elapsed phase time, not CPU time. It includes sleep when the selected loop's deadline clock does. It does not prevent host sleep, change timeout policy, or guarantee that callbacks execute while the host sleeps; overdue deadlines can fire after wake.

Regression coverage checks clock delegation and simulates a 668-second agent phase, asserting persisted duration and unchanged scoring/cleanup behavior without waiting or calling a model. This is a deterministic clock-domain check, not a live suspend test.

Verification: all 111 backend tests passed in 23.82 seconds; Ruff checks and formatting checks passed. No frontend files changed.

Original results, raw evidence, and the 50,473 ms historical measurement remain unchanged. The existing source-app backend must restart, or the packaged app must be rebuilt, to use the correction. No application restart, paid rerun, power-setting change, or result rewrite was performed during this investigation.

V2 still does not support a performance ranking. An approved fresh comparison should run with host sleep prevented and retain this batch as historical evidence.
