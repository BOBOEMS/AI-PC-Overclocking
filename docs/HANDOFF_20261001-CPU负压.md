# 交接文档：CPU 分核负压（Curve Optimizer）—— 2026-10-01

> **注意：这是一份日期为 2026-10-01 的历史交接记录，不是当前说明。**
> 其中的 `tools\...`、`watchdog_sessions\`、`task_logs\` 路径是当时的事实，
> **故意保留未改写**。目录已在 2026-10-02 重构：源码在 `src/`，运行产物在
> `artifacts/`。当前结构与用法见 `README.md`、`docs/ARCHITECTURE.md`、
> `docs/CONFIGURATION.md`。


> 给**新 AI 会话**看的。覆盖 09-30 晚 → 10-01 深夜；机器由用户物理操作、AI 负责测量与记录。**第 4 节④b/④c 是 10-01 傍晚到深夜新增的策略转向与验收结果，先看那两节再回看历史。**
> 阅读顺序：本文 → `AGENT.md`（规程）→ `runs/20260930-191708-cpu-co-find-quick-core0/CPU_CO_RESULT.md`（五轮原始数据）。
> 方法论与章节框架在 `docs/OVERCLOCK_TUNING_ROADMAP.md`，CPU 侧 BIOS 现状见其 **2.2G**（本文第 2 节是它的实测补充）。
> 10-01 新增的三份一手读数：`runs/20261001-144528-cpu-co-sweep-core0-1/` 下的 `CPU_CO_RESULT_ROUND6.md`（第 6 轮分核扫）、`RESOLUTION_CHECK_RESULT.md`（收益分辨率）、`ACCEPTANCE_RESULT_M20_VT3.md`（全核 −20 验收），外加 `ENGINE_AB_RESULT.md`（AVX-512 vs SSE3 温度对照）。

---

## 1. 一句话现状

**策略已从"找最深极限"改为"找甜点"**。10-01 傍晚实测证明：负压的**收益分辨率在约 −10 ~ −20 就耗尽**（0 → −10 买到 +80 MHz，−10 → −20 只多 +5 MHz，−20 → −30 **回退**），所以"逐核往深探"没有边际价值。用户据此拍板：**停在甜点区 −20 → −10**，直接上全核验收。全核 **−20** 的 30 min VT3 24 GiB（用户口径）**已通过**（峰值 Tctl 86.25 ℃、零样本 ≥90 ℃、`VT3: Passed`、WHEA 0），下一次验收按用户决定用 **−15**（判据：峰值 ≤90 ℃ 即冻结 −15）。

机器当前 **SMU margin = BIOS 基线 0**（18:33:06 重启过；`dev reset` 与重启都回 0）。历史那条"−20 崩在 Apex"仍然有效，**Apex 实玩这一项仍未做**。

---

## 2. 当前配置（区分实测与声明）

| 项目 | 值 | 来源 |
|---|---|---|
| CPU | AMD Ryzen 7 9700X，8C/16T，1 CCD / 1 CCX，SMT on | WMI + `ryzen-smu-cli --info` 双重确认 |
| 主板 / BIOS | MSI MPG X670E CARBON WIFI (MS-7D70)，BIOS **1.S3**，Firmware 0B40403B，SMU 98.84.0 | `--info` |
| SMU / PM table | TYPE_CPU4，`SetDldoPsmMargin` via RSMU 0x6；PM version **0x00620105**，size 0x724 | `dev probe` + `--info` |
| FMax / PBO scalar | **5550 MHz** / scalar **1** | `--get-fmax`、`--get-pbo-scalar` |
| 分核 CO | **全核 0** | `rycolab dev probe`（8/8）+ `ryzen-smu-cli --get-offsets-terse`（`0,0,0,0,0,0,0,0`）互相独立印证 |
| Curve Shaper | **默认（未设置）** | 用户声明，**无截图** |
| PBO | Auto | 用户声明，**无截图** |
| 105W 功耗限制 | 已解锁，**具体是哪一项待确认** | 用户声明，**无截图** |
| 内存 | 6400（UCLK 3200）30-38-38-70、**tRFC1 960**（用户 10-01 傍晚改回）、CR 1T、FCLK 2133、SoC 1.28 V、DRAM VDD/VDDQ 1.45、VPP 1.91 | 频率/时序/电压 = **HWiNFO 共享内存实测**（18:41，`runs\20261001-144528-cpu-co-sweep-core0-1\hwinfo_after_trfc960.json`，166 readings）；**tRFC1 960 是用户声明值，不是实测** —— HWiNFO 共享内存不导出 tRFC（`AGENT.md` 第 198 行记过同类缺口，要读 tRFC 只能 ZenTimings） |
| 内存后续 | **用户 10-01 晚声明"内存已冻结，焦点转 CPU"** → 内存相关动作一律记为 **DEFERRED（挂起）**，不再当未决任务推进 | 用户声明 |

**重要前提**：用户已把 BIOS 恢复默认后重调（内存先做完，CPU 只动了 PBO Auto + 解锁 105W），且**已备份 BIOS 方案**。因此 Roadmap 2.2B 里"全核 CO −20 + Curve Shaper 高频高温 +8"那份旧冻结**已不是当前状态**（2.2G 已就地推翻）。

历史锚点仍然有效且**比以前更硬**：那条"全核 −20 → R23 30 min／TM5 15 min 全过，但 Apex 1–2 小时后卡死重启（约 70 ℃、5.3–5.4 GHz）"是在 **CS +8 抬压**的条件下发生的；现在 CS 归默认，同一 −20 只会更不稳。**任何 −20 附近的参数都必须过 Apex 实玩，不能只过跑分。**

**10-01 晚的补注（重要，别把两件事混起来）**：分辨率验证证明的是**"收益"在 −20 以下耗尽**（频率/电压/温度都不再变化），**不等于"负压对稳定性不再有影响"**。历史锚点本身就是证据——全核 −20 跑分全过、却在实玩 1–2 h 后崩，说明**残余的稳定性效应确实存在**。所以正确表述是：用**收益**做判据 → −20 以下不要搜；用**稳定性**做判据 → 理论上仍可继续压，但那必须靠长时全核负载（VT3 / Apex），**不是逐核 sweep 能测的**。详见 `runs/20261001-144528-cpu-co-sweep-core0-1/RESOLUTION_CHECK_RESULT.md` 的判读第 5 条。

---

## 3. 今晚的结论链（含推翻关系，别只看最后一条）

| 轮次 | 做了什么 | 结论 | 状态 |
|---|---|---|---|
| 1 | rycolab quick，仅 core 0 | limit -50 | 被第 3 轮判定为无效测量 |
| 2 | rycolab quick 全 8 核（看门狗守护，71 min，25 runs，WHEA 0） | 8 核全 -50、提案 -45 | **作废**：整段落在无效区 |
| 3 | margin A/B（rycolab 写 + LHM/HWiNFO 读，AVX-512 负载） | 0→-20 有效，-20→-50 不动 | 方向对，仪器单一 |
| 4 | 换第三方仪器复现（`ryzen-smu-cli`，PM-table entry 49 verified Vcore） | 同样形状：1.1967 / 1.1867 / 1.1861 V | 有效，但"饱和"解释被第 5 轮修正 |
| 5 | 轻载高频档 + 92 样本×3 次/档 + 随机顺序 | **0→-20 = +70 MHz（分布不重叠）；-20→-50 仅 +11 MHz（重叠）；Vcore 三档全平** | **当前采用** |
| **6**（10-01 15:45–17:11） | 把搜索搬进有效区：`co-sweep-core0-1-20261001b`，core 0-1，−25 → −5 步长 5，180 s/档 | core 0/1 的 sweep+confirm(1800 s)+soak(600 s) **在 −25 全 CLEAN**，`Positives (0)`、WHEA 0 → **−25 是搜索下界，不是核的极限**，分核差异这一轮没测出来 | **完成，结论否定但信息量大**（`CPU_CO_RESULT_ROUND6.md`） |
| **引擎 A/B**（10-01 17:11–17:28） | 同核、同测试集、同时长的 AVX-512（`24-ZN5 ~ Komari`）vs SSE3（`04-P4P`）单变量对照 | 峰值 **91.00 → 78.75 ℃**；AVX-512 是**双峰**（中位数 78 ℃、22 个样本 ≥90 ℃），SSE3 是**平的**（p90 77.25 ℃）→ 那个 90–93 ℃ 循环是**AVX-512 的单核功耗密度**，不是这颗 CPU 的普遍热行为 | **完成**（`ENGINE_AB_RESULT.md`） |
| **分辨率验证**（10-01 17:34–17:44） | core 0，单变量：margin 0 / −10 / −20 / −30 各 120 s（SSE3 `04-P4P` + `SFTv4`，档间冷却 30 s，每档读回验证） | 频率中位数 **5380 / 5460 / 5465 / 5455 MHz** → 0→−10 **+80 MHz**、−10→−20 只 **+5 MHz**、−20→−30 **−10 MHz 回退**；VID 四档全平 1.35 V、Tctl 全程 ≤1 ℃ 差 → **收益分辨率在 −10 ~ −20 耗尽，不要往深搜** | **完成（EXIT=0）**（`RESOLUTION_CHECK_RESULT.md`） |
| **全核 −20 验收**（10-01 17:49–18:20） | 用户口径：全核 −20 + 30 min **VT3 24 GiB**，看门狗 + HWiNFO 保护（876 样本） | `VT3: Passed`、退出码 0、WHEA 0、无重启；Test Speed **8.67×10⁹ bits/s**；Tctl 峰值 **86.25 ℃**、中位 85.00、**≥90 ℃ 样本 0 个**；SPD Hub 峰值 62.50 ℃；`dev reset` 归零 | **通过**（`ACCEPTANCE_RESULT_M20_VT3.md`）—— 本机第一个够格叫"可用值候选"的读数 |

### 现在成立的四条

1. **CO 写入通路完全有效**，两套互不相关的实现（ZenStates+inpoutx64+LHM ／ ZenStates+PawnIO+PM-table）给出一致结果。
2. 第 4 轮的"-20 饱和"**不是固件钳位，而是接近 FMax 的自然收敛**：轻载已跑到 5503 MHz，离 FMax 5550 只剩 47 MHz。
3. **在轻载高频档，负偏置余量被 boost 换成频率而不是电压**（Vcore 三档都 1.355 V）→ 判据必须用**有效频率**，看电压会得出错误结论。
4. **有用的搜索区间是约 -5 ~ -25**。rycolab 从 -50 起步的 coarse 扫（-50/-40/-30）整段在已被 FMax 吃掉的区域，这就是"8 核全 -50 干净"的成因——**它不是硅强，是预算花错了地方**。

### 10-01 晚修正后的三条（取代上面的搜索策略）

1. **区间下界是 −25，但 −20 以下没有收益分辨率**：继续逐核往深搜，既测不出分核差异，也不涨频率（第 6 轮 + 分辨率验证的合并结论）。
2. **甜点带 ≈ −20 ~ −10**：收益的绝大部分在 −10 就拿到了（+80 MHz），−20 只多 +5 MHz（噪声内），−30 反而回退。**收益峰值在 −20，风险最低在 −10**。
3. **所以缺的不是"更深的 limit"，而是"全核 + 真实工况"的稳定性数据** —— 用户口径的两项：30 min VT3 24 GiB 全核（**已完成，−20 通过**）+ Apex 实玩（**未做**）。

---

## 4. 下一步（按优先级，含确切命令与时长）

> **先读 ④b、④c 两节**：10-01 傍晚策略已从"找最深极限"改为"找甜点"，①里的 `--start -25 --top -5` **不再是当前窗口**，现行窗口是 **−20 → −10**（见 ④b）。

### ① 在有效区间做真正的分核搜索（主线，约 40–70 分钟）

> **状态更新（10-01 晚）**：本节的命令已被 ④b 取代。core 0/1 已在 −25 全过（第 6 轮），分辨率验证又证明 −20 以下没有收益，因此**不要再跑 `--start -25 --top -5`**，改跑 `--start -20 --top -10`。下面的方法学说明（coarseStep、`dev sweep` vs `find` 的取舍、判据）仍然全部有效。

```
rycolab dev sweep --cores 0-7 --start -25 --top -5 --step 5 --seconds 180 --plain
```

- **先做一步，否则白跑**：`rycolab dev plan set coarseStep 5`。粗扫步长取自 `config.coarseStep`（默认 **10**），保持 10 的话 -25 之后直接跳到 -15、-5，**-20／-10 整段不测**，而那正是第 3~5 轮标定出来的有效区。改 5 之后 -25/-20/-15/-10/-5 逐档线性走一遍。
- **`dev sweep` 与 `find` 的取舍**：`find` 的 start/top **不认命令行**（只读 config），且会重建 `rycolab-find-resume` 计划任务；`dev sweep` 两者都干净，所以看门狗模式下走 `dev sweep`。代价：**`dev sweep` 没有自动续跑**，硬重启后 `--resume` 只会重复被打断的那一条 run（之前的核保留），profile 不会被覆盖。
- **判据**：逐核"是否出现计算错误/正例" + 轻载有效频率，**不要看电压**（第 5 轮：轻载档 Vcore 三档全平）
- 提权：走 ② 的计划任务（`tools\co_job_sweep.json` 改参数即可），**不再需要 UAC**
- 跑法建议：先只测 2 个核确认区间选对了，再放开 8 核（本轮就是这么做的）


### ② 免 UAC 的计划任务（用户 10-01 白天拍板：已建）

用户当时要睡了，问的是"能不能自动点 UAC"。**已明确拒绝自动点 UAC**（那是绕过 Windows 同意机制）。正路是注册一个只跑测试脚本的高权限计划任务，之后 `schtasks /run` 触发不再弹框。

**已落地（2026-10-01 14:50），这是整个流程唯一一次 UAC：**

```powershell
# 用户提权执行一次
powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup_uac_free_task.ps1
# 之后 AI 侧固定用（无参数：schtasks /run 不能传参）
'{"op":"sweep"}' | Out-File -Encoding ascii tools\co_task_op.json
schtasks /run /tn optimize-co-elevated
```

- 任务 `optimize-co-elevated`：`InteractiveToken` + `RunLevel=HighestAvailable` + 无时间上限，动作只有 `tools\task_launch.ps1`
- 参数走 JSON 文件，提权侧**先回显全部生效参数再干活**；操作名走 `co_task_op.json`（`schtasks /run` 不能传参）
- 实跑证据：`task_logs\sweep-20261001-150816.log`（`isAdmin=True`）、`hwinfo-20261001-150626.log`（冷启动 9 秒共享内存就绪）

#### ②-1 五个操作（10-01 晚更新：原来是三个）

`tools\task_launch.ps1` 的 `-Op`（以及 `co_task_op.json` 的 `op`）校验白名单是 **`sweep` / `hwinfo` / `stop-hwinfo` / `resolution` / `accept`** 五个：

| 操作 | 参数文件 | 实际干的事 |
|---|---|---|
| `sweep` | `tools\co_job_sweep.json` | `tools\rycolab_controller.py arm` → rycolab dev sweep + 看门狗守护（长任务） |
| `hwinfo` | 无（脚本内搜索 HWiNFO64 路径） | 起 HWiNFO64 并**等到共享内存可用**（顺带自动点过启动画面，见 ②b） |
| `stop-hwinfo` | 无 | 维护用：HWiNFO 是**提权**进程，非提权 `taskkill` 会被拒绝，所以停它必须走提权侧 |
| `resolution` | `tools\co_job_resolution.json` | `tools\resolution_check.py`：频率-收益分辨率测量（0/−10/−20/−30 逐档，见第 3 节） |
| `accept` | `tools\co_job_accept.json` | `tools\rycolab_controller.py accept`：**全核 margin + 用户验收负载**（30 min VT3 24 GiB），见 ④c |

- 五个操作都是**固定参数表 + JSON job 文件**，AI 侧永远不能把任意命令传进提权侧（这是设计目标）
- `accept` 特意**不自己喂心跳**：提权进程不是 AI 会话的子进程，自己喂狗等于让 dead-man 永不触发（与 sweep 拆两侧同理，注释就在 `task_launch.ps1` 里）

#### ②-2 任务现在跑 PowerShell 7（10-01 晚换装，已实跑验证）

| 项 | 值 |
|---|---|
| 解释器 | **`C:\Program Files\PowerShell\7\pwsh.exe`，PSVersion 7.6.6**（由 `setup_uac_free_task.ps1` 自动探测） |
| 动作 | `pwsh.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File tools\task_launch.ps1` |
| 为什么是 Minimized 而**不是** Hidden | 用户报告**火绒拦掉了隐藏窗口的 PowerShell 执行**；而且"可见但最小化"也不会抢正在跑的跑分的焦点。**这是刻意的选择，不要改成 Hidden** |
| 注册脚本 | `tools\setup_uac_free_task.ps1`，自动探测 PS7；带 **`-UseWindowsPowerShell`** 一键回退到 5.1 |
| 换装前验证过的四件事 | ①**无 BOM** 的 UTF-8 脚本 + 中文内容在 PS7 下解码正确；②`$PSNativeCommandUseErrorActionPreference` 默认 **False**；③带 BOM 的脚本同样解码正确；④`-WindowStyle Hidden` 在 PS7 里**其实是可用的**（与早先"PS7 不支持"的猜测相反）——所以 Minimized 是**出于火绒与焦点**，不是因为 Hidden 坏掉 |
| 解析器 | `task_launch.ps1` 在 PS7 **更严格的 parser** 下解析通过 |
| 实跑证据 | `task_logs\resolution-20261001-173406.log` 与 `task_logs\accept-20261001-174944.log` 都打 `powerShell = 7.6.6`（由 `task_launch.ps1` 的 `$PSVersionTable.PSVersion` 落盘） |

**踩过的三个坑（都已修，别再踩）：**

1. **PowerShell 读无 BOM 的 UTF-8 脚本会把中文目录名搞乱** —— `HWiNFO64.exe` 路径里的 `综合检测` 变成 `缁煎悎妫€娴媆`，任务报 `not found`。`tools\*.ps1` 现在统一带 UTF-8 BOM，且 HWiNFO 路径改为在工具目录里**搜索**而不是硬编码。
2. **argv 数组不能穿过 PowerShell 命令行** —— `-RycolabArgs dev sweep --cores 0-1 ...` 会被 PowerShell 当成参数名，报 `NamedParameterNotFound -cores`；重复给同一个参数还会报 `Parameter 'Cores' specified more than once`。现在 workload 描述一律走 JSON（`co_workload_sweep.json`）。
3. **Windows PowerShell 5.1 里 `$ErrorActionPreference='Stop'` 会把原生命令的 stderr 变成终止错误** —— 探测共享内存时那句正常的 `Win32 error 2` 直接把整个 hwinfo 操作打死（任务 `Last Result=1`，日志停在"starting HWiNFO64"）。现在探测改成 `2>$null` + 读退出码，且脚本顶部有全局 `trap`，任何未处理错误都会写 `task_logs\launcher-crash-*.log` 带堆栈。

#### ②-3 停一个正在跑的任务：**暂停计划任务没有用**（10-01 晚实测的教训）

- 在任务计划程序里**"暂停/结束"计划任务，并不会杀掉它已经启动的提权子进程** —— 任务显示 `Last Result=1073807364`（用户观察值），而底下的 rycolab / 负载**仍在跑**
- 正确停法：**用看门狗自己的 `stop` 命令 + 该会话的 session token**，它会①杀掉 workload ②执行 `dev reset` 归零。**不要靠 `taskkill` / 暂停任务来停**
- 这条与 `AGENT.md` 已有的"提权进程不是 AI 会话的子进程"是**同一件事的两个方向**：正因为不是子进程，AI 侧杀不到它；也正因为不是子进程，暂停父任务杀不掉它

诚实的限制：**任务能免掉弹框，但免不掉"AI 会话活着才有人喂狗"**——会话一断，45 秒内看门狗 trip、杀负载、`dev reset` 归零。这是用户自己定的安全语义，不要绕过。

### ②b HWiNFO 启动画面已可自动点过（2026-10-01 修复）

用户反馈"每次启动 HWiNFO 都必须手点开始"。机理与修法：

- HWiNFO 8.34 每次启动都先弹模态启动画面（class `#32770`，`开始` 按钮 **控件 id=1**），**传感器窗口和共享内存都在点击之后才存在**
- **中等完整性进程不能给高完整性窗口发窗口消息**（UIPI，静默丢弃：`SendMessage` 返回得像成功了但什么也没发生）——这就是 14:52 我"点了没反应"的原因；同理从 AI 会话合成鼠标点击也不行
- 修法：**把点击放进提权侧**（`task_launch.ps1` 跑在 HighestAvailable 里），每 3 秒轮询共享内存，发现 `#32770` 可见窗口就 `BM_CLICK` 控件 id=1，最多 20 次
- 实跑证据：`task_logs\hwinfo-20261001-150626.log`（**冷启动**：进程不存在 → 起 → attempt 1 按下 → ~9 秒 `shared memory OK` → `sensors=23 readings=454` → `HWINFO OK`），`launcher-crash-*.log` 0 个


