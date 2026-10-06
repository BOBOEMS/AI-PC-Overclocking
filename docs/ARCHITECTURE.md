# Architecture

Why the toolkit is shaped the way it is. Most of the structure exists to make one
guarantee possible: **a run either produces trustworthy evidence, or it is
recorded as incomplete — it never silently becomes a false pass.**

## The core problem

A stress test is a program that is supposed to either finish or fail loudly. In
practice it does neither reliably:

- It **hangs**. The process is alive, the CPU is at 100 %, and no result is ever
  produced. A wall-clock timer in the same process cannot notice, because the
  timer thread is starved or the hang is in a driver.
- The **machine resets**. Nothing in user space survives to write an explanation.
- The **operator walks away**. Nobody notices a 4-hour-old frozen window.

All three produce the same dangerous outcome: an absence of failure that gets
read as success.

## The dead-man switch

The workload is placed in a **Windows Job Object** and killed unless a heartbeat
keeps arriving:

```
   workload starts
        |
        v
   +----------------+   heartbeat < timeout   +------------------+
   | armed          | <---------------------- | external feeder  |
   +----------------+                         +------------------+
        |  heartbeat stops
        v
   +----------------+   terminate job, restore margins, write status
   | tripped        |
   +----------------+
```

The essential detail is **where the heartbeat comes from**. It must be a process
the OS can still schedule when the workload is wedged, and it must be outside the
job being killed. An elevated run therefore cannot supervise itself.

Independent trip conditions, each with its own threshold:

| Trip | Catches |
|---|---|
| heartbeat timeout | hangs, and the operator leaving |
| WHEA error count | machine-check exceptions that do not reset the box |
| CPU temperature | cooling failure or an unsafe configuration |
| DIMM temperature | memory running hot enough to throttle or corrupt |
| sensor staleness | the monitoring path itself dying |
| wall-clock hard timeout | a workload that ignores its own duration |

The temperature trips use a **strike count** (N consecutive samples over the
limit) rather than a single reading. A lone sensor spike would otherwise abort a
healthy run — this is the difference between a watchdog and a nuisance.

## Privilege split

The two halves need different rights, and that shapes everything:

| | unprivileged half | elevated half |
|---|---|---|
| runs as | your session / an AI agent | scheduled task, `HighestAvailable` |
| can touch the SMU | no | yes |
| feeds the heartbeat | **yes** | no |
| reads HWiNFO shared memory | yes | yes |

**Registering the task removes the repeated UAC prompt, not the requirement for
privilege.** Automating the consent dialog would defeat the mechanism Windows
uses to ask; moving the work into a task that was consented to *once*, by a human,
does not.

The elevated surface is deliberately tiny. `schtasks /run` cannot pass arguments,
so the operation is read from `config/co_task_op.json` and validated against an
allow-list. The unprivileged side can choose *which* fixed operation runs; it
cannot supply a command. Each operation has a fixed argument list.

## Evidence pipeline

Everything a run produces lands under `artifacts/`, keyed by session name:

```
artifacts/sessions/<session>/
├── session.json              what was armed, and the token (redacted on archive)
├── events.jsonl              append-only: armed, started, trips, finished
├── status.json               current/last state
├── heartbeat.json            last heartbeat seen
├── sensor_samples.jsonl      one row per poll, all protected temperatures
├── probe_before.log          SMU state before any write
├── probe_after_apply.log     SMU state after the write, read back
├── probe_after.log           SMU state after reset
├── workload.stdout.log       the engine's own output, including Test Speed
└── workload.stderr.log
```

The `probe_*` files are what make a run attributable: they show the hardware's
own report of the margin, not the toolkit's intention.

`src/common/archive_watchdog_session.py` copies a session into
`artifacts/runs/<run>/attempts/`, **redacting the heartbeat token** and gzipping
the sensor samples. Archiving is how a run becomes a durable result rather than
transient state.

## Three kinds of number

A recurring source of error is treating these as interchangeable:

