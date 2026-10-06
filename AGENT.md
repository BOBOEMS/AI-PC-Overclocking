# AGENT.md — 接手这台机器超频验证的 AI 操作手册

> **目录结构已于 2026-10-02 重构。** 源码全部移入 `src/`，所有运行产物移入
> `artifacts/`（该目录**不入 git**）。本文档中的命令与路径已同步更新；但**第 4 节
> 及更早的历史记录里出现的 `C:\bobo_...` 绝对路径是当时的事实，故意保留不改**，
> 以免篡改历史记录。当前布局见 `README.md`，路径解析见 `docs/CONFIGURATION.md`。


最后更新：2026-10-02（目录重构为 src/ + config/ + artifacts/，路径集中到 paths.py／paths.ps1；新增 git 提交规则与推送授权规则）

上一版：2026-10-01（3.9 起改为「免 UAC 计划任务」入口、传感器走 sidecar；第 4 节新增 PowerShell 5.1 三个坑、SMU 争用、UIPI，以及 90–93 ℃ 固有热循环与「测试线 vs 验收线」两条温度线）。上一版：2026-09-30 新增 3.8 分核负压下发与读回。

## 0. 这个项目是什么

一台具体机器（Ryzen 7 9700X + MSI MPG X670E CARBON WIFI + 2×16GB 光威 DDR5 + RX 7900 XTX）的**超频验证记录仓库**。你的工作不是写软件，而是：**在用户改完 BIOS 后，用受控的压测去证明或推翻一个配置，并把可回溯的证据写进仓库。**

硬件、系统、目标配置见 `README.md`。方法论与章节框架见 `docs/OVERCLOCK_TUNING_ROADMAP.md`。

## 1. 开工前按顺序读

1. **若存在 `docs/HANDOFF_20261001-CPU负压.md`，先读它**——那是 CPU 分核负压这条线最近一次（10-01 凌晨）的交接：当前配置、五轮结论链（含被推翻的）、下一步命令、工具路径、提权脚本模式、未决问题。
2. 本文件（规程）。
3. `docs/OVERCLOCK_TUNING_ROADMAP.md` 的**开头进度行 + 2.2B／2.2C**（冻结的 BIOS 输入，以及之后的实测读数偏差），CPU 侧另看 **2.2G**（10-01 现状，已推翻 2.2B 的 CO／Curve Shaper）。
4. `artifacts/runs/CURRENT_RUN.txt` 指向的 run 里的 `MEMORY_TEST_RESULT.md`（上一轮的真实结论与遗留问题）。
5. 只在需要历史细节时再翻 `docs/CHAPTER1_BASELINE_CAPTURE_TASK.md`、`docs/WATCHDOG_README.md` 和旧 run。

**不要**把仓库里任何数值当成"当前配置"。当前配置只能来自两种来源：用户本轮明确声明的 BIOS 输入，或你自己用 `tools/read_memory_timings.py` 读到的实测值。

## 2. 禁止事项（违反即停手问用户）

