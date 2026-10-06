# 第 1 章执行任务：当前 BIOS/系统基线采集与冻结

> **执行状态：已执行，本文档现作为归档任务单保留。不要仅因读取到本文件就再次自动执行第一章采集。**  
> 首次采集：`runs/20260927-013633-chapter1-baseline/`（历史 DDR5-6200 快照）。  
> 当前候选基线：`runs/20260927-204032-chapter1-postupdate-baseline/`（BIOS 7D70v1S3 / 系统报告 1.S3，DDR5-6400）。  
> 最新实际运行由 `runs/CURRENT_RUN.txt` 指向，目前为后续 DDR5-6400 稳定性筛查，不代表本任务需要重跑。

## 执行状态（归档说明）

- BIOS **7D70v1S3 已由用户确认**，系统侧同时报告 1.S3。
- 第一章的系统/传感器基线采集已经完成。
- 仍待人工核对的是无法从 OS/HWiNFO 可靠回读的 BIOS 输入值，例如 PBO/CO/Curve Shaper、CPU VDDIO/MC 的 BIOS 输入来源、EXPO/MCR/Power Down Enable 等。
- 第一章之后已发生 DDR5-6400 CL30 的 y-cruncher VT3 30 分钟筛查；该结果属于后续探索记录，不应把本任务单重新解释为“尚未执行”。

日期：2026-09-27  
项目：Ryzen 7 9700X 超频摸索  
当前章节：第 1 章——现状整理与安全准备

## 0. 任务背景

用户已经确认以下事实：

- CPU：AMD Ryzen 7 9700X
- 主板：MSI MPG X670E CARBON WIFI（MS-7D70）
- BIOS：已升级到 `7D70v1S3`
- CPU 散热：单塔风冷
- 机箱风道：前部 3 进风、顶部 2 出风、尾部 1 出风
- 内存：有直吹风
- Apex 实际使用显卡：RX 7900 XTX
- 2026-09-03、09-04、09-07、09-13 的异常关机记录：均为用户手动操作，不作为超频失稳证据
- FAT32 U 盘：已准备，可用于 BIOS/配置回退
- **重要：本次开机前，用户已经进入 BIOS，将设置恢复到了此前使用的超频配置。当前系统不是 BIOS 默认值。**

路线图中的历史已知设置包括但不限于：
- CO：全核 Negative 20
- Curve Shaper：High/Med +3、High/High +5、Max/Med +5、Max/High +8，其余 Auto
- 内存/FCLK：历史常用 6200/2067
- DRAM VDD/VDDQ：历史为 1.40V
- SoC：近期曾主动设置 1.25V，旧主板稳定组合曾使用 1.20V
- PBO：历史设置/实测对应 125W / 90A / 135A
- CPU 温度墙：历史确认 95°C

**这些只能作为“预期/历史背景”，不能因为用户说“恢复旧设置”就自动认定所有项目当前值完全一致。能读则读，不能可靠读取则标记为待人工核对。**

## 1. 本次目标

建立一份可追溯的“第 1 章当前基线”，明确：

1. 当前实际硬件、BIOS、Windows 与电源计划。
2. 当前系统能从 Windows / HWiNFO / 现有脚本可靠读出的 CPU、内存、FCLK/UCLK、SoC/VDDIO/DRAM 电压、温度等实际读数。
3. 哪些关键 BIOS 设置无法从系统侧可靠读取，形成一份最小人工核对清单。
4. 修正历史事件口径：手动关机不得计入失稳证据。
5. 为第 2 章建立可复用的“冻结基线”。

## 2. 严格限制

本任务是**只读采集**，不是调参任务。

禁止：
- 不修改 BIOS。
- 不改 PBO、CO、Curve Shaper、内存频率、FCLK、时序、电压。
- 不运行 Cinebench、y-cruncher、TM5、OCCT、CoreCycler、FurMark 或任何压力测试。
- 不自动关机、重启。
- 不安装新的超频或压力测试软件。
- 不把读不到的 BIOS 值“根据历史设置推断成当前值”。
- 不把 2026-09-03、09-04、09-07、09-13 的异常关机事件作为稳定性故障证据。