### ②c 温度线：测试用 95/100，验收仍是 ≤90–91 ℃（10-01 定论）

为什么 90 ℃ 那条线在本机不可用、以及 95 ℃ 的代价，定论写在 `runs/20261001-144528-cpu-co-sweep-core0-1/THERMAL_90C_DIAGNOSIS.md`：单核 `24-ZN5 ~ Komari` 每约 180 s 走一轮 90–93 ℃（10 分钟里 10 段连续 ≥90 ℃、每段 8–20 s、峰值 93.00 ℃），−5 与 −25 的循环形状一致 → **与负压深度无关**。据此用户 10-01 拍板：

| 线 | 数值 | 说明 |
|---|---|---|
| **测试线**（本轮 sweep 用） | CPU 停止 **95 ℃** / 紧急 **100 ℃**（`tools\co_job_sweep.json` 的 `cpuTempStop` / `cpuTempEmergency`） | 从 90 提到 95 是用户**明确批准的放宽，不是新默认**；95 ℃ 已是 9700X 的 Tjmax，峰值 93 ℃ 只剩 ~2 ℃ 余量，会频繁擦线 |
| **验收线**（日常/高负载期望） | CPU **≤ ~90 ℃，且从不超过 91 ℃** | 最终 **VT3 24 GiB + Apex 实玩**（第 4 节④c）那一轮必须展示出来的数字 |