- 不改 BIOS、不重启、不关机、不睡眠。改值是用户的物理操作；`--shutdown-on-thermal` 永远不要加，除非用户当轮明确要求。
- 不安装新软件、不下载工具、不动 `C:\bobo_document\tool\` 里的被测程序本体。
- 不把未完成的测试说成通过；不把"能开机"说成"稳定"。
- 不同时改两个变量还声称归因清楚。发现用户一次改了好几项，照实记录，并在结论里写明无法归因。
- 不删、不改已归档的 run 证据。写错的补充用新段落追加，不要重写历史。
- **每一轮文件改动后都要 `git commit`**，不需要等用户开口（2026-10-02 用户明确要求）。
- **`git push` 必须先取得用户当次授权。** 每次推送前单独询问；用户未明确同意就不要推。绝不用 `--force`。
  注意 `artifacts/` 已被忽略（那是刻意的），所以提交内容只含 `src/`、`config/`、`docs/` 等源码与文档。
- 不无人值守跑未知的高风险配置（首试未知值必须有人在场，见 Roadmap 第 5 节）。

## 3. 标准流程

### 3.0 本机工具路径（2026-09-29 核对存在）

| 用途 | 路径 |
|---|---|
| y-cruncher（控制器默认） | `C:\bobo_document\tool\BoostClock\y-cruncher v0.8.5.9543\y-cruncher.exe` |
| TM5 | `C:\bobo_worktool\TB_Tools_202601\tools\内存工具\tm5\TM5.exe`，历史实际参数 `bin\Absolut @ anta777.cfg` |
| Cinebench | `C:\bobo_document\tool\BoostClock\CinebenchR23_V23.200`、`Cinebench2024_win_x86_64` |
| SMUDebugTool（分核负压 GUI） | v1.41 `C:\bobo_document\tool\BoostClock\SMUDebugTool_v1.41_20260722`（09-30 从上游 GitHub 下载，SHA256 `B55101D7BCC6670BB07CC06B7E7A90BB8C0563C50EFB3FF0166E53E56F839023`，新增 Curve Shaper 试验功能）；旧版 v1.38 目录保留未动 |
| **rycolab（分核负压自动搜索＋读回校验）** | 源码 `C:\bobo_worktool\rycolab`（commit `b9fd4d58`，GPL-3.0，本机自编译）；已安装到 `C:\Users\BOBO\AppData\Local\rycolab`；编译用 `C:\bobo_worktool\dotnet-sdk-9\dotnet.exe`（9.0.318） |
| **ZenTimings（读 SPD／密度／tREFI／刷新模式）** | `C:\bobo_worktool\TB_Tools_202601\tools\内存工具\ZenTimings\v140.665\ZenTimings.exe`（09-30 经用户批准下载并校验 sha256） |
| 传感器来源 | HWiNFO64 必须**正在运行且启用共享内存**，否则 `--sensor-required` 会因传感器失联立即中止。10-01 起可用计划任务全自动起（`config\co_task_op.json` 写 `{"op":"hwinfo"}` + `schtasks /run /tn optimize-co-elevated`，会自动点过启动画面），见 3.9 |

**读 SPD 的正确姿势**：HWiNFO 共享内存和 CPU-Z 都**不给出** die 密度／rank／`tRFC1MinNs`；只有 ZenTimings 的 `Tools → Advanced Info → SPD` 给全。但它以管理员权限运行并加载驱动（`inpout64.sys`），**提权后的窗口无法由本会话操作或关闭**——所以要请用户截图（存进 `bios_photo/内存/`），我来读数。退出时它会自动卸载驱动。

跑任何东西前先确认路径与版本存在；不存在就停下问用户，不要自己下载安装。

### 3.1 建 run 目录

```
runs/<yyyyMMdd-HHmmss>-<主题>/
```

主题用可读的短横线命名，例如 `20260929-205719-ddr5-6400-30383870-trfc960`。先写 `test_plan.json`，至少包含：本轮目的、相对上一配置变了什么、`hwinfoAtArm`（实测读数）、`workload`（session 名／测试项／时长／内存容量）、`passCriteria`、`monitoring`（心跳、硬时限、温度停止线）。

### 3.2 记录实测读数（必做）

```bat
python src\common\read_memory_timings.py --out runs\<run>\hwinfo_at_arm.json
```

需要 HWiNFO64 正在运行且启用共享内存。重点核对：内存频率、`Tcas/Trcd/Trp/Tras/Trc/Trfc`、`Command Rate`、UCLK、FCLK、SoC／VDDIO／DRAM VDD／VDDQ／VPP、两条 DIMM 的 SPD Hub 温度。

**这一步的意义**：用户说的 BIOS 输入值经常和实际生效值不一致。09-29 就出现过用户只收了主时序、以为 tRFC 已回退，实际 tRFC1 仍是 960 的情况——读到 960 才能避免重跑一轮已知失败的组合。发现与用户描述不符时，先报告并让用户决定测哪个组合，不要自行改判。

### 3.3 检查内存余量

```bat
powershell -NoProfile -Command "$os=Get-CimInstance Win32_OperatingSystem; [math]::Round($os.FreePhysicalMemory/1MB,2)"
```

`-M:24G` 在 30.9 GB 总容量的机器上只剩不到 1 GB 余量时，先确认能分配再跑长测（y-cruncher 日志里每核都应显示 `100%`）。

### 3.4 预检 → 正式测试

```bat
python src\engines\ycruncher_controller.py <session> --tests VT3 --test-duration 60
python src\engines\ycruncher_controller.py <session> --tests VT3 --test-duration 1800
```

预检的作用：验证 24 GiB 分配、心跳链路、传感器接线，**不作为通过证据**。控制器会：起 `src/watchdog/deadman_watchdog.py arm`（Job Object、`KILL_ON_JOB_CLOSE`、`--sensor-required`、CPU 95/100°C、DIMM 80/85°C、心跳 30 s、硬时限 = 时长 + 300 s），每 8 秒喂一次心跳，每 `--report-interval` 秒打印一行状态。session 名不得与 `artifacts/sessions/` 下已有目录重名。

时长默认沿用 30 分钟 VT3 / 30 分钟 FFT 的筛查强度，除非用户要求变更；改强度要在 `test_plan.json` 里写清楚。**用户 2026-09-30 已定门槛：30 分钟 VT3 通过即作为阶段定版依据，不要主动追加数小时或过夜烤机；真实使用（游戏、双卡多模型长任务）中出现不稳定，再按单变量流程回查。**

### 3.5 判读结果

四种口径必须分清：

| 口径 | 判据 |
|---|---|
| **通过** | `Running <测试>: Passed` + 看门狗 `state: completed` 且退出码 0 + 无新 WHEA + 无温度/心跳/传感器触发 |
| **未通过（计算错误）** | `Failed` / `Checksum Mismatch` / `AlgorithmFailedException` |
| **未通过（系统崩溃）** | 新 `C:\Windows\Minidump\*.dmp`、bugcheck 事件；此时看门狗来不及写任何东西 |
| **未完成** | 心跳失联、传感器失联、温度越线、权限错误（如 `WinError 5`）、人工停止 |

辅助核查：

```bat
python src\watchdog\deadman_watchdog.py status --session <session>
type watchdog_sessions\<session>\events.jsonl
```

`events.jsonl` 的 `armed` 行带 `baseline_whea`；只要没有 WHEA 事件即为无新硬件错误。另查 `C:\Windows\Minidump` 的 mtime 是否晚于本轮开始——09-29 那次 tRFC1 620 直接蓝屏两次，软件看门狗完全没机会记录。

**预判会硬崩的配置（例如 tRFC 逼近已知的蓝屏值），在 arm 之前先把 minidump 清单和本次开机时间写成 run 内的 `pretest_event_baseline.json`。** 硬重启会连同这个会话一起打断，事后只能靠这份基线对账"到底有没有新增崩溃"。09-30 的 tRFC1 700 一轮就是这么确认"通过且无新崩溃"的。

### 3.6 归档

```bat
python src\common\archive_watchdog_session.py <session>
```

默认归档到 `artifacts/runs/CURRENT_RUN.txt` 指向的目录（可 `--run <run>` 指定）。会复制 `events.jsonl`/`status.json`/`workload.*.log`，把 `session.json`/`heartbeat.json` **脱敏 token** 后另存为 `*.redacted.json`，压缩 `sensor_samples.jsonl.gz`，并生成 `sensor_summary.json`（时长、样本数、各受保护温度的 min/max）。

### 3.7 写结论

在同目录写 `MEMORY_TEST_RESULT.md`（内存类）或对应章节的结果文件，结构：状态 → 与上一配置的差异 → 实测读数 → 预检 → 主测 → 性能对照 → 当前采用参数 → **仍未排除的问题** → 下一步与所需用户确认 → 日志位置。然后更新 `artifacts/runs/CURRENT_RUN.txt` 与 Roadmap 的进度行／偏差小节。

**必写项**：与上一已验证配置的确切差异；性能对照（y-cruncher 的 `Test Speed` 可直接比较）；仍未排除的问题要具体（缺哪种负载、缺哪种温度状态、缺哪张截图）。

### 3.8 分核负压（Curve Optimizer）下发与读回（2026-09-30 打通）

用 rycolab。它的关键价值是**每次写入都从 SMU 读回，读回不符就中止**——这正是过去只有 GUI 时做不到的事，也是"下发的值到底生效没有"唯一的硬证据。

| 命令 | 权限 | 作用 |
|---|---|---|
| `rycolab dev probe` | 提权 | 只读，打印每核当前生效 margin |
| `rycolab dev probe --write-test` | 提权 | 把 core 0 自己的值写回自己，验证写通路，不改变任何东西 |
| `rycolab dev apply --margin M --core N` / `--profile` | 提权 | 下发；支持 `--dry-run` |
| `rycolab dev reset [--to N]` | 提权 | 全部回到 `config.json` 里的 baseline |
| `rycolab find [--quick] [--cores 0]` | 提权 | 逐核找极限并提案 profile |
| `rycolab on` / `off` | — | 让隐藏 guard 保持 profile / 回 baseline |
| `rycolab dev log --out x.csv` | 提权 | 跑 Cinebench 时同步采包功率、Tctl、每核有效时钟与核心电压，供跑分前后对照 |

**非交互提权的做法**（本节所有读数都是这么拿到的）：命令写进一个 `.ps1`，用 `Start-Process powershell -Verb RunAs -WindowStyle Hidden -ArgumentList '-NoProfile','-File',<ps1>` 启动，脚本内把输出 `Out-File` 落盘，再从日志文件读原始文本判读。不要靠转述，也不要假设提权窗口里能看到东西。

**09-30 实测**（日志 `C:\bobo_worktool\rycolab\probe-elevated.log`、`wtest-elevated.log`）：

```
CPU AMD Ryzen 7 9700X 8-Core Processor, SMU TYPE_CPU4, 1 CCD / 8 cores / SMT on
SetDldoPsmMargin supported (writes via RSMU 0x6)   FMax 5550
Core 0..7  HARDWARE = 0（Read from hardware: 8 of 8；Applied right now: CCD0 0）
Write test OK (RSMU 0x6, arg 0x00000000)
```

config 的 baseline 因此记为 **0**。这条读数直接推翻了"全核负压档 27 正在生效"的说法：SMU 下发是 volatile 的，重启就回 BIOS 状态；09-30 为校准做的那次重启把 Windows 侧下发的值清掉了，而 BIOS 里的 CO 至今没有截图（见第 4 节）。**遇到这种不一致，按 3.2 的规矩：报告读数、让用户决定测哪个组合，不要自行改判，也不要拿仓库里的档位号当当前生效值。**

**闭环验证**（日志 `C:\bobo_worktool\rycolab\looptest-elevated.log`，全程非交互提权，无需用户点击）：`dev apply --core 0 --margin -3` → `Applied and verified on 1 cores`；`dev probe` → core0 HARDWARE `-3`、其余 `0`、`Applied right now: CCD0 -3/0`；`dev reset` → `-3 -> 0`；再 `dev probe` → 全核回到 `0`。下发、读回、恢复三步都成立，所以"AI 自动跑核负压"这条路可用。

rycolab 只碰分核 margin，不碰 Curve Shaper、PBO limits、全核 offset 和 BIOS。负压下限 Zen4/5 为 -50，正值一律拒绝。`find` 的完整 campaign 是逐核多阶段长时间测量（`--quick` 单核是它文档里的十分钟量级），跑之前必须在场，别无人值守首试。

SMUDebugTool 那条路也留着：它的 exe 里有 `--applyprofile` 与 `profiles\co_profile.txt`（本机字符串实测）；profile 每核一行 `[核号,负数值]`、以及"应用后不会自动退出"这两点来自上游文档，**未在本机实测**。要做无人值守闭环优先用 rycolab。

### 3.9 无人值守跑负压：看门狗链路（2026-09-30 建好；2026-10-01 换计划任务入口 + sidecar 传感器，已实跑）

负压 campaign 必须提权，而**提权进程不是本会话的子进程**，所以不能照搬 `tools/ycruncher_controller.py` 那种"自己启动、自己喂狗"的单进程写法——AI 掉线后心跳照喂，dead-man 永远不触发。拆成两半：

```
提权侧（2026-10-01 起的主路径：免 UAC 计划任务，无参数）
  schtasks /run /tn optimize-co-elevated        ← 操作名读 config\co_task_op.json
    └─ src\elevated\task_launch.ps1                     ← 计划任务唯一的动作；先把生效参数回显进日志
         ├─ -Op hwinfo      → 起 HWiNFO64 + 自动点过启动画面 + 等共享内存可用（见下）
         ├─ -Op stop-hwinfo → 维护用（HWiNFO 是提权进程，非提权 taskkill 会被拒绝）
         └─ -Op sweep       → python src\rycolab\rycolab_controller.py arm
              → src\watchdog\deadman_watchdog.py arm --sensor-file <session>\sensor_feed.json
                   └─ powershell src\elevated\rycolab_workload_elevated.ps1
                        ├─ python src\watchdog\sidecar_sensors.py → <session>\sensor_feed.json
                        └─ rycolab.exe dev sweep ...（`--` 之后的 workload）
              → 收尾 rycolab dev reset + dev probe