允许：
- 只读 PowerShell/CIM/WMI 查询。
- 读取 Windows 事件日志。
- 读取现有 HWiNFO 数据、共享内存和日志。
- 使用仓库已有 `tools/hwinfo_shared.py`（只读探针见 `tools/read_memory_timings.py`）等只读工具。
- 检查现有本机工具是否存在，但不要因本任务额外下载安装。

## 3. 执行步骤

### 3.1 创建本次记录目录

在 `runs/` 下新建一份第 1 章基线目录，命名建议：

`runs/<YYYYMMDD-HHMMSS>-chapter1-baseline/`

所有新采集文件写入该目录，不覆盖 2026-09-14 的旧数据。

### 3.2 采集系统基线

至少记录：

- 当前日期时间与时区
- CPU 型号、核心/线程
- 主板型号
- BIOS/UEFI 版本（重点确认系统报告为 7D70v1S3 对应版本）
- Windows 版本/Build
- 最近启动时间
- 当前电源计划
- 物理内存条数量、容量、系统报告频率
- GPU 列表与驱动版本
- 当前显示/游戏主显卡只记录用户事实：Apex 使用 RX 7900 XTX；不要仅凭 GPU 枚举顺序推断
- 当前启动以来 WHEA 事件数量
- 近期 Kernel-Power / BugCheck / WHEA 事件摘要

保存为结构化 JSON，例如：
- `system_baseline.json`
- `event_baseline.json`

### 3.3 采集当前运行参数/传感器

优先复用仓库已有 HWiNFO 共享内存能力。

如果 HWiNFO 共享内存可用：
- 保存完整或足够完整的传感器快照
- 重点提取并单独汇总以下项目（以实际可读项目为准）：
  - CPU Tctl/Tdie
  - CCD 温度
  - CPU Package Power / PPT
  - TDC / EDC 使用情况（若能读）
  - CPU Core Voltage / SVI3 相关实际读数
  - SoC Voltage / VSOC
  - CPU VDDIO / MC
  - DRAM VDD
  - DRAM VDDQ
  - Memory Clock
  - UCLK / Memory Controller Clock
  - FCLK / Infinity Fabric Clock
  - 内存 SPD Hub 温度
  - 主板 VRM/MOS 温度
  - RX 7900 XTX 温度/热点/显存温度，仅作空闲基线

如果 HWiNFO 未运行或共享内存不可用：
- 不启动压力测试。
- 可以尝试启动 HWiNFO 的纯传感器模式（前提是本机已有并且无需安装）；如无法安全自动完成，则记录“未采集”，不要伪造。
- 明确记录失败原因。

保存：
- `hwinfo_baseline.json`
- `runtime_summary.json`

### 3.4 识别“系统侧可验证”和“只能 BIOS 人工确认”的项目

输出一个表格，至少覆盖：

| 项目 | 历史/预期值 | 当前系统侧证据 | 状态 |
|---|---:|---|---|
| BIOS 版本 | 7D70v1S3 | 读取结果 | 已确认/异常 |
| PBO PPT | 125 W | 若可读则写 | 已确认/待人工核对 |
| PBO TDC | 90 A | 若可读则写 | 已确认/待人工核对 |
| PBO EDC | 135 A | 若可读则写 | 已确认/待人工核对 |
| CPU 温度墙 | 95°C | 一般难从 OS 可靠确认 | 待人工核对 |
| CO | All Core -20 | 不可靠则不推断 | 待人工核对 |
| Curve Shaper | 历史 +3/+5/+5/+8 | 不可靠则不推断 | 待人工核对 |
| DDR5 频率 | 6200 预期 | HWiNFO/OS 实际 | 已确认/异常 |
| UCLK | 约 3100 MHz 预期 | HWiNFO 实际 | 已确认/待确认 |
| FCLK | 2067 MHz 预期 | HWiNFO 实际 | 已确认/待确认 |
| SoC | 1.25V 或历史 1.20V | HWiNFO 实际 | 仅实际读数，不反推 BIOS 输入 |
| CPU VDDIO | 历史约 1.20V | HWiNFO 实际 | 仅实际读数 |
| DRAM VDD/VDDQ | 1.40V 预期 | HWiNFO 实际 | 已确认/待确认 |
| EXPO Profile | 未冻结 | 若系统侧不能可靠识别 | 待人工核对 |
| MCR | 未冻结 | — | 待人工核对 |
| Power Down Enable | 未冻结 | — | 待人工核对 |
| Boost Override | 未冻结 | — | 待人工核对 |
| Scalar | 未冻结 | — | 待人工核对 |