两条线是**故意不同的两个数**，写结论时必须说明用的是哪一条。看门狗新增的 `--temp-strikes-required 3`（连续 3 个 ~2 s 样本确认；未达次数的越线写 `thermal_glitch_ignored`）只是收紧**证据门槛**，**并不能**让 90 ℃ 线顶住 8–20 s 的真实循环（自测 `task_logs\selftest_sensor_path.py`）。

**10-01 晚的补充：验收线已经用全核负载实测过一次，结果比预期好得多。** 全核 −20 + 30 min VT3 24 GiB 的 Tctl 是 **85 ℃ 平台 / 峰值 86.25 ℃**，**零个样本 ≥90 ℃**；而单核 AVX-512 那条 90–93 ℃ 的循环在 `ENGINE_AB_RESULT.md` 里被证明是 **AVX-512 单核功耗密度**造成的（同核同时长换 SSE3 只有 78.75 ℃ 峰值）。也就是说：

- **90–93 ℃ 不是"负载重"造成的，是"单核独自 boost 到 5.4 GHz + AVX-512"造成的**（全核时功耗墙把每核频率和电压都压下来，反而更凉：85 ℃ 平台）
- 但**验收线本身不因此放松**——用户的日常工况里仍可能出现单核高 boost 的场景


### ③ 补证据缺口（要用户动手，成本很低）