AI 侧    python src\rycolab\rycolab_controller.py feed --session <同一个 session>   （随会话一起死）

旧路径（仍在仓库里，保留备用）  src\elevated\co_arm_elevated.ps1 + Start-Process -Verb RunAs
```

**为什么换计划任务**：`Start-Process -Verb RunAs` 每次都要人点 UAC，而"自动点 UAC"是绕过 Windows 同意机制，10-01 已明确拒绝（见 `docs/HANDOFF_20261001-CPU负压.md` 第 4 节②）。`src\elevated\setup_uac_free_task.ps1` 注册一次任务 `optimize-co-elevated`（`InteractiveToken` + `RunLevel=HighestAvailable`、无时间上限），之后 `schtasks /run` 不再弹框。`schtasks /run` 不能传参，所以操作名走 `config\co_task_op.json`、sweep 参数走 `config\co_job_sweep.json`、workload 描述走 `config\co_workload_sweep.json`，提权侧先回显再干活。**诚实的限制**：计划任务免掉的是弹框，**不免**"AI 会话活着才有人喂狗"——会话一断，心跳超时（45 s）内看门狗 trip、杀负载、`dev reset` 归零；这是用户定的安全语义，不要绕过。

**HWiNFO 启动已全自动（2026-10-01 冷启动实测）**：HWiNFO 8.34 每次启动都先开一个模态启动画面（class `#32770`，`开始` 按钮 **控件 id=1**），**传感器窗口和共享内存都在这颗按钮被按下之后才存在**。中等完整性进程不能给高完整性窗口发窗口消息——UIPI 静默丢弃（`SendMessage` 返回得像成功了，其实什么也没发生），合成鼠标点击同理；所以这个点击必须由提权侧的 `task_launch.ps1` 发出：每 3 秒轮询一次共享内存，对 HWiNFO64 的每个可见 `#32770` 对话框 `BM_CLICK` 控件 id=1，最多 20 次。证据 `task_logs\hwinfo-20261001-150626.log`：`starting HWiNFO64` → `attempt 1: dialog(s) [#32770|H] -> pressed start` → `shared memory OK after ~9 s` → `sensors=23 readings=454` → `HWINFO OK`。

