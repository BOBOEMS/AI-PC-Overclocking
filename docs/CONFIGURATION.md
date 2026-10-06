# Configuration

Every machine-specific value lives in **one place per language**, and neither has
a hardcoded path:

| Half | File | Defines |
|---|---|---|
| Python (unprivileged) | `src/common/paths.py` | artifacts, tools, interpreter, task name |
| PowerShell (elevated) | `src/elevated/paths.ps1` | the same values, for the launcher |

They are kept deliberately in sync, and **must agree on the session directory** —
if they disagree, the watchdog looks in one directory while the controller arms a
session in another, and every run reports "session not found".

## Resolution order

For every setting:

```
1. environment variable           highest priority
2. user config file
3. built-in default               lowest priority
```

If a value resolves to a path that exists, both `selftest_paths.ps1` and
`paths.py` mark it `[ok]`. Anything `[MISSING]` is what you need to fix.

## Where to put your values

### Option A — user config file (recommended)

Outside the repository, so it can never be committed by accident:

```
%APPDATA%\overclock-toolkit\paths.json
```

```jsonc
{
  // Paths use doubled backslashes in JSON.
  "pythonExe":    "C:\\Python312\\python.exe",
  "ryzenSmuCli":  "C:\\Tools\\ryzen-smu-cli\\ryzen-smu-cli.exe",
  "ycruncherExe": "C:\\Tools\\y-cruncher\\y-cruncher.exe",
  "ycruncherDir": "C:\\Tools\\y-cruncher",
  "hwinfoExe":    "C:\\Tools\\HWiNFO\\HWiNFO64.exe",
  "rycolabExe":   "C:\\Users\\you\\AppData\\Local\\rycolab\\bin\\rycolab.exe"
}
```

### Option B — checkout-local override

`config/paths.local.json`, same keys. Useful for testing, but **gitignored**; do
not commit it.

### Option C — environment variables

Same names as the table below. Convenient in a shell, but note:

> **A user-scope environment variable does not reach an already-running
> process.** A new child inherits its *parent's* environment block, so a
> scheduled task started from an existing session may never see a variable you
> just set with `setx` or `[Environment]::SetEnvironmentVariable`. This is why a
> config file is the recommended option — it is read fresh on every launch.

## Settings reference

Environment variable → config key → default.

### Layout

| Env var | Config key | Default | Meaning |
|---|---|---|---|
| `OVERCLOCK_ARTIFACT_ROOT` | `artifactRoot` | `<repo>/artifacts` | root for all generated output |

Subdirectories are derived and not separately configurable: `sessions/`, `runs/`,
`task_logs/`, `build/`.

### Interpreter

| Env var | Config key | Default | Meaning |
|---|---|---|---|
| `OVERCLOCK_PYTHON` | `pythonExe` | auto-detected | Python used by the elevated half |

Auto-detection probes `%LOCALAPPDATA%\Programs\Python`, `C:\Python312` / `311` /
`310`, then `PATH`, then the `py` launcher. Set it explicitly if you have several
Pythons; a scheduled task cannot rely on `PATH`.

### Third-party tools

| Env var | Config key | Default | Tool |
|---|---|---|---|
| `OVERCLOCK_TOOLS_ROOT` | `toolsRoot` | `C:\Tools` | base for the defaults below |
| `RYCOLAB_APPDATA` | `rycolabAppData` | `%LOCALAPPDATA%\rycolab` | rycolab install dir |
| `RYCOLAB_EXE` | `rycolabExe` | `<rycolabAppData>\bin\rycolab.exe` | rycolab binary |
| `RYCOLAB_BINARIES` | `rycolabBinaries` | `<rycolabAppData>\tools\y-cruncher\Binaries` | bundled engines |
| `RYZEN_SMU_CLI` | `ryzenSmuCli` | `<toolsRoot>\ryzen-smu-cli\ryzen-smu-cli.exe` | SMU reader/writer |
| `YCRUNCHER_DIR` | `ycruncherDir` | `<toolsRoot>\y-cruncher` | y-cruncher install dir |
| `YCRUNCHER_EXE` | `ycruncherExe` | `<ycruncherDir>\y-cruncher.exe` | stress engine |
| `HWINFO_EXE` | `hwinfoExe` | `<toolsRoot>\HWiNFO\HWiNFO64.exe` | sensor source |
| `MEMPROBE_EXE` | `memprobeExe` | `<artifactRoot>\build\memprobe.exe` | memory probe (you build it) |

`OVERCLOCK_TOOLS_ROOT` is the convenient one: install
`<root>\ryzen-smu-cli\`, `<root>\y-cruncher\`, `<root>\HWiNFO\` and most of the
rest resolves itself.

### Scheduled task

| Env var | Config key | Default | Meaning |
|---|---|---|---|
| `OVERCLOCK_TASK_NAME` | `taskName` | `optimize-co-elevated` | name of the elevated task |

Use a different name if you want more than one configuration registered side by
side.

## Verifying a configuration

```powershell
pwsh -File src/elevated/selftest_paths.ps1
```

```
repo root      C:\...\optimize_system
artifacts      C:\...\optimize_system\artifacts
sessions       C:\...\optimize_system\artifacts\sessions
python         C:\Python312\python.exe                        [ok]
ryzen-smu-cli  C:\Tools\ryzen-smu-cli\ryzen-smu-cli.exe       [ok]
...
missing (excluding artifact dirs, which are created on demand): 0
```

```powershell
python src/common/paths.py
```

Both should show the same Session and Run directories. Artifact directories are
created on demand, so they are reported without an existence check.

## What is *not* configurable, and why

- **The operation surface.** `task_launch.ps1` accepts a fixed set of operations
  (`sweep`, `hwinfo`, `stop-hwinfo`, `resolution`, `accept`, `probe`), each with
  a fixed argument list. The unprivileged side selects one by writing
  `config/co_task_op.json`. This is a security boundary, not a limitation to work
  around: it means an unprivileged caller cannot turn the elevated task into an
  arbitrary-command runner.
- **Job and workload parameters.** These live in `config/co_job_*.json` and
  `config/co_workload_sweep.json`. They are inputs to the operations, not paths,
  so they belong with the operations rather than in `paths.json`.
- **The session-directory layout.** Session names are chosen by the caller; the
  directory structure beneath `artifacts/sessions/` is fixed because the
  watchdog, the archiver and the analysis scripts all rely on it.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `python.exe` resolves and the task exits immediately | `pythonExe` not set; see the `PATH` note above |
| Watchdog says "session not found" right after arming | Python and PowerShell disagree on the artifact root; run both self-tests |
| A `[MISSING]` tool that you know is installed | wrong quote escaping in JSON, or a non-ASCII path and an ANSI-decoded `.ps1` (see [EXTERNAL_DEPENDENCIES.md](EXTERNAL_DEPENDENCIES.md)) |
| Scheduled task reports `Last Result: 1` with an empty log | an unhandled terminating error before logging began; check `artifacts/task_logs/launcher-crash-*.log` |
| `git status` shows thousands of files after a run | `artifacts/` is not being ignored; confirm `.gitignore` is intact |
