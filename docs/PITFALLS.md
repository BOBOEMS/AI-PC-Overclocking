# Pitfalls

Every entry here cost real debugging time. They are grouped by *when you meet
them*, because that is what determines whether you can still do anything about
it. Each one states the symptom first, because the symptom is what you will
actually observe — the cause is rarely the obvious one.

If you are extending this toolkit, read the **Code and tooling** section before
touching anything. If you are interpreting results, read **Measurement and
methodology**.

---

## Code and tooling

### 1. A missing `sys` import, hidden by a bootstrap block

**Symptom.** `NameError: name 'sys' is not defined` at the very first line of a
script, pointing at a line that looks correct.

**Cause.** A refactor inserted `sys.path.insert(...)` into a file that imported
`argparse`, `gzip`, `json`, `pathlib` and `shutil` — but never `sys`. Adding the
call without the import is easy to miss because the block *looks* like
boilerplate.

**Guard.** Any inserted bootstrap must also assert its own prerequisites. The
migration scripts that did this refactor add `import sys` and
`from pathlib import Path` when missing (see `tools/migrations/`).

### 2. Bootstrap placed before the imports it depends on

**Symptom.** Every rewritten script fails immediately with a `NameError` for
`sys` or `Path` — *even though the import exists further down the file*.

**Cause.** The bootstrap was inserted directly after
`from __future__ import annotations`, which sits **above** `import sys` and
`from pathlib import Path`. Python executes top to bottom, so the bootstrap ran
before its own dependencies were bound.

**Guard.** Order is: docstring → `__future__` → stdlib imports → bootstrap →
local imports. `tools/migrations/bootstrap_order.py` enforces it idempotently.

**Why it matters here.** The scripts *looked* neatly reorganised and were all
broken. A layout can be verified by reading; execution cannot.

### 3. `Out-File -Append` does not create parent directories

**Symptom.** An operation logs `PROBE OK` and exits 0, but the evidence file it
claims to have written does not exist anywhere.

**Cause.** The target directory had not been created. `Out-File -Append` fails
silently in that situation when the error preference is not `Stop`.

**The dangerous part** is not the missing file — it is the **log claiming
success**. A missing artifact is obvious; a false success message is not.

**Guard.** `Initialize-ArtifactDirs` is called once at the top of
`task_launch.ps1`, before any operation can write. If you add an operation, do
not assume its output directory exists.

### 4. A parameter that rejects the empty string

**Symptom.** `Cannot bind argument to parameter 'Default' because it is an empty
string`, thrown from inside a path-resolution helper.

**Cause.** `[Parameter(Mandatory)][string]$Default` rejects `''` unless the
parameter is marked `[AllowEmptyString()]`. "No default, the caller decides" is a
legitimate value that the signature forbade.

**Guard.** Empty is allowed and means "no default". Check the caller, not the
signature, for whether a value was produced.

### 5. Environment variables do not reach an already-running process

**Symptom.** You set a variable, verify it in the registry, and the tool still
resolves the old default. A newly spawned child does not see it either.

**Cause.** A child inherits its parent's **environment block**. Setting a user
variable writes the registry and broadcasts a change notification, but a process
that is already running does not rebuild its block. A scheduled task started from
such a session inherits the stale one.

**Guard.** Configuration is read from a **file** on every launch
(`%APPDATA%\overclock-toolkit\paths.json`), with environment variables as an
override for shells. Do not rely on `setx` to affect a running system.

### 6. A scheduled task stores an absolute script path

**Symptom.** After moving or renaming the repository, every operation fails with
`Last Result: 1` and no log at all.

**Cause.** `schtasks /create` records the absolute path to the launcher.
Moving the tree does not update it, and the failure happens before the script
runs, so the script cannot log it.

**Guard.** Re-run `src/elevated/setup_uac_free_task.ps1` after any move. Verify
with:

```powershell
schtasks /query /tn optimize-co-elevated /xml | Select-String 'Arguments'
```

### 7. A search that ignores the configured value

**Symptom.** `ABORT: <tool> not found`, even though the tool's path is set
correctly in the configuration file.

**Cause.** The discovery code searched a couple of assumed roots and never
consulted the resolved setting. It worked for installs under those roots and
failed for everyone else.

**Guard.** Resolution order is: configured value → search → abort with a message
naming **both** what was configured and where the search looked. An abort message
that omits the configured path sends the reader looking in the wrong place.

### 8. A bare `python` is not a Python

**Symptom.** The elevated task exits immediately. The resolved interpreter is the
literal string `python.exe`.

**Cause.** A scheduled task does not inherit an interactive `PATH`. Falling back
to `python.exe` looks harmless and produces an unrunnable command.

**Guard.** Probe real locations (`%LOCALAPPDATA%\Programs\Python`,
`C:\Python3xx`, `PATH`, the `py` launcher) and treat "no interpreter" as an error
worth reporting, not as a default.

### 9. UTF-8 without a BOM read as ANSI