- 截 `AMD Overclocking` 主页 + PBO 子页 → 存 `bios_photo\bios\`。这张图 Roadmap 追了半个多月，能一次冻结 PBO 具体项、温度墙、Curve Shaper 全格，以及回答"105W 解锁的是哪一项"
- 顺手截 SMUDebugTool v1.41 的 Curve Shaper 屏（软件侧对照）

### ④ 参数验收（有候选值之后）

用户口径：**30 min VT3 24 GiB 全核**（`tools/ycruncher_controller.py` / 提权侧 `tools\rycolab_controller.py accept`）+ **Apex 实玩**。rycolab 的 quick 判据（180 s 单线程）**不能**替代它，这一点已写进 `AGENT.md` 陷阱区。

### ④b 策略转向：**不再找最深极限，改找甜点**（10-01 傍晚，用户拍板）

这是 10-01 最重要的一次方向修正，触发链条是两轮实测：

| 步骤 | 事实 | 出处 |
|---|---|---|
| 第 6 轮 | core 0 与 core 1 **都在 −25 全过**，而 −25 是当时搜索的最深档 | `CPU_CO_RESULT_ROUND6.md` |
| 由此产生的岔路 | "继续往 −30/−40 探" vs "往深探也测不出东西" 两种可能同时成立 | 同上 |
| 分辨率验证 | margin 0 / −10 / −20 / −30 的频率中位数 = **5380 / 5460 / 5465 / 5455 MHz**；VID 四档全平 1.35 V；Tctl 全档差 ≤1 ℃ | `RESOLUTION_CHECK_RESULT.md` |
| 结论 | **0 → −10 买到 +80 MHz；−10 → −20 只多 +5 MHz（噪声内）；−20 → −30 回退 −10 MHz** → 收益分辨率在 −10 ~ −20 耗尽 | 同上 |

**所以第 6 轮的"两颗核都在 −25 干净"不是硅强，而是"第一处干净的 margin"测到的是区间下界（地板），不是核的能力。** 这与第 2 轮"8 核全 −50 干净"是同一个形状的错误的轻量版。

**用户决定：停止追最深极限，改为瞄准甜点。** 性能最优带 ≈ **−20 ~ −10**；再深只增加稳定性风险、不带来任何收益。

**一个必须写清的细微差别**（别让后人误读成"负压对稳定性没影响了"）：

- 在 −20 以下耗尽的是**收益分辨率**（频率/电压/温度），**不是**"负压对稳定性的作用"
- 历史锚点（−20：R23 30 min + TM5 15 min 全过，Apex 1–2 h 后崩）说明**残余的稳定性效应确实存在**
- 所以**纯稳定性搜索理论上仍然可能**，但它**不能拿频率当判据**，只能靠长时全核负载 —— 那是 VT3 / Apex 的活，不是逐核 sweep 的活

**当前逐核窗口改为 −20 → −10**（`tools\co_job_sweep.json`）：

- 两侧包住甜点：某核只扛得住 −15 会在 −20 失败后显形；−20 就干净的核记为"更靠带内"，是好事
- 已在跑的那一轮：session `co-sweet-core2-7-20261001`、campaign `co-sweet-20261001-c2-7`、cores 2-7、`--start -20 --top -10 --step 5 --seconds 180`、`confirmSeconds=300` / `soakSeconds=120`、`sensorSource=hwinfo-shm`、`--no-stream`（不用 ryzen-smu-cli 流 → 无 SMU 争用）；日志 `task_logs\sweep-20261001-184142.log`
- 前一轮 cores 2-3 的 `--start -35 --top -25`（`co-sweep-core2-3-20261001`，日志 `task_logs\sweep-20261001-182118.log`）是还在按"往深探"跑的旧窗口，**已被 ④b 的判断作废**

### ④c 验收结果：**全核 −20 + 30 min VT3 24 GiB 通过**（10-01 17:49–18:20）

**这是本机第一个够格叫"可用值候选"的读数**，完整数据在 `runs/20261001-144528-cpu-co-sweep-core0-1/ACCEPTANCE_RESULT_M20_VT3.md`。

| 判据 | 实测 | 结论 |
|---|---|---|
| 计算错误 | `VT3: Passed`，无 Failed / Checksum Mismatch | 通过 |
| 进程退出 | workload 退出码 0、`state: completed` | 通过 |
| 硬件错误 | WHEA 0 | 通过 |
| 崩溃 / 重启 | 无新 minidump、无重启 | 通过 |
| 温度 | 全程未触发任何停止/紧急线；**Tctl 峰值 86.25 ℃（中位 85.00），≥90 ℃ 样本 0 个** | 通过 |
| 其他温度 | CCD1 峰值 89.88、DIMM SPD Hub 峰值 62.50、另一条 DIMM 59.75、MOS 52.00、GPU 热点 66.00 ℃ | 记录 |
| 收尾 | `dev reset` → `Applied and verified on 8 cores`，读回全 0 | 通过 |

**吞吐对账**：`VT3 Test Speed 8.67 × 10⁹ bits/s`，与历史同量级（30-36-36-72+960 = 6.87×10⁹、30-38-38-70+960 = 9.10×10⁹）→ **说明负载确实按 24 GiB 全核跑满，不是空转通过**。

**一个反直觉但重要的发现（已单独记入 `ACCEPTANCE_RESULT_M20_VT3.md`）**：

> **全核负载比单核 AVX-512 更凉**：单核 `24-ZN5 ~ Komari` 跑出 90–93 ℃ 循环，全核 24 GiB VT3 只有 **85 ℃ 平台**。原因是**功耗墙（105 W 已解锁）把每核频率和电压都压下来**，而单核时那颗核能**独自 boost 到 5.4 GHz + 高压**，功耗密度反而更极端。
>
> → 那个 90–93 ℃ 是**单核功耗密度效应**，不是"负载重"效应。日常游戏/本地 AI 通常既不是单核极限 boost、也不是纯 AVX-512 满载。

**与历史锚点的关系（别误读成"推翻历史"）**：历史那条"全核 −20 崩在 Apex"与本轮不矛盾 —— 历史故障发生在**轻载高频瞬态 + 长热态（5.3–5.4 GHz）且叠着 CS +8 抬压**；本轮是重浮点满载、频率被压低、CS 归默认。**VT3 覆盖不到 Apex 那个工况，所以"VT3 过"不等于"−20 可以日常用"。**

**遗留观察**：DIMM SPD Hub 中位数已达 61.25 ℃、峰值 62.50 ℃，**超过模组自标 55 ℃**（Roadmap 183 行记过同类现象）。本轮用的停止线是 70 ℃、未触发（余量 7.5 ℃），曲线在 61–62 ℃ 收敛成平台而非失控上升。**全核长测的 DIMM 停止线建议压到 58–60 ℃**。

### ④d 下一次验收：用户选定 **−15**（判据先于本轮定死）

用户 10-01 晚的决定：**下轮验收用 −15，不是 −20**。理由与判据如下（`tools\co_job_accept.json` 里逐字记着）：

| 项 | 内容 |
|---|---|
| 为什么 −15 | 收益到 −10 基本吃完（+80 MHz），−20 只多 +5 MHz；而 **−15 离 −30 的回退点更远**，给全核情况留更多余量 |
| **先定判据再跑** | 规则在跑之前就写死：**峰值 CPU ≤90 ℃ 即通过 → 按用户"够用即止"原则冻结 −15 为当前版本** |
| 单核失败怎么办 | 若出现单核失败 → **只把那一颗核下放到 −10**，不是整份 profile 推翻 |
| 负载 | 与 −20 那轮**完全同口径**：30 min VT3 24 GiB 全核 + 看门狗 + HWiNFO 保护（`tools\co_job_accept.json` 的 `session` = `co-accept-m15-vt3-30m-20261001`、`margin` = `-15`） |
| 引擎 | 仓库版 y-cruncher **0.8.5.9543**（历史吞吐出自这个版本，别换成 rycolab 带的 0.8.7） |
| 触发方式 | `tools\task_launch.ps1 -Op accept`（提权侧），AI 侧喂狗 |

### ④e 机器状态与新内存事实（10-01 晚）

- **18:33:06 机器重启过**（`Win32_OperatingSystem.LastBootUpTime` = 2026-10-01 18:33:06；系统日志 18:30:31 的 1074 = 用户主动重启）。**重启后 SMU margin 回到 BIOS 基线 0** —— `dev reset` 与重启都回 0，任何时候想清零都靠这两条
- **tRFC1 被用户改回 960**（原为 700）。这是**用户声明输入，不是实测值**：HWiNFO 共享内存**不导出 tRFC**（`AGENT.md` 第 198 行同类缺口），要读只能靠 ZenTimings 截图
- **18:41 的内存读数**（重启 + 改 tRFC 之后）已落盘：`runs\20261001-144528-cpu-co-sweep-core0-1\hwinfo_after_trfc960.json`，**166 readings**，实测：**Tcas 30 / Trcd 38 / Trp 38 / Tras 70 / Trc 117、Command Rate 1T、UCLK 3200 MHz、FCLK 2133 MHz、SoC 1.28 V、VDD/VDDQ 1.45 V、VPP 1.91 V**
- **用户 10-01 晚声明"内存已冻结，焦点是 CPU"** → 内存侧记为 **DEFERRED（挂起）**，不再作为未决任务推进；第 2 节表格已同步
- 相关日志：`task_logs\hwinfo-20261001-184109.log`（18:41 起 HWiNFO）、`task_logs\sweep-20261001-184142.log`（18:41:42 起甜点窗口 sweep，`co_job_sweep.json` 的 `_note` 也记了"18:33:06 重启 → SMU 是 BIOS 基线、本轮从 0 开始"）

---

## 5. 工具与路径（全部已装好、已验证可用）

| 工具 | 路径 | 状态 |
|---|---|---|
| **ryzen-smu-cli v0.5.0** | `C:\bobo_worktool\ryzen-smu-cli\ryzen-smu-cli.exe` | ✅ 可用。SHA256 `94ecd319a63bb0578f9210ad248c949ba0e0261d0a59cfb41b547115db43833a`（与官方 `checksums-sha256.txt` 一致）。CoreCycler 官方同款 CO 写入器 |
| PawnIO 驱动 | 服务名 `PawnIO`，**Running**，版本 2.2.0.0，DriverStore 里 | ✅ 已装（`PawnIO_setup-v2.2.0.exe` 报"已安装"是正常的，别重装） |
| **rycolab 0.3.0** | 安装 `C:\Users\BOBO\AppData\Local\rycolab\bin\rycolab.exe`；源码 `C:\bobo_worktool\rycolab`（commit `b9fd4d58`） | ✅ 126 个单测全过；`dev calibrate` 在本机 PM 表上**失败**（认不出四个数据块）→ 每核 V/GHz 拿不到，别再用它做电压判据 |
| .NET SDK 9.0.318 | `C:\bobo_worktool\dotnet-sdk-9\dotnet.exe` | ✅ 重装 rycolab 时用：`dotnet publish -c Release -r win-x64 --self-contained true src/Rycolab.Cli` |
| SMUDebugTool v1.41 | `C:\bobo_document\tool\BoostClock\SMUDebugTool_v1.41_20260722` | ✅ 已更新（SHA256 `B55101D7BCC6670BB07CC06B7E7A90BB8C0563C50EFB3FF0166E53E56F839023`），新增 Curve Shaper 试验功能；v1.38 旧目录保留未动。GUI 提权窗口 AI 操作不了，要用户动手 |
| Cinebench R23 | `C:\bobo_document\tool\BoostClock\CinebenchR23_V23.200\Cinebench.exe` | ✅ 存在（跑分对照用） |
| y-cruncher | rycolab 用 `%LOCALAPPDATA%\rycolab\tools\y-cruncher\Binaries`（**0.8.7.9547b**）；仓库控制器用 `C:\bobo_document\tool\BoostClock\y-cruncher v0.8.5.9543`（**0.8.5**） | ⚠️ **两个版本并存，别混**。历史吞吐数字（6.87×10⁹／9.10×10⁹）出自 0.8.5，升级会打断跨轮可比性 |

### 看门狗链路（已实跑验证，可用）

```
提权侧（免 UAC 计划任务）
  schtasks /run /tn optimize-co-elevated        ← 操作名读 tools\co_task_op.json
    └─ tools\task_launch.ps1 -Op sweep
         └─ python tools\rycolab_controller.py arm
              ├─ python tools\deadman_watchdog.py arm --sensor-file <session>\sensor_feed.json
              │    └─ powershell tools\rycolab_workload_elevated.ps1
              │         ├─ ryzen-smu-cli --stream-system-telemetry → <session>\smu_telemetry.jsonl
              │         ├─ python tools\sidecar_sensors.py → <session>\sensor_feed.json
              │         └─ rycolab.exe dev sweep ...（-- 之后的 workload）
              ├─ 反复删除 \rycolab-find-resume 任务；收尾 rycolab dev reset + dev probe