**传感器路径（`--sensor-file`）**：看门狗读 `src/watchdog/sidecar_sensors.py` 维护的 `<session>\sensor_feed.json`；sidecar 把 (a) `ryzen-smu-cli` 遥测与 (b) HWiNFO 共享内存合并进同一个持续重写的文件。两个硬碰过的细节：ryzen-smu-cli 的 stdout 是**块缓冲**（4–8 KiB），流健康时文件也会静止 15–30 秒（10-01 14:55 因此误杀过一次健康 run：`sensor source stale for 15.5s`）；新鲜度按**最后一条新 telemetry 行**算，不是文件 mtime（字段 `source_age_seconds`）。`--sensor-source hwinfo-shm` 仍然可用，且**现在是取 CPU 温度的首选**：HWiNFO 的轮询循环不受 SMU 争用影响，覆盖 Tctl/Tdie、CCD1、每核温度、每核频率、包功率、DDR5 SPD Hub、GPU 与 VRM。

**温度触发改为连续样本确认**：`--temp-strikes-required`（默认 **3**）——停止/紧急条件必须连续保持这么多个约 2 秒样本才 trip。未达次数的越线写 `events.jsonl` 的 `thermal_glitch_ignored`（带原始读数），回落写 `thermal_glitch_recovered`，**没有触发是不可见的**。自测 `task_logs\selftest_sensor_path.py`（一个 90.4 ℃ 样本 + strikes=3 **不** trip 且留下 glitch 记录；持续 90.4 ℃ 会 trip）与 `task_logs\selftest_sidecar_path.py`。**注意**：这只是收紧**证据门槛**，并不能单独让 90 ℃ 停止线顶住 8–20 s 的真实热循环（见 4.1）。

