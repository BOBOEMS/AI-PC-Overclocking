# External dependencies

This toolkit is a **supervisor and recorder**, not a stress tester. It drives
third-party programs and reads third-party sensors. None of them are vendored
here, so you install them yourself and point the toolkit at them via
[docs/CONFIGURATION.md](CONFIGURATION.md).

> **Licences differ, and not all are permissive.** The toolkit's own code is MIT,
> but it *calls* the programs below. If you redistribute a bundle that includes
> any of them, you are bound by their terms, not this repository's. `rycolab` in
> particular is GPL-3.0.

## Summary

| Tool | Role | Config key | Licence |
|---|---|---|---|
| [rycolab](#rycolab) | Curve Optimizer sweep harness | `rycolabExe` | GPL-3.0 |
| [ryzen-smu-cli](#ryzen-smu-cli) | direct SMU access | `ryzenSmuCli` | GPL-3.0 |
| [y-cruncher](#y-cruncher) | the stress-test engine | `ycruncherExe` | freeware, not open source |
| [HWiNFO64](#hwinfo64) | sensor source (shared memory) | `hwinfoExe` | free for personal use |
| [Python](#python) | runs the non-elevated half | `pythonExe` | PSF licence |
| [PowerShell 7](#powershell-7) | runs the elevated half | — | MIT |
| [gcc](#gcc) | builds `memprobe` (optional) | — | GPL |

Optional / mentioned only in the methodology docs:

| Tool | Role | Licence |
|---|---|---|
| [ZenTimings](https://zentimings.com/) | read back live DRAM timings | freeware |
| [TestMem5](https://www.overclock.net/threads/memory-testing-with-testmem5-tm5-v0-12-1.1586541/) | alternative memory stress | freeware |
| [Cinebench R23](https://www.maxon.net/en/downloads/cinebench-r23-downloads) | CPU benchmark | free for non-commercial |
| [FurMark](https://geeks3d.com/furmark/) | GPU stress | freeware |

---

## rycolab

**What the toolkit uses it for.** Everything Curve Optimizer: sweeping per-core
negative margins, verifying them against hardware, and — critically — reporting
the *hardware register value* per core. The toolkit reads those numbers rather
than trusting its own records, because a stale record once disagreed with the
silicon.

- **Source:** <https://github.com/aJustDev/rycolab>
- **Licence:** GPL-3.0
- **Version this toolkit was developed against:** commit
  `b9fd4d589ce86bcc4dff2d20f5e88180be0d5a3d` (v0.3.0, `main`)
- **Install:** the repository's `install.ps1`. It installs to
  `%LOCALAPPDATA%\rycolab` by default; set `RYCOLAB_APPDATA` if you put it
  elsewhere.
- **Commands used:** `dev probe`, `dev apply`, `dev reset`, `dev sweep`.

It is a .NET application, which is why a .NET SDK may be needed to build it.
`rycolab dev probe` requires administrative rights — that is the reason this
toolkit has an elevated half at all.

**Why the version matters.** `rycolab` bundles its own `y-cruncher` engine
builds under `tools/y-cruncher/Binaries`, named like `24-ZN5 ~ Komari.exe`
(Zen 5, AVX-512) and `04-P4P.exe` (SSE3). Their *N* is a y-cruncher version. If
you change `rycolab` versions, the engines change with it, and throughput numbers
stop being comparable with older runs.

## ryzen-smu-cli

**What the toolkit uses it for.** Reading and writing SMU state directly:
per-core Curve Optimizer margins (`--get-offsets-terse`), FMax, PBO scalar. It
serves as an **independent second reader** — when it and `rycolab` agree on all
eight cores, the read-back is trustworthy.

- **Source:** <https://github.com/sp00n/ryzen-smu-cli>
- **Licence:** GPL-3.0
- **Install:** build from source, or take a release binary. Point `ryzenSmuCli`
  at the `.exe`.
- **Commands used:** `--get-offsets-terse`, `--get-fmax`, `--get-pbo-scalar`,
  `--offset`, `--stream-system-telemetry`.

**Two operational notes that cost real time to discover:**

1. It **must run elevated** to touch the SMU. Calls that appear to fail silently
   are usually a permissions problem, not a hardware one.
2. Its `--stream-system-telemetry` output is **block-buffered** when stdout is
   redirected, so it can stall for 15–30 seconds. That looks exactly like a
   failed sensor, and once aborted a healthy run. The toolkit's sidecar reads
   HWiNFO shared memory for this reason.

Also: do not run two `--stream-system-telemetry` streams at once. Doing so can
wedge the SMU power-table mailbox and freeze `Tctl` at a constant value, which is
a convincing-looking fake that will pass any sanity check.

## y-cruncher

**What the toolkit uses it for.** The actual stress load. `VT3` (an AVX-512
integer transform) is the acceptance test; `FFT` is used for screening.

- **Official site:** <https://www.numberworld.org/y-cruncher/>
- **Version list:** <https://www.numberworld.org/y-cruncher/versions.html>
- **Licence:** freeware; **not** open source. Check the site's terms before
  redistributing.
- **Version this toolkit pins:** **0.8.5 build 9543**.

**Why the version is pinned.** `0.8.7` reports throughput differently and changes
the engine selection, so a before/after comparison that mixes versions is
meaningless. The result documents in this repository all come from 0.8.5.

**Reading its output.** It prints one `Test Speed: N * 10^09 bits / sec` line per
completed test, after `Iteration: 0`. That first-iteration figure takes only
3–5 seconds and is **independent of the overall run length**, which is why a
180-second run and a 30-minute run report comparable numbers. The toolkit's
analysis scripts rely on this.

## HWiNFO64

**What the toolkit uses it for.** Temperatures — CPU `Tctl/Tdie`, `CCD1`, DIMM
`SPD Hub`, motherboard `MOS` — read from its shared memory, which is the only
stable source available. The toolkit also starts it and dismisses its splash
window from the elevated side.

- **Official site:** <https://www.hwinfo.com/>
- **Licence:** free for personal use; the Pro edition is paid. Review the terms.
- **Required setting:** *Shared Memory Support* must be ON.

Two settings make unattended use possible. In `HWiNFO64.INI`:

```ini
SensorsOnly=1
SensorsSM=1
```

The splash window cannot be dismissed from a non-elevated process, because
Windows UIPI blocks window messages from medium to high integrity. An attempt to
`SendMessage` it from the unprivileged side is silently dropped. The click is
therefore performed by the elevated half.

## Python

**What the toolkit uses it for.** The non-elevated half: watchdog, controllers,
sensor plumbing, analysis.

- **Official site:** <https://www.python.org/>
- **Licence:** PSF licence.
- **Version tested:** 3.12.
- **Dependencies:** **standard library only.** Nothing to `pip install`, which is
  deliberate — the tools must run on a machine where installing packages is not
  desirable or possible.

Set `pythonExe` explicitly. A scheduled task does not inherit an interactive
`PATH`, so a bare `python` may resolve to something unrunnable (this happened
during development: it resolved to the literal string `python.exe`).

## PowerShell 7

**What the toolkit uses it for.** The elevated half — `task_launch.ps1` and
friends. Windows PowerShell 5.1 works, and `setup_uac_free_task.ps1` can register
the task to use it, but PS7 is preferred.

- **Official site:** <https://github.com/PowerShell/PowerShell>
- **Licence:** MIT.
- **Version tested:** 7.6.6.

**Encoding pitfall.** PowerShell 5.1 reads a `.ps1` file without a UTF-8 BOM as
ANSI, which mangles non-ASCII path components and produces a "file not found"
that looks like a missing install. All `.ps1` files in `src/elevated/` are
therefore saved **with** a BOM.

## gcc

**What the toolkit uses it for.** Building `src/bench/memprobe.c` — a small
memory bandwidth and dependent-load latency probe.

- **Official site:** <https://gcc.gnu.org/>
- **Windows builds:** <https://www.mingw-w64.org/>
- **Licence:** GPL (the compiled binary inherits distribution obligations; the
  toolkit does not redistribute it).
- **Build:** `gcc -O2 -o artifacts/build/memprobe.exe src/bench/memprobe.c`
- Optional: only the memory-probe workflow needs it.

---

## What is deliberately not a dependency

- **No package manager, no virtualenv, no `requirements.txt`.** The Python half
  is standard library only.
- **No vendored binaries.** `artifacts/` is ignored, so no `.exe` is published.
  Binaries would tie the repository to one compiler and one machine.
- **No auto-downloader.** Tools are installed by you, from their official
  sources, so you see and accept each licence yourself.