AI 侧    python tools\rycolab_controller.py feed --session <同一个>   （随会话死）
```

**传感器路径（10-01 白天重做，两个坑都在这里）：**

| 事实 | 说明 |
|---|---|
| 看门狗默认不再用 HWiNFO 共享内存 | `--sensor-file` 读 `sidecar_sensors.py` 维护的 `sensor_feed.json`；`--hwinfo-shm` 仍保留 |
| 为什么需要 sidecar | ryzen-smu-cli 的 stdout 是**块缓冲**（4–8 KiB），文件会静止 15–30 秒，尽管流是健康的。直接读原文件会让 `--sensor-stale 15` 误杀（14:55 就发生了一次，见 `attempts/tripped-sensor-stale-20261001/`） |
| 新鲜度语义 | `source_age_seconds` = **距最后一条新 telemetry 行的秒数**（不是文件 mtime）；超过 20 s 就故意报大 → 真正断流才 trip。参数 `--sensor-stale 30` |
| 启动宽限 | 看门狗 `arm` 的首次读数可能早于 sidecar 就绪 → 前 90 秒内允许"文件存在但还没有真读数"，不 refusal |
| 顺带买到 DDR5 保护 | sidecar 从**非提权**侧读 HWiNFO 共享内存（UIPI 不挡读），把 SPD Hub 温度并进同一个文件，所以 70/75 ℃ 停止线是真的在生效 |
| 覆盖范围 | CPU Tctl/Tdie + 每核 APERF/MPERF 有效频率 + DDR5 SPD Hub +（HWiNFO 顺带带来的）GPU/MOS 温度 |

设计说明在 `docs/CO_WATCHDOG_README.md`。`deadman_watchdog.py` 的进程白名单已加入 `rycolab.exe` 与 y-cruncher 引擎二进制（`04-P4P.exe`、`24-ZN5 ~ Komari.exe` 等）。

**为什么两侧拆开**：提权进程不是 AI 会话的子进程，所以喂狗必须留在非提权侧，否则 dead-man 永不触发。

**10-01 晚的补充：`accept` 与 `resolution` 走的是同一套骨架、不同的末端**（五个操作见 ②-1）：

```
tools\task_launch.ps1 -Op resolution  → python tools\resolution_check.py       （逐档写 margin + 测量，收尾归零）
tools\task_launch.ps1 -Op accept      → python tools\rycolab_controller.py accept（全核 margin + 30 min VT3 24 GiB）
```

- 两者都**需要提权**（`ryzen-smu-cli` 要写 SMU），但 **`accept` 不自己喂心跳**：提权进程不是 AI 会话的子进程，自喂会让 dead-man 永不触发（注释就写在 `task_launch.ps1` 的 `'accept'` 分支里）
- `resolution` 的会话 `watchdog_sessions\co-resolution-core0-20261001\` 里落了全量 HWiNFO 原始读数 `hwinfo_raw.jsonl`（302 样本 / 20 MB）、`resolution_levels.json`（含 `resetOk: true`、`readback=0,0,0,0,0,0,0,0`）、`resolution_summary.json`


---

## 6. 提权跑东西的正确姿势（今晚踩过的坑都在这里）

```powershell
# 一次调用只负责启动，不要在同一个调用里轮询
Start-Process -FilePath 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' `
  -Verb RunAs -WindowStyle Hidden `
  -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','<脚本路径>'
```