启动顺序、默认阈值的理由（心跳 45 s／硬时限 4 h／DIMM 70-75 ℃）、以及为什么宁可"重启即本轮结束"，都写在 `docs/CO_WATCHDOG_README.md`。跑之前必须确认传感器源可用（`hwinfo-shm` 就要 HWiNFO64 在跑且共享内存可用，可先往 `config\co_task_op.json` 写 `{"op":"hwinfo"}` 再 `schtasks /run /tn optimize-co-elevated`），否则 `arm` 以 `refused` 退出——这是设计如此，不要为了跑起来而去掉 `--sensor-required`。

**已验证 / 状态**：两个 .py `py_compile` 通过、`--help` 正常、.ps1 语法解析无误、`deadman_watchdog.py` 的进程白名单已加入 `rycolab.exe` 与 y-cruncher 引擎二进制；计划任务实跑证据 `task_logs\sweep-20261001-150816.log`（`isAdmin=True`）。2026-10-01 傍晚**正在跑** core 0-1 的分核 sweep：session `co-sweep-core0-1-20261001b`、campaign `co-valid-20261001-core0-1b`、`dev sweep --cores 0-1 --start -25 --top -5 --step 5 --seconds 180 --plain`、sensor source `hwinfo-shm`、不跑 SMU 流——**尚无结果，任何逐核 limit 都还没测出来**。