**Symptom.** A path containing non-ASCII characters is mangled — `综合检测`
becomes `缁煎悎妫€娴媆` — and the tool reports "file not found" for a file that
plainly exists.

**Cause.** Windows PowerShell 5.1 decodes a `.ps1` file without a UTF-8 BOM using
the system ANSI code page. The mangling happens while parsing the script, so the
path is already wrong before any code runs.

**Guard.** All `.ps1` files in `src/elevated/` are saved **with** a BOM. When
editing them, preserve it. Note that a "file not found" for a non-ASCII path is
this bug until proven otherwise.

### 10. `$ErrorActionPreference = 'Stop'` promotes stderr to fatal

**Symptom.** A working operation dies because a probe wrote something to stderr.
The task reports `Last Result: 1`.

**Cause.** With `Stop`, a native command's stderr output becomes a terminating
error in PowerShell. A probe writing a diagnostic to stderr is not a failure.

**Guard.** Either capture stderr explicitly (`2>$null`) and check the exit code,
or keep the preference at `Continue` and log deliberately — which is what
`task_launch.ps1` does, plus a global `trap` that writes a crash log with a stack
trace.

### 11. `schtasks /run` cannot pass arguments

**Symptom.** You want to trigger an operation with parameters and there is no way
to express them.

**Cause.** By design. The trigger takes no arguments.

**Consequence, and why it is a feature.** Anything variable must travel in a
file, and the file's contents must be **validated against an allow-list**. That
is what keeps the elevated task from becoming an arbitrary-command runner: the
unprivileged side chooses *which* fixed operation runs, never what command.

### 12. Pausing a scheduled task does not stop its children

**Symptom.** You disable the task, and the workload keeps running. `Last Result:
1073807364` means "still running", not "stopped".

**Cause.** The task's child processes are not part of the task's lifecycle in the
way you would expect. Disabling prevents *new* runs.

**Guard.** Stop workloads through the watchdog (`stop --session <s> --token
<t>`). `taskkill` on the elevated tree is frequently denied — and for good
reason, that tree is not yours to kill from an unprivileged session.

---

## Sensors and telemetry

### 13. Block-buffered stdout looks like a dead sensor

**Symptom.** A telemetry source stops updating for 15–30 seconds, the watchdog
declares it stale, and a healthy run is aborted.

**Cause.** `ryzen-smu-cli --stream-system-telemetry` block-buffers its stdout
when redirected. It is not dead; it is holding data in a buffer.

**Guard.** `src/watchdog/sidecar_sensors.py` merges sources and tracks
**per-source** freshness, so a stall is attributed correctly. The primary
temperature source is HWiNFO shared memory, which does not buffer.

### 14. Two concurrent SMU streams wedge the power-table mailbox

**Symptom.** `Tctl` freezes at a constant value — for example 71.38 °C — and
stays there. The watchdog reports the source stale after 30 s.

**Cause.** Two simultaneous `ryzen-smu-cli` PM-table streams contending for the
SMU mailbox.

**The dangerous part** is that a frozen plausible value passes casual
inspection. This is a fake, not a reading.

**Guard.** Never run more than one SMU telemetry consumer. This is also a reason
to prefer HWiNFO shared memory, and a reason **not** to stack two monitoring
systems during a measurement run.

### 15. UIPI blocks messages from a non-elevated process

**Symptom.** A `SendMessage`/`BM_CLICK` to dismiss a splash window returns
without error and does nothing.

**Cause.** Windows User Interface Privilege Isolation blocks window messages from
a medium-integrity process to a high-integrity window. The call is dropped
silently.

**Guard.** HWiNFO's splash is dismissed by the **elevated** half
(`task_launch.ps1`, `op hwinfo`, class `#32770`, control id 1, retried every 3 s).
Never try to automate a consent dialog from the unprivileged side — that is the
mechanism working as intended.

### 16. Sensor-based protection can kill a session you care about

**Symptom.** During an interactive session the workload is killed and the window
disappears.

**Cause.** The watchdog's sensor source stalled briefly, or a threshold was
crossed during a legitimate load. Sensor-based trips do not know the difference
between a fault and a game.

**Guard.** For interactive sessions, run the watchdog **without** sensor
arguments. It still catches hangs through the heartbeat, with zero hardware
contention and no chance of a false trip. Thermal protection is worth less when a
human is watching than the risk of killing their session.

---

## Measurement and methodology

These are not bugs. They are ways to produce a confident, wrong conclusion.

### 17. Sample once, conclude wrongly

**Symptom.** A difference is "clearly real", and later vanishes.

**Cause.** Single samples. During one session two separate conclusions had to be
retracted once more samples arrived — a claimed 1.5 % regression that turned out
to be scatter, and a claimed 14 % difference that was real but caused by the
wrong subsystem.

**Guard.** Establish the metric's repeatability **first**, then judge a
difference against it. Report the sample count alongside every number, and prefer
a comparison whose *within-group* spread is smaller than the effect being claimed.

### 18. Thermal drift mistaken for a configuration effect