- `Start-Process -Verb RunAs` **会阻塞等 UAC**。如果和后续轮询写在同一个超时会话里，超时杀掉的正是刚起来的提权子进程（今晚连踩两次，表现为"日志不存在、无进程"）
- 脚本内把输出 `Out-File` 落盘，**AI 从文件读原文判读**，不要靠转述
- **PowerShell 函数参数绝不能叫 `$args`**（自动变量，实参静默丢失）。今晚因此产生一次假成功：四步全变成裸跑 `rycolab`，一秒结束且 `EXIT=0`，监视器还报了"完成"。**先看日志里有没有真正的 workload 行，再看退出码**
- 后台任务默认 10 分钟超时，长任务要传 `timeout: 0`，否则喂狗进程会被按点杀掉 = 自己制造 trip
- 监视器（`monitor_command`）的 stdout 经常捕获不到 → 直接读盘上的 `status.json` / 日志更可靠
- 读 HWiNFO 的 JSON 用 python（`-X utf8`），不要用 PowerShell `ConvertFrom-Json`（GBK 控制台会把中文标签搞乱）

---

## 7. 证据与日志位置

| 内容 | 位置 |
|---|---|
| 五轮完整数据与判读 | `runs/20260930-191708-cpu-co-find-quick-core0/CPU_CO_RESULT.md` |
| **90–93 ℃ 固有热循环定论（10-01）** | `runs/20261001-144528-cpu-co-sweep-core0-1/THERMAL_90C_DIAGNOSIS.md`（10 段 ≥90 ℃ 清单、三次触发原始读数、看门狗 strike 改动；定论会话 `watchdog_sessions/co-plateau2-m5-20261001/`） |
| 本轮 test_plan | 同目录 `test_plan.json` |
| 第 2 轮看门狗归档 | 同目录 `attempts/co-find-all-quick-20261001/`（`events.jsonl`、`status.json`、`workload.stdout.log`、`sensor_samples.jsonl.gz` 5.6 MB、`sensor_summary.json`、脱敏 `*.redacted.json`） |
| 预检 trip 证据 | `watchdog_sessions/preflight-co-trip-20260930/`（未脱敏，不外发） |
| 第 3 轮 A/B | `C:\bobo_worktool\rycolab\ab-margin\`（`ab-margin.log`、`hw_arm*_t*.json`、`cal_arm*.out.txt`、`probe_arm*.json`） |
| 第 4 轮（第三方仪器） | `C:\bobo_worktool\ryzen-smu-cli\read0.log`、`ab2\ab2.log` |
| 第 5 轮（轻载重复采样） | `C:\bobo_worktool\ryzen-smu-cli\ab4-light-repeat\`（`ab4.log` + 9 个 `stream_r*.jsonl`，每个 92 样本） |
| **第 6 轮（分核扫 core 0-1，−25 边界）** | `runs/20261001-144528-cpu-co-sweep-core0-1/CPU_CO_RESULT_ROUND6.md`；归档 `attempts/co-sweep-core0-1-20261001b/`；原始会话 `watchdog_sessions/co-sweep-core0-1-20261001b/`；任务日志 `task_logs/sweep-20261001-154501.log`；campaign `%LOCALAPPDATA%\rycolab\campaigns\co-valid-20261001-core0-1b\` |
| **AVX-512 vs SSE3 温度对照** | `runs/20261001-144528-cpu-co-sweep-core0-1/ENGINE_AB_RESULT.md`；两臂归档 `attempts/engine-ab-avx512-vs-sse3-20261001/co-ab-{zn5,p4p}-20261001/`；工具 `tools/engine_runner.py`、`tools/engine_ab_controller.py`、`task_logs/run_ab_comparison.py`、`task_logs/compare_ab_temperatures.py` |
| **收益分辨率验证** | `runs/20261001-144528-cpu-co-sweep-core0-1/RESOLUTION_CHECK_RESULT.md`；会话 `watchdog_sessions/co-resolution-core0-20261001/`（`hwinfo_raw.jsonl` 302 样本 / 20 MB、`resolution_levels.json`、`resolution_summary.json`）；任务日志 `task_logs/resolution-20261001-173406.log`（`powerShell = 7.6.6`）；分析脚本 `task_logs/analyze_resolution.py`；参数 `tools/co_job_resolution.json` |
| **全核 −20 验收（VT3 24 GiB 30 min）** | `runs/20261001-144528-cpu-co-sweep-core0-1/ACCEPTANCE_RESULT_M20_VT3.md`；会话 `watchdog_sessions/co-accept-m20-vt3-30m-20261001/`（876 样本、`workload.stdout.log`、`events.jsonl`、`status.json`、`probe_before.log` / `probe_after_apply.log` / `probe_after.log`）；任务日志 `task_logs/accept-20261001-174944.log`（`powerShell = 7.6.6`）；工具 `tools/rycolab_controller.py accept`、`tools/co_job_accept.json` |
| **下一个候选（−15）的参数文件** | `tools/co_job_accept.json`（`session` = `co-accept-m15-vt3-30m-20261001`、`margin` = `-15`；判据写在 `_note` 里） |
| **甜点窗口 sweep（core 2-7，−20 → −10）** | 会话 `watchdog_sessions/co-sweet-core2-7-20261001/`；任务日志 `task_logs/sweep-20261001-184142.log`；参数 `tools/co_job_sweep.json`（`_note` 记录了 18:33:06 重启与策略转向） |
| **tRFC1 改回 960 后的内存实测** | `runs/20261001-144528-cpu-co-sweep-core0-1/hwinfo_after_trfc960.json`（18:41，166 readings；Tcas 30 / Trcd 38 / Trp 38 / Tras 70 / Trc 117、CR 1T、UCLK 3200、FCLK 2133、SoC 1.28 V、VDD/VDDQ 1.45、VPP 1.91）；对应任务日志 `task_logs/hwinfo-20261001-184109.log` |
| rycolab 数据库 | `%LOCALAPPDATA%\rycolab\rycolab.db`，查询：`rycolab report find-20260930-1936`、`rycolab db sql "select ..."` |

**作废的 profile**：`%LOCALAPPDATA%\rycolab\profile.json`（那份全核 -45 提案）已挪走为
`C:\bobo_worktool\ryzen-smu-cli\ab-margin\profile.invalid-20261001.json`，防止哪天 `rycolab on` 误用。
**别把它当参数**——它是第 2 轮无效区间的产物。

---

## 8. 回滚与安全

- **重启即回 BIOS 状态**（SMU 写入是 volatile 的，今晚反复验证）。任何时候想清掉负压：重启，或提权跑 `rycolab dev reset` / `ryzen-smu-cli --offset 0:0,1:0,2:0,3:0,4:0,5:0,6:0,7:0`。**10-01 18:33:06 的一次实际重启已验证**：重启后 margin = BIOS 基线 0（`tools\co_job_sweep.json` 的 `_note` 记着这一点）
- **停一个正在跑的提权任务，只能靠看门狗的 `stop` + session token**：在任务计划程序里暂停/结束 `optimize-co-elevated` **不会杀掉它已启动的 rycolab / 负载**（任务显示 `Last Result=1073807364`，而 rycolab 仍在跑 —— 用户 10-01 晚的实测观察）。日志文件本身不记这个 1073807364，是任务计划程序界面上的 `Last Result`。详见第 4 节 ②-3
- 计划任务：`rycolab-guard` 处于 **Disabled**（我们从未 `rycolab on`）；`rycolab-find-resume` 每次 `find` 会重建，看门狗模式下由 `arm` 负责删除——**要重启自动续跑就等于绕开看门狗，别留它**
- 内核驱动 `inpoutx64.sys` / `WinIo32` / PawnIO 被多个工具共用，`rycolab uninstall` 故意不删它们
- 温度红线：**CPU 测试线以第 4 节②c 为准（停止 95 / 紧急 100 ℃，用户 10-01 明确批准的放宽，因为单核固有循环必然摸到 90–93 ℃）；日常验收线是 CPU ≤ ~90 ℃ 且从不超过 91 ℃**。DIMM 停止 70 / 紧急 75 ℃。**注意** Roadmap 183 行记着 **SPD Hub 曾实测 58 ℃，已超过模组自标 high limit 55 ℃**；10-01 的全核 −20 VT3 又把这条推高到 **中位 61.25 / 峰值 62.50 ℃**（停止线 70 ℃ 距触发仅 7.5 ℃，曲线在 61–62 ℃ 收敛成平台）—— **跑全核长测前要先和用户确认是否把 DIMM 停止线压到 58–60 ℃**
- 内存侧：**用户 10-01 晚声明内存已冻结、焦点转 CPU** → 内存相关动作记为 **DEFERRED（挂起）**，不再作为未决任务；tRFC1 现为 **960（用户声明）**，是 18:33 重启之后生效的值

---

## 9. 红线（用户明确要求的做事方式）

1. **零虚构**。每条结论必须能指到一次真实调用与落盘文件；没跑过的就说没跑过。今晚发生过一次严重失信（编造工具输出、编造仓库、编造读回值），用户专门停下来质问，已记进 `AGENT.md`
2. **不 commit / 不 push**，改完留在工作区，用户自己提交
3. **不改 BIOS、不重启、不关机**——改值是用户的物理操作；`--shutdown-on-thermal` 永远不加
4. **不无人值守首试未知高风险配置**；首试必须在场
5. **够用即止**：30 min VT3 通过就冻结为当前版本，不主动加浸泡时长，出问题再回查
6. **单变量**。用户一次改几项时照实记录并写明无法归因，不替他归因
7. **不擅自装软件**（今晚的 rycolab / SMUDebugTool v1.41 / ryzen-smu-cli 都是用户明确批准后才装的）
8. **不写 taste 文件**

---

## 10. 给新会话的开场提示（可直接粘贴）

> 你先读 `docs/HANDOFF_20261001-CPU负压.md`、`AGENT.md`，**重点读交接文档第 4 节 ④b / ④c / ④d 三节**（策略已从"找最深极限"改为"找甜点"，全核 −20 的 30 min VT3 24 GiB 已通过，下一轮验收用户定在 −15、判据是峰值 ≤90 ℃ 即冻结）。原始数据在 `runs/20261001-144528-cpu-co-sweep-core0-1/`（`CPU_CO_RESULT_ROUND6.md`、`RESOLUTION_CHECK_RESULT.md`、`ACCEPTANCE_RESULT_M20_VT3.md`、`ENGINE_AB_RESULT.md`）。**不要再跑 `--start -25 --top -5` 那种往深搜的窗口**，现行逐核窗口是 **−20 → −10**；判据用逐核计算错误，不要看电压，也不要再用 rycolab 默认的 -50 下限。工具、路径、提权脚本模式（PS7 + `-WindowStyle Minimized`，五个操作）、看门狗都已经装好并验证过，见交接文档第 4 节②、第 5、6 节。所有结论要有落盘证据，不许凭印象；改完不要 commit。

---

## 11. 未决问题清单

1. "解锁 105W 功耗限制"具体改了 BIOS 的哪一项？（影响 boost 行为归因）
2. Curve Shaper 是否真的全默认？（无截图，只有声明）
3. 免 UAC 的计划任务要不要建？——**已解决**：10-01 14:50 已建并实跑（`optimize-co-elevated`），见第 4 节②、②b；10-01 晚已扩到五个操作并换装 PS7，见 ②-1 / ②-2
4. 全核长测时 DIMM 停止线用 70 ℃（现有默认）还是压到 58–60 ℃（尊重模组自标）？——**10-01 的 −20 VT3 把 SPD Hub 实测推到中位 61.25 / 峰值 62.50 ℃，比 09 月更硬，建议压到 58–60**
5. 历史那条"−20 崩在 Apex"当时的内存频率/时序是什么？（Roadmap 2.3 记的是 6400／FCLK 2133／SoC 1.20，与今天 SoC 1.28、**tRFC1 960** 不同，跨配置归因要小心）
6. **空闲温度偏高，要不要动散热器？** 0 W 包功率下空闲 Tctl ~59–60 ℃，对风冷 + 20–25 ℃ 环境偏高（`THERMAL_90C_DIAGNOSIS.md` 的选项 C）。**注意 10-01 晚的 `ENGINE_AB_RESULT.md` 已部分缩小怀疑范围**：SSE3 单核负载峰值只有 78.75 ℃ → 散热系统本身能压住这个功耗级别，散热器接触/硅脂**仍是 UNVERIFIED**，但"散热整体不行"已被这条读数削弱
7. **逐核画像仍未完整**：core 0/1 已测（−25 全过，见 `CPU_CO_RESULT_ROUND6.md`）；**core 2-7 正在按甜点窗口（−20 → −10）跑**（session `co-sweet-core2-7-20261001`，`task_logs\sweep-20261001-184142.log`）。**在该轮跑完并写进 `runs/20261001-144528-cpu-co-sweep-core0-1/` 之前，不要引用任何 core 2-7 的 CO 档位或"某核能到多少"**；此前 cores 2-3 那一轮 `--start -35 --top -25`（`co-sweep-core2-3-20261001`）已按 ④b 的判断作废
8. **Apex 实玩仍未做**（用户验收口径的第二项，也是历史故障的复现工况）。VT3 已过，但 VT3 覆盖不到"轻载高频瞬态 + 长热态"那个工况 —— 见 `ACCEPTANCE_RESULT_M20_VT3.md` 的"与历史锚点的对照"
9. **下一轮 −15 验收还没跑**：参数已写在 `tools\co_job_accept.json`（`co-accept-m15-vt3-30m-20261001`），判据也已在跑之前定死（峰值 ≤90 ℃ → 冻结 −15；单核失败 → 只把那颗核下放到 −10）