### 3.10 Git 工作流（2026-10-02 用户定版）

```powershell
git add -A
git commit -m "<这一轮改了什么，一句话>"
git status --porcelain    # 应为空；非空说明还有没提交的内容
git log -1 --stat         # 确认提交真的建立、且文件范围正确
```

两条规矩分开记，不要混为一谈：

| 动作 | 是否需要用户同意 |
|---|---|
| `git commit` | **不需要** —— 每轮改动后主动做 |
| `git push` | **需要，且是每一次** —— 推送前单独问 |

`git add -A` 返回成功**不等于**提交已建立，所以提交后必须核对 `git status` 与
`git log -1`。推送前至少确认：分支正确、远端正确、没有意外文件混入。
`artifacts/` 被 `.gitignore` 刻意排除，因此提交里不应出现会话证据、任务日志或
BIOS 截图；若出现，先停下查 `.gitignore` 是否被改动。

## 4. 已知陷阱

> **完整清单见 [`docs/PITFALLS.md`](docs/PITFALLS.md)**（27 条，按"何时会遇到"分组：改代码时／读传感器时／解读数据时／发布仓库时）。写法是「症状 → 成因 → guard」，因为**症状才是你会观察到的现象，而成因几乎总不是最像的那个**。本节只保留本机特有的硬件与数据类陷阱。