**Symptom.** Back-to-back runs drift monotonically (for example copy bandwidth
60.71 → 58.27 → 58.30 GB/s), and the drift is read as a result.

**Cause.** The machine was heating up. The first run is fast because it starts
cool, not because its settings are better.

**Guard.** Cool to a fixed temperature before **every** sample. With that
protocol the same measurement tightened from a 4.2 % spread to 1.5 %. Report
each sample's starting temperature.

### 19. A plausible mechanism is not evidence

**Symptom.** A tidy explanation survives several rounds of reasoning and turns
out to be wrong.

**Cause.** Reasoning from what *should* happen. Two examples from this project:
"a heavier-looking all-core test must run hotter" (it ran cooler — the power
limit lowers per-core voltage), and "a higher-throughput stress test is a weaker
test" (the opposite was true for this workload).

**Guard.** Write the prediction down **before** the measurement, including what
result would falsify it. When a number contradicts the mechanism, record the
contradiction rather than the mechanism.

### 20. Values that cannot be read get inferred from history

**Symptom.** A configuration value is recorded as fact although nothing was read
back.

**Cause.** Convenience. History is a tempting substitute for a read-back.

**Guard.** Keep three kinds of number apart: **declared input** (what a human
typed), **observed reading** (what the hardware reports), and **verdict** (what
the load did). Unreadable values are `unconfirmed`. Use two independent readers
where possible — `rycolab` and `ryzen-smu-cli` once disagreed with a stale record.

### 21. Throughput depends on more than the thing being tested

**Symptom.** A 14 % throughput drop is blamed on the CPU when the CPU was
identical.

**Cause.** A memory setting was changed at the same time. Core clocks were
byte-for-byte the same (5140 vs 5135 MHz, identical VID), which located the cause
in the memory subsystem in a single step.

**Guard.** When throughput moves, first compare what the *CPU* was doing. If
clocks and voltages match, stop looking at the CPU. Also pin the engine version:
`y-cruncher` 0.8.5 and 0.8.7 report differently and cannot be compared.

### 22. Changing several settings at once destroys attribution

**Symptom.** A result cannot be explained, and no follow-up can rescue it.

**Cause.** Several BIOS settings changed between the two measurements, and the
order of changes was not recorded. The correct output of such a round is
"unattributable", not a best guess.

**Guard.** One explainable variable per round. If a round turns out to have
changed several things, say so in the conclusion and leave the cause open.

### 23. Run-to-run scatter is a property of the metric, not of the settings

A related pair of numbers from this project, useful as a sanity check:

| Metric | Within-configuration spread | Minimum detectable difference |
|---|---|---|
| VT3 first-iteration throughput | ~0.5 % | > 0.5 % |
| copy bandwidth | ~1.5 % | > 1.5 % |
| scale bandwidth | ~2.1 % | > 2.1 % |
| triad bandwidth | ~3.5 % | > 3.5 % |
| dependent-load latency (page-strided) | ~4.1 % | > 4.1 % |

A difference smaller than the number in the right-hand column is not a finding.
Measure your own — these are specific to one machine and one load.

### 24. Only the first iteration of a y-cruncher test is comparable

`y-cruncher` prints `Test Speed` once per completed test, after `Iteration: 0`.
That first pass takes 3–5 seconds and completes long before a 30-minute run
finishes, so a 180-second run and a 30-minute run report **the same measurement**.
That is why short runs are legitimate for throughput comparison — and why a
figure must not be compared across different engine versions, memory
configurations or thermal states.

---

## Repository hygiene

### 25. Generated output becomes the repository

**Symptom.** A clone is hundreds of megabytes, `git status` is full of `jsonl`
files after every run, and the actual source is hard to find.

**Cause.** Logs and session evidence were tracked alongside source.

**Guard.** One rule: if the toolkit produced it, it lives under `artifacts/` and
is ignored. `artifacts/` is deliberately **not** a git submodule and never
tracked. Result documents worth keeping are the exception, and are moved
under `artifacts/runs/` only when they are the record of a completed experiment.

### 26. Machine-specific paths in source

**Symptom.** Someone else clones the repository and nothing runs.

**Cause.** Absolute paths belonging to one machine — a checkout location, a user
profile, a download folder — written directly into scripts.

**Guard.** All paths resolve through `src/common/paths.py` and
`src/elevated/paths.ps1`, from a user config file that is never committed. Run
both self-tests (`pwsh -File src/elevated/selftest_paths.ps1` and
`python src/common/paths.py`) after any change; they must agree on the session
directory and report `0` missing.

### 27. Source that was never tracked at all

**Symptom.** The repository looks complete but a clone cannot run, because some
of the tools were never added to git.

**Cause.** The working tree had 39 source files while only 5 were tracked — the
rest had simply never been staged, and nothing reported it.

**Guard.** Compare `git ls-files` against the working tree before publishing:

```powershell
git status --porcelain --ignored | Select-String '^\?\?'
```

Anything unexpected there is either a missing file or a missing `.gitignore` rule.