| Kind | Example | Where it comes from |
|---|---|---|
| **declared input** | "I set Curve Optimizer to −15 in BIOS" | a human, a screenshot |
| **observed reading** | `-15,-15,...` from `--get-offsets-terse` | the hardware |
| **verdict** | `VT3: Passed`, peak 85.0 °C, 0 WHEA | the workload and sensors |

A declaration is not evidence. A read-back proves the value reached the hardware,
which is why `probe` exists and why it uses **two independent readers**
(`rycolab` and `ryzen-smu-cli`) — they once disagreed with a stale record.
Unreadable values are recorded as `unconfirmed`, never inferred from history.

## Sensor strategy

Temperatures come from **HWiNFO shared memory** (`Global\HWiNFO_SENS_SM2`). It is
not the only possible source, but it is the only one that stayed reliable:

- `ryzen-smu-cli --stream-system-telemetry` is **block-buffered** when stdout is
  redirected. It stalls for 15–30 s, which is indistinguishable from a dead
  sensor, and it once aborted a healthy run.
- Running **two** such streams concurrently can wedge the SMU power-table
  mailbox and freeze `Tctl` at a constant value — a convincing fake that passes
  casual inspection.

`src/watchdog/sidecar_sensors.py` therefore merges both sources and tracks
freshness **per source**, so a stall is attributed to the right one instead of
being reported as "sensors dead".

## The engine abstraction

`src/rycolab/engine_runner.py` reproduces how `rycolab` invokes its bundled
`y-cruncher` builds: the same config shape, stdin held open, affinity mask
`3 << logical_core`, and a brief suspend per ~10 s. This matters because a
throughput figure is only comparable to another figure produced the same way.

`engine_ab_controller.py` uses it to compare engines directly. That comparison
found AVX-512 (peak 91 °C) against SSE3 (peak 78.75 °C) for the same nominal
workload — a 12 °C difference that is a property of the instruction set's power
density, not of the cooling.

## Pitfalls worth inheriting

Twenty-seven specific traps are catalogued with symptoms, causes and guards in
**[PITFALLS.md](PITFALLS.md)**. They are grouped by when you meet them: while
changing code, while reading sensors, while interpreting measurements, and while
publishing the repository.

The ones that shaped this architecture directly:

1. **Pausing a scheduled task does not kill its children.** The elevated process
   tree keeps running. `Last Result: 1073807364` means "still running". Stop
   workloads through the watchdog, not the Task Scheduler UI.
2. **A `.ps1` file without a BOM is read as ANSI by PowerShell 5.1.** Non-ASCII
   path components get mangled, producing a file-not-found that looks like a
   missing install.
3. **UIPI blocks window messages from medium to high integrity.** Dismissing
   HWiNFO's splash from the unprivileged side silently does nothing; the
   `SendMessage` is dropped with no error.
4. **`$ErrorActionPreference = 'Stop'` turns a native command's stderr into a
   terminating error.** A probe writing a diagnostic to stderr killed an
   otherwise fine run.
5. **`SCHTASKS` cannot pass arguments.** Anything variable must travel in a file,
   and that file needs validating as an allow-list.
6. **Two concurrent SMU telemetry streams freeze `Tctl` at a plausible constant**
   — a fake reading that passes casual inspection.
7. **`Out-File -Append` does not create parent directories, and fails silently.**
   An operation logged `PROBE OK` while writing no evidence at all.
8. **A terminated command can settle as a bare exit 1 with no signal marker.**
   Treat that as an interruption, not a crash, and check the artifact state
   before concluding a run failed.

## Testing philosophy

The repository's rules follow from the architecture:

- **Only clean runs count.** Lost heartbeat, lost sensors, temperature trips and
  permission errors all yield `incomplete`, never `passed`.
- **One variable per round.** A round that changed two settings is recorded as
  unattributable rather than being interpreted.
- **Preflights are not verdicts.** A 60-second preflight validates the plumbing —
  allocation, heartbeat, sensors. It is reported as such and never as evidence of
  stability.
- **Compare like with like.** Throughput depends on engine version, run length
  and thermal state. Numbers are only put side by side when those match, and the
  repository records a measured repeatability figure for each metric so a
  difference can be judged against noise rather than against intuition.