- **tRFC 收太紧会硬重启**，不是报错。09-29 实测：tRFC1 620 T（≈193.8 ns；用户 09-30 回忆 BIOS 实际值为 **640**，本仓库记录待订正）开机约 17 秒内两次 bugcheck（`0x1E`、`0xBE`）。本机 16Gb 颗粒的 SPD 下限是 **295 ns = 944 T @6400**，低于它就没有"再压压看"的余地。2026-10-02 曾有一轮 HWiNFO `Trfc` 读到 **920 T**（低于下限 2.5%，属"实测能用"而非"规格内"）。**2026-10-02 15:10 本轮直读已是 960 T**（`artifacts/runs/20261002-151037-vt3-180s-throughput/hwinfo_at_arm.json`），920 不是这次开机后的生效值。tRFC920 的低延迟收益若再试，需要与 960 做同温对照，勿假设它更好。
- **性能不是单调的**。30-36-36-72 + 960 的 VT3 吞吐 6.87 × 10⁹，比放宽到 30-38-38-70 + 960 的 9.10 × 10⁹ 更低且立刻报错——过紧的时序可能触发纠错/重试开销。
- **HWiNFO 标签是中文且控制台按 GBK 输出会乱码**。用 `--out` 落 JSON 文件再看，不要靠 `type` 的输出判断数值。
- **`artifacts/sessions/` 是未脱敏的原始会话**，交付／分享时只引用 `runs/**/attempts/` 里的归档副本。
- **历史 run 里的 `attempts/*.py` 副本可能指向已不存在的路径**（脚本已于 09-29 移入 `src/`）。它们是当时执行过的证据，不要修、不要拿来重跑；重跑一律用 `src/`。
- **2026-09-03／04／07／13 的异常关机是用户手动断电**，不是失稳证据；而 09-29 的两条 minidump 是真崩溃。
- `AMD Overclocking` 子菜单至今没有截图，PBO／CO／Curve Shaper／温度墙只有用户声明，任何内存结论都要带上这个前提。
- **SPD 的 `*MinNs` / `*minPs` 字段分两类，别混用**：`tRFC1MinNs`（本机 = 295 ns）由 die 密度决定、与频率无关，可以当"超规格"判据；而 `tRCDminPs / tRASminPs / tRCminPs / tWRminPs` 只是 **4800 CL40-40-40-77 额定档**折算出的时间，超频时低于它们属正常，**不能拿来当红线**。
- **tREFI 与刷新模式只能从 ZenTimings 读**，HWiNFO 共享内存不导出。09-30 就因此出过一次记录误差：第 1 章按截图冻结 tREFI 46800，实际早已是 65535（tWR、SoC 同步改过），导致跨轮吞吐对比的变量清单不完整。**每轮 arm 时把 ZenTimings 的 tREFI／Refresh／tRFC 读数一并记进 `test_plan.json`。**
- **SMU 下发的分核负压重启就没了**，BIOS 里的值才是开机基线。任何"当前生效多少"只能来自 `rycolab dev probe` 的读回，不能引用仓库里的档位号或上一轮的记录。09-30 就这么发现"档 27 在跑"其实是 0。
- **本会话默认没有管理员权限**（`IsInRole(Administrator)` = False），但可以用隐藏提权窗口 + 日志落盘做到非交互自动化，见 3.8；不要因此放弃闭环，也不要假设"提权就必须用户手动点"。
- **rycolab 的 `install` 会改机器**：`%LOCALAPPDATA%\rycolab\bin`、用户 PATH、下载 y-cruncher 0.8.7（校验 SHA-256）、建 disabled 计划任务 `rycolab-guard`、首次访问 SMU 时装 `inpoutx64.sys` 内核服务（与 ZenTimings／SMUDebugTool 共用）。这些都已经发生过一次，重跑幂等。
- **SMU 回读等于 ≠ 负压真的更深**。10-01 A/B 实测：core 0 写 0 / -20 / -50 都能原值回读，但工作点只在 0→-20 动过（4955→5065 MHz、VDD −8 mV），**-20→-50 频率与电压一位不变**。**第 4 轮已用第三方仪器复现**（`ryzen-smu-cli` v0.5.0，PawnIO + PM-table `0x00620105` entry 49 "verified" Vcore 通道：1.1967 / 1.1867 / 1.1861 V，频率 4950 / 5055 / 5060）→ 本机 **CO 生效饱和点 ≈ -20**，rycolab 以 -50 为下限的 sweep 整段落在死区里，它的"8 核全 -50 干净"不是分核画像。**有效搜索区间是 0 → -20**；任何 CO 结论都要先用 A/B 证明该档位改变了工作点（做法见 `runs/20260930-191708-cpu-co-find-quick-core0/CPU_CO_RESULT.md` 第 3、4 轮）。
- **读每核电压/频率不必依赖 rycolab 的 calibrate**（它在这张表上认不出数据块）。`ryzen-smu-cli --get-vcore` / `--get-cpu-temperature` / `--stream-telemetry` 对本机 PM-table 版本是已验证映射，且 `--get-offsets-terse` 可独立读 margin。
- **判据的频段要对得上**。y-cruncher AVX-512 把频率压在 5.0 GHz，而本机历史故障在 5.3–5.5 GHz 轻载瞬态（Apex 1–2 h）——用重浮点测出来的"干净"覆盖不了出事的那一段。
- **PowerShell 函数里不要把参数命名为 `$args`**——它是自动变量，实参会被静默丢弃。09-30 就因此产生一次**假成功**：包装 rycolab 的 `STEP` 函数用 `$args` 收命令，调用时参数全丢，四步全变成裸跑 `rycolab`，一秒结束且 `EXIT=0`，监视器也跟着报"完成"。写包装脚本一律用 `$cmdArgs` 之类，并且**先看日志里有没有真正的 workload 行，再看退出码**。
- **提权进程不随 AI 会话死**：`Start-Process -Verb RunAs` 起的进程在另一棵进程树里，"父进程没了就停"这条保护对它无效。凡是提权侧的长任务，喂狗必须留在非提权侧（见 3.9）。
- **`Start-Process -Verb RunAs` 会阻塞等 UAC 确认**，如果把它和后续轮询写在同一个超时会话里，超时杀掉的正是刚起来的提权子进程。要么单独一次调用只负责启动，要么改用计划任务。
- **Windows PowerShell 5.1 的三个坑（2026-10-01 各实打实花掉一次实跑）**：
  1. **无 BOM 的 UTF-8 `.ps1` 被 5.1 当 ANSI 读**，中文路径会被搞乱：HWiNFO 路径里的 `综合检测` 变成 `缁煎悎妫€娴媆`，任务直接报 `not found`。`tools\*.ps1` 现在统一带 UTF-8 BOM，且 HWiNFO 路径改为在工具目录里**搜索**而不是硬编码。
  2. **argv 数组不能穿过 PowerShell 命令行**：`--cores` 这类 token 会被绑成参数名（`NamedParameterNotFound -cores`），同一参数重复给还会报 `Parameter 'Cores' specified more than once`。workload 描述现在一律走 JSON（`config\co_workload_sweep.json`），由提权侧读取并回显。
  3. **`$ErrorActionPreference='Stop'` 下原生命令的 stderr 是终止错误**（PS 5.1）：一次正常失败的探测（`Win32 error 2`）就把整个 hwinfo 操作打死（任务 `Last Result=1`，日志停在 `starting HWiNFO64`）。探测现在统一 `2>$null` + 读退出码，`src\elevated\task_launch.ps1` 顶部有全局 `trap`，任何未处理错误写 `task_logs\launcher-crash-*.log` 带堆栈。
