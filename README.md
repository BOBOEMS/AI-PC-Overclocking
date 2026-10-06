# Overclock Toolkit — CPU/DRAM 稳定性测试监督框架

**中文** | [English](#english)

一套用于在 Ryzen 平台上运行**无人值守、可产出证据的稳定性测试**的工具。核心想法只有一条：**长时间压测只有在被独立监督时才可信，而它产出的每个数字都必须落盘、事后可查。**

要解决的问题：一台机器能通过 30 分钟压测，却可能在实际使用 2 小时后出问题。这个差距通常不是"测试太短"，而是**测试没有被观察**。如果进程卡死、操作者切走窗口、或者机器硬重启，无人监督的运行记录不下任何有用信息 —— 而一次**软挂**（进程还在、CPU 满载、却永不产出结果）很容易被当成通过。

本工具用**死人开关（dead-man watchdog）**补上这个缺口，并靠区分三样平时被混为一谈的东西来保证实验可复现：

| | |
|---|---|
| **声明的输入** | 你在 BIOS 里敲了什么 |
| **实测的读数** | 硬件通过 SMU / HWiNFO 报了什么 |
| **判定** | 负载实际做了什么，以及支撑它的证据 |

---

## 它能做什么

- **死人开关**（`src/watchdog/deadman_watchdog.py`）—— 把负载放进 Windows **Job Object**，心跳一停就杀掉它。心跳丢失、WHEA 报错、CPU/DIMM 温度越线各自独立触发，并带**连续样本去抖**（单个传感器抖动不会毁掉一次好运行）。
- **Curve Optimizer 控制**（`src/rycolab/rycolab_controller.py`）—— 通过 `rycolab` 部署、喂狗、验收分核负压扫描，然后应用选定的负压并跑验收负载。
- **传感器链路**（`src/watchdog/sidecar_sensors.py`、`src/common/hwinfo_shared.py`）—— 把 `ryzen-smu-cli` 遥测与 HWiNFO 共享内存合并成一路**带新鲜度追踪**的数据流，因为任一来源单独都可能静默卡住。
- **免 UAC 提权**（`src/elevated/`）—— 提权那半边以 `HighestAvailable` 注册成计划任务，用 `schtasks /run` 触发。没有反复的 UAC 弹窗，没有自动点击同意对话框，并且**参数面被刻意收窄**：非提权侧只能在几个预设操作之间选择。
- **内存探针**（`src/bench/memprobe.c`）—— 一个小型 C 基准，测带宽与依赖加载延迟，并**自己打印校验结果**。

## 架构

```
+---------------------------+          +--------------------------------+
|  非提权侧（你 / AI）       |          |  提权计划任务                   |
|                           |          |  (HighestAvailable, 无 UAC)    |
|  写 config/co_task_op     | schtasks |  src/elevated/task_launch.ps1  |
|  -----------------------> | -------> |    -> 操作分发                  |
|                           |   /run   |                                |
|  喂心跳 ----------------- | -------> |  deadman watchdog              |
|  （每 N 秒）               |          |    -> 负载跑在 Job Object 里    |
+---------------------------+          |    -> 心跳缺失即杀掉            |
                                       +--------------------------------+
                                                     |
                                       +--------------------------------+
                                       |  artifacts/sessions/<name>/    |
                                       |    events.jsonl   status.json  |
                                       |    sensor_samples.jsonl        |
                                       |    workload.stdout.log         |
                                       +--------------------------------+
```

这个拆分有两条理由：两半边需要的权限不同；而且**心跳必须来自提权进程树之外**。提权运行无法监督自己 —— 它卡死时，它自己的监督者也一起卡死。所以心跳来自一个**当负载卡住时 Windows 仍能调度**的进程。

## 目录结构

```
.
├── README.md                  本文件（中文 + 英文）
├── AGENT.md                   操作协议 / 硬规矩
├── .gitignore                 所有生成物都在 artifacts/ 下并被忽略
├── config/                    作业与操作参数（跟踪）
│   ├── co_job_accept.json         验收运行参数
│   ├── co_job_sweep.json          扫描参数
│   ├── co_job_resolution.json     频率分辨率参数
│   └── co_workload_sweep.json     扫描用的负载描述
├── docs/                      文档（跟踪）
│   ├── ARCHITECTURE.md            各组件如何拼起来，以及为什么
│   ├── PITFALLS.md                27 个坑：症状 / 成因 / 防护
│   ├── CONFIGURATION.md           每个路径设置与覆盖方式
│   ├── EXTERNAL_DEPENDENCIES.md   第三方工具、来源、许可证
│   ├── EXPERIMENT_LOG.md          参考机器的结果索引
│   └── ...                        方法论与各章节任务书
├── src/                       全部源码（跟踪）
│   ├── common/                    paths.py（唯一真源）、hwinfo_shared、归档
│   ├── watchdog/                  deadman_watchdog、sidecar_sensors
│   ├── rycolab/                   rycolab_controller、engine_runner、engine_ab_controller
│   ├── engines/                   ycruncher_controller、resolution_check
│   ├── elevated/                  paths.ps1、task_launch.ps1、setup_uac_free_task.ps1
│   └── bench/                     memprobe.c + 分析脚本
├── tools/
│   └── migrations/            重构本仓库时用的一次性脚本
└── artifacts/                 全部生成物 —— 不入 git
    ├── sessions/                  看门狗会话证据
    ├── runs/                      每次实验的结果与归档证据
    ├── task_logs/                 启动器 / 计划任务日志
    └── build/                     编译产物（memprobe.exe）
```

维持整洁只有两条规矩：

1. **工具产出的东西**放 `artifacts/`，被忽略。
2. **人写的、别人会需要的东西**放 `src/`、`config/` 或 `docs/`，被跟踪。

## 快速开始

### 1. 安装第三方工具

见 **[docs/EXTERNAL_DEPENDENCIES.md](docs/EXTERNAL_DEPENDENCIES.md)**。简版：`rycolab`、`ryzen-smu-cli`、`y-cruncher`、`HWiNFO64`。

### 2. 告诉工具它们在哪

路径解析顺序是 **环境变量 → 用户配置文件 → 内置默认值**，所以你**不需要改源码**。最省事的做法是写个文件：

```jsonc
// %APPDATA%\overclock-toolkit\paths.json
{
  "pythonExe":    "C:\\Python312\\python.exe",
  "ryzenSmuCli":  "C:\\Tools\\ryzen-smu-cli\\ryzen-smu-cli.exe",
  "ycruncherExe": "C:\\Tools\\y-cruncher\\y-cruncher.exe",
  "hwinfoExe":    "C:\\Tools\\HWiNFO\\HWiNFO64.exe"
}
```

完整键名与其他两种方式：**[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**。

### 3. 验证解析结果

两半边**各自独立**解析路径，而且**必须对同一个会话目录达成一致** —— 否则看门狗找不到控制器部署的会话：

```powershell
pwsh -File src/elevated/selftest_paths.ps1
python src/common/paths.py
```

两者都应报告 `0` 个缺失（artifacts 目录按需创建）。

### 4. 编译内存探针（可选）

```powershell
gcc -O2 -o artifacts/build/memprobe.exe src/bench/memprobe.c
```

### 5. 注册提权任务（一次性，需要点一次 UAC）

```powershell
pwsh -File src/elevated/setup_uac_free_task.ps1
```

之后 `schtasks /run /tn optimize-co-elevated` 就能在**无弹窗**的情况下启动提权那半边。

## 跑一次测试

计划任务**从不接受命令行参数** —— 它从一个文件里读取经过校验的操作名，这样触发命令保持固定、可审查：

```powershell
# 1. 选择操作
'{"op":"hwinfo"}' | Out-File -Encoding ascii config/co_task_op.json
#    可用操作：sweep | hwinfo | stop-hwinfo | resolution | accept | probe

# 2. 触发提权那半边
schtasks /run /tn optimize-co-elevated

# 3. 读它的日志
Get-Content (Get-ChildItem artifacts/task_logs -Filter 'hwinfo-*.log' |
             Sort-Object LastWriteTime | Select-Object -Last 1)

# 4. 负载部署期间，持续喂死人开关的心跳
python src/rycolab/rycolab_controller.py feed --session <name> --interval 8
```

如果第 4 步停了，看门狗会杀掉负载并把 CPU 恢复到基线负压。**这是设计在正常工作，不是故障。**

## 硬规矩

1. **心跳丢失、传感器丢失、或温度越线的运行，记为 `未完成`，永不记为 `通过`。** 只有干净运行才算稳定性证据。
2. **一次只改一个可解释的变量。** 同时改了两项设置的轮次无法归因，并会照此记录。
3. **声明输入、实测读数、判定是三样不同的东西。** 读不到的值写 `未确认`，绝不从历史推断。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 组件设计与背后的推理 |
| [docs/PITFALLS.md](docs/PITFALLS.md) | **27 个坑**：症状/成因/防护 —— 扩展代码前必读 |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | 每个路径设置、解析顺序、覆盖方式 |
| [docs/EXTERNAL_DEPENDENCIES.md](docs/EXTERNAL_DEPENDENCIES.md) | 必需工具的来源链接与许可证 |
| [docs/EXPERIMENT_LOG.md](docs/EXPERIMENT_LOG.md) | 本仓库所基于那台机器的结果索引 |
| [AGENT.md](AGENT.md) | 操作协议，含值得知道的坑 |
| [docs/OVERCLOCK_TUNING_ROADMAP.md](docs/OVERCLOCK_TUNING_ROADMAP.md) | 完整调校方法论 |
| [docs/CO_WATCHDOG_README.md](docs/CO_WATCHDOG_README.md) | Curve Optimizer 监督流程 |

> **说明**：部分文档（`AGENT.md`、`ROADMAP`、`HANDOFF`）以中文撰写，但**命令、路径、代码标识符与实测数值保留原文形式**。核心架构与依赖文档为英文。

## 适用范围与免责

- 面向 **Windows**，且**专为 AMD Ryzen**：SMU 访问路径、Curve Optimizer 语义、HWiNFO 传感器命名都是平台相关的。
- 提权任务模型假设操作者是管理员。它消除的是反复弹出的 UAC **弹窗**，不是"需要提权进程"这件事本身；机器的安全性仍取决于**谁能触发这个任务**。
- `artifacts/runs/` 下的结果文档记录的是**某一台特定机器**。保留它们是作为方法的实例，**不是通用数值**。
- 压测会把硬件推到极限。本工具**不保护**你免受坏设置的影响；它只是让影响**可见并被记录**。请在你愿意承担风险的硬件上使用，并在无人值守运行前先读 `AGENT.md`。

## 许可证

本工具自身代码为 MIT —— 见 [LICENSE](LICENSE)。它会调用第三方程序，那些程序带有**各自的许可证**，其中一些并非宽松许可；分发前请阅读 [docs/EXTERNAL_DEPENDENCIES.md](docs/EXTERNAL_DEPENDENCIES.md)。

---

<a id="english"></a>

# Overclock Toolkit — a supervision harness for CPU/DRAM stability testing

[中文](#overclock-toolkit--cpudram-稳定性测试监督框架) | **English**

Tools for running **unattended, evidence-producing stability tests** on a Ryzen
system, built around one idea: a long stress test is only trustworthy if
something independent is watching it, and every number it produces is written to
disk where it can be checked later.

The motivating problem: a machine that passes a 30-minute stress test can still
fail after two hours of real use. That gap is usually not the test being too
short — it is the test being **unobserved**. If the process hangs, the operator
alt-tabs away, or the machine hard-resets, an unmonitored run records nothing
useful, and a soft hang gets mistaken for success.

This toolkit closes that gap with a dead-man watchdog, and keeps experiments
reproducible by separating three things that are normally conflated:

| | |
|---|---|
| **declared input** | what you typed into BIOS |
| **observed reading** | what the hardware reports over SMU / HWiNFO |
| **verdict** | what the load actually did, with the evidence to back it |

---

## What it does

- **Dead-man watchdog** (`src/watchdog/deadman_watchdog.py`) — runs a workload
  inside a Windows Job Object and kills it unless a heartbeat keeps arriving.
  Independent trips for heartbeat loss, WHEA errors and CPU/DIMM temperature
  limits, with a debounce so one sensor glitch does not abort a good run.
- **Curve Optimizer control** (`src/rycolab/rycolab_controller.py`) — arms, feeds
  and accepts per-core CO margin sweeps through `rycolab`, then applies the
  chosen margin and runs the acceptance load.
- **Sensor plumbing** (`src/watchdog/sidecar_sensors.py`, `src/common/hwinfo_shared.py`)
  — merges `ryzen-smu-cli` telemetry with HWiNFO shared memory into one
  freshness-tracked feed, because either source alone can silently stall.
- **UAC-free elevation** (`src/elevated/`) — the privileged half runs as a
  scheduled task at `HighestAvailable`, triggered by `schtasks /run`. No repeated
  UAC prompt, no auto-clicked consent dialog, and a deliberately narrow argument
  surface: the unprivileged side picks between a few pre-defined operations.
- **Memory probe** (`src/bench/memprobe.c`) — a small C benchmark that measures
  bandwidth and dependent-load latency, and prints its own verification.

## Architecture

```
+---------------------------+          +--------------------------------+
|  non-elevated (you / AI)  |          |  elevated scheduled task       |
|                           |          |  (HighestAvailable, no UAC)    |
|  writes config/co_task_op | schtasks |  src/elevated/task_launch.ps1  |
|  -----------------------> | -------> |    -> operation dispatch       |
|                           |   /run   |                                |
|  feeds heartbeat -------- | -------> |  deadman watchdog              |
|  (every N seconds)        |          |    -> workload in a Job Object |
+---------------------------+          |    -> kills on missed beat     |
                                       +--------------------------------+
                                                     |
                                       +--------------------------------+
                                       |  artifacts/sessions/<name>/    |
                                       |    events.jsonl   status.json  |
                                       |    sensor_samples.jsonl        |
                                       |    workload.stdout.log         |
                                       +--------------------------------+
```

The split exists because the two halves need different privileges, and because
the heartbeat must come from **outside** the elevated process tree. An elevated
run cannot watch itself: if it hangs, so does its own supervisor. The heartbeat
therefore comes from a process Windows can still schedule while the workload is
wedged.

## Layout

```
.
├── README.md                  this file (Chinese + English)
├── AGENT.md                   operating protocol / hard rules
├── .gitignore                 everything generated lives under artifacts/
├── config/                    job and operation parameters (tracked)
│   ├── co_job_accept.json         acceptance-run parameters
│   ├── co_job_sweep.json          sweep parameters
│   ├── co_job_resolution.json     frequency-resolution parameters
│   └── co_workload_sweep.json     workload description for the sweep
├── docs/                      documentation (tracked)
│   ├── ARCHITECTURE.md            how the pieces fit, and why
│   ├── PITFALLS.md                27 traps: symptoms, causes, guards
│   ├── CONFIGURATION.md           every path setting and how to override it
│   ├── EXTERNAL_DEPENDENCIES.md   third-party tools, sources, licences
│   ├── EXPERIMENT_LOG.md          results index for the reference machine
│   └── ...                        methodology and per-chapter task briefs
├── src/                       all source (tracked)
│   ├── common/                    paths.py (single source of truth), hwinfo_shared, archive
│   ├── watchdog/                  deadman_watchdog, sidecar_sensors
│   ├── rycolab/                   rycolab_controller, engine_runner, engine_ab_controller
│   ├── engines/                   ycruncher_controller, resolution_check
│   ├── elevated/                  paths.ps1, task_launch.ps1, setup_uac_free_task.ps1
│   └── bench/                     memprobe.c + analysis scripts
├── tools/
│   └── migrations/            one-shot scripts used to reorganise the tree
└── artifacts/                 EVERYTHING GENERATED — not tracked
    ├── sessions/                  watchdog session evidence
    ├── runs/                      per-experiment results and archived evidence
    ├── task_logs/                 launcher / scheduler logs
    └── build/                     compiled helpers (memprobe.exe)
```

Two rules keep this clean:

1. If the toolkit produced it, it goes under `artifacts/` and is ignored.
2. If a human wrote it and someone else would need it, it goes under `src/`,
   `config/` or `docs/` and is tracked.

## Quick start

### 1. Install the third-party tools

See **[docs/EXTERNAL_DEPENDENCIES.md](docs/EXTERNAL_DEPENDENCIES.md)**. Short
version: `rycolab`, `ryzen-smu-cli`, `y-cruncher`, `HWiNFO64`.

### 2. Tell the toolkit where they are

Paths resolve as **environment variable → user config file → default**, so you
never edit source. The simplest option is a file:

```jsonc
// %APPDATA%\overclock-toolkit\paths.json
{
  "pythonExe":    "C:\\Python312\\python.exe",
  "ryzenSmuCli":  "C:\\Tools\\ryzen-smu-cli\\ryzen-smu-cli.exe",
  "ycruncherExe": "C:\\Tools\\y-cruncher\\y-cruncher.exe",
  "hwinfoExe":    "C:\\Tools\\HWiNFO\\HWiNFO64.exe"
}
```

Full key list and the other options: **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)**.

### 3. Check it resolved correctly

Both halves resolve paths independently and **must agree** on the session
directory, or the watchdog will not find the run the controller armed:

```powershell
pwsh -File src/elevated/selftest_paths.ps1
python src/common/paths.py
```

Both should report `0` missing (artifact directories are created on demand).

### 4. Build the memory probe (optional)

```powershell
gcc -O2 -o artifacts/build/memprobe.exe src/bench/memprobe.c
```

### 5. Register the elevated task (once; needs one UAC click)

```powershell
pwsh -File src/elevated/setup_uac_free_task.ps1
```

After this, `schtasks /run /tn optimize-co-elevated` starts the elevated half
with no prompt.

## Running a test

The scheduled task never accepts a command line — it reads a validated operation
name from a file, so the trigger command stays fixed and inspectable:

```powershell
# 1. choose the operation
'{"op":"hwinfo"}' | Out-File -Encoding ascii config/co_task_op.json
#    ops: sweep | hwinfo | stop-hwinfo | resolution | accept | probe

# 2. trigger the elevated half
schtasks /run /tn optimize-co-elevated

# 3. read its log
Get-Content (Get-ChildItem artifacts/task_logs -Filter 'hwinfo-*.log' |
             Sort-Object LastWriteTime | Select-Object -Last 1)

# 4. while a workload is armed, keep the dead-man switch fed
python src/rycolab/rycolab_controller.py feed --session <name> --interval 8
```

If step 4 stops, the watchdog kills the workload and restores the CPU to its
baseline margin. That is the design working, not a failure.

## Hard rules

1. **A run that lost its heartbeat, lost its sensors, or exceeded temperature is
   `incomplete`, never `passed`.** Only clean runs count as stability evidence.
2. **One explainable variable at a time.** A round that changed two settings
   cannot be attributed, and is recorded as such.
3. **Declared input, observed reading and verdict are different things.** Values
   that cannot be read are written as `unconfirmed`, never inferred from history.

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | component design and the reasoning behind it |
| [docs/PITFALLS.md](docs/PITFALLS.md) | 27 traps with symptoms, causes and guards — read before extending |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | every path setting, resolution order, overrides |
| [docs/EXTERNAL_DEPENDENCIES.md](docs/EXTERNAL_DEPENDENCIES.md) | required tools with source URLs and licences |
| [docs/EXPERIMENT_LOG.md](docs/EXPERIMENT_LOG.md) | results index for the machine this was built on |
| [AGENT.md](AGENT.md) | operating protocol, including pitfalls worth knowing |
| [docs/OVERCLOCK_TUNING_ROADMAP.md](docs/OVERCLOCK_TUNING_ROADMAP.md) | the tuning methodology in full |
| [docs/CO_WATCHDOG_README.md](docs/CO_WATCHDOG_README.md) | Curve Optimizer supervision workflow |

> **Note**: some documents (`AGENT.md`, `ROADMAP`, `HANDOFF`) are written in
> Chinese, with commands, paths, code identifiers and measured values kept in
> their original form. The core architecture and dependency documents are in
> English.

## Scope and caveats

- Written for **Windows** and for **AMD Ryzen** specifically: the SMU access
  path, Curve Optimizer semantics and HWiNFO sensor names are all
  platform-specific.
- The elevated-task model assumes the operator is an administrator. It removes
  the repeated UAC **prompt**, not the requirement for a privileged process; the
  machine's security still rests on who can trigger the task.
- The result documents under `artifacts/runs/` record one particular machine.
  They are kept as worked examples of the method, not as universal numbers.
- Stress testing pushes hardware to its limits. Nothing here protects against bad
  settings; it only makes their effects visible and recorded. Use it on hardware
  you are willing to risk, and read `AGENT.md` before running anything unattended.

## Licence

The toolkit's own code is MIT — see [LICENSE](LICENSE). It calls third-party
programs that carry **their own licences**, some not permissive; read
[docs/EXTERNAL_DEPENDENCIES.md](docs/EXTERNAL_DEPENDENCIES.md) before
redistributing anything.