### 3.5 人工 BIOS 核对清单

对于无法可靠从系统侧读取的项目，生成一份**最小核对清单**，不要让用户把整个 BIOS 拍一遍。

目标是让用户后续只需核对/截图：
- PBO Limits：PPT/TDC/EDC
- CPU Temperature Limit
- Curve Optimizer
- Curve Shaper
- Boost Clock Override
- Scalar
- DDR5 Frequency
- UCLK 模式
- FCLK
- SoC Voltage
- CPU VDDIO/MC
- DRAM VDD
- DRAM VDDQ
- EXPO Profile
- Memory Context Restore
- Power Down Enable
- 用户手工修改过的其他 CPU/内存相关非 Auto 项

### 3.6 事件日志口径修正

在结果中明确写入：

- 2026-09-03：用户手动操作
- 2026-09-04：用户手动操作
- 2026-09-07：用户手动操作
- 2026-09-13：用户手动操作

这些事件即使在 Windows 中出现 Kernel-Power 41 等记录，也不能作为超频不稳定的独立证据。

其余未被用户解释的 WHEA、BugCheck、Unexpected Shutdown 可以保留为“待解释事件”，不要擅自归因于 CPU、内存或显卡。

## 4. 输出文件

本次至少生成：

1. `runs/<本次目录>/system_baseline.json`
2. `runs/<本次目录>/event_baseline.json`
3. `runs/<本次目录>/hwinfo_baseline.json`（若可用）
4. `runs/<本次目录>/runtime_summary.json`
5. `runs/<本次目录>/CHAPTER1_RESULT.md`

并把 `runs/CURRENT_RUN.txt` 更新为本次目录。

## 5. CHAPTER1_RESULT.md 必须包含

### 当前采用的参数
分成两类：
- **已由系统侧读取确认**
- **用户声明已恢复旧超频设置、但尚未人工核对 BIOS 输入值**

不要混写。

### 已有验证依据
- 当前只读系统/传感器采集
- 2026-09-14 历史基线仅作为旧数据参考
- 本任务没有新增任何压力测试结果

### 仍未排除的问题
至少包括：
- CPU 高频轻载/游戏稳定性
- DDR5-6400 稳定性
- FCLK 稳定上限
- 新 BIOS 7D70v1S3 下旧超频参数是否全部按预期生效
- 无法从 OS 可靠读取的 BIOS 设置仍需人工核对

### 第 1 章状态
在人工 BIOS 核对完成前，结论写：
**“第 1 章：基线采集完成，BIOS 关键输入值待人工核对；不得进入第 2 章参数修改。”**

如果本次自动采集连 BIOS 版本/内存实际频率等关键数据都无法取得，则写：
**“第 1 章：未完成。”**

## 6. Git 要求

- 只提交本任务产生的基线文件、结果文件，以及必要的 `runs/CURRENT_RUN.txt` 更新。
- 不删除或覆盖旧测试。
- 不修改超频参数。
- 不因本任务顺手重构 `tools/deadman_watchdog.py` 或其他无关代码。
- 完成后提交到当前分支，并使用清晰 commit message，例如：
  `chapter1: capture current BIOS and runtime baseline`