- **SMU 争用是一级风险：同时不要跑多于一个 PM 表轮询流**。10-01 白天一个聚合 16 目标流 + 一个 per-core 流互相饿死对方，症状是 `lost sensor monitoring: sensor source stale for 30.1s`，以及 PM 表 Tctl 冻在恒定的 71.38 ℃ 而 HWiNFO 仍在读真实值。该组合已退役；取温度优先 `--sensor-source hwinfo-shm`（HWiNFO 轮询不受 SMU 争用影响）。
- **UIPI：中等完整性进程不能给高完整性窗口（HWiNFO 启动画面）发窗口消息**——`SendMessage` 静默失败（返回得像成功了），合成鼠标点击同样无效。点击必须由提权侧的 `task_launch.ps1 -Op hwinfo` 发出，见 3.9。"点了没反应"不要当成 HWiNFO 卡死。

### 4.1 热约束：90–93 ℃ 固有循环 + 两条故意不同的温度线（2026-10-01 定论）

单核负载 `24-ZN5 ~ Komari` 会周期性冲到 90–93 ℃，这是**本机在该负载口径下的固有散热结果**：不是负压、不是单传感器伪迹、也不是看门狗 bug。定论条件（10 分钟、margin **−5**、冷却后起跑、全程只用 HWiNFO 共享内存）：峰值 **93.00 ℃**、**56 个样本 ≥90 ℃**、**10 段连续 ≥90 ℃（每段 8–20 s）**；周期约 **180 s**，与引擎的 3 个测试（`SecondsPerTest: 60`）对齐（rycolab 的 `susp` 计数稳定爬升＝引擎在测试间反复暂停/恢复，恢复瞬间的单核 boost 是那 ~20 ℃ 跳变的来源）。−5 与 −25 的循环形状/峰值/时刻一致 → 与负压深度无关。完整表格与原始读数在 `runs/20261001-144528-cpu-co-sweep-core0-1/THERMAL_90C_DIAGNOSIS.md`。

| 线 | 数值 | 性质 |
|---|---|---|
| **测试线** | CPU 停止 **95 ℃** / 紧急 **100 ℃** | 用户 2026-10-01 明确批准的**放宽**（从 90 提到 95），因为上述固有循环必然摸到 90–93 ℃。**不是新默认**，参数落在 `config\co_job_sweep.json` |
| **验收线** | CPU **≤ ~90 ℃，且从不超过 91 ℃** | 用户对正常/高负载使用的验收期望；最终 **VT3 24 GiB + Apex 实玩**那一轮必须展示出来 |

两条线是**故意不同的两个数**，写结论时必须说明是哪一条。**仍未排除（UNVERIFIED）**：空闲 Tctl ~59–60 ℃（包功率 0 W）对风冷 + 20–25 ℃ 环境偏高，与"单核就上 93 ℃"同向，指向散热器接触面/硅脂/风道；**未拆装验证，不为此下结论**。

## 5. 重构后的自检记录

2026-09-29 把脚本从仓库根移到 `src/` 后，验证过两条链路，会话留在 `artifacts/sessions/`：

- `restructure-selftest-20260929`：故意不喂心跳，15.1 秒后 `state: tripped`、`shutdown_scheduled: false`，负载子进程被终止。证明死 man 路径在迁移后仍有效。
- `toolmove-selftest-vt3-60s-20260929`：`tools/ycruncher_controller.py` 完整跑 60 秒 VT3 24G，`completed`／退出码 0，传感器读数正常落盘。

迁移同时修掉了一处真实回归：`src/watchdog/deadman_watchdog.py` 原以脚本自身目录为 `WORKSPACE`，移动后会话会落到 `tools/artifacts/sessions/`；现改为 `parents[1]`，会话始终写在仓库根。

## 6. 汇报口径

给用户的话按这个顺序：**当前配置（实测值）→ 这轮跑了什么、多久、结果 → 相对上一版的变化与性能对照 → 仍未排除的问题 → 下一步需要用户做什么（通常就是"去 BIOS 改某一项"**。不要给时间估计，不要把筛查说成稳定验收，不要隐瞒异常或乱码之类的操作细节。
