# 分核负压看门狗（rycolab 版）

与内存压测那套（`docs/WATCHDOG_README.md`）同一保护模型，但因为**负压下发必须管理员权限**，进程拓扑被刻意拆成两半。

## 为什么必须拆

`tools/ycruncher_controller.py` 是单进程：自己启动看门狗，也自己喂心跳。控制器随 AI 会话一起死，心跳一断，看门狗就收工——dead-man 成立。

rycolab 不行：它要访问 SMU，只能跑在提权进程里，而**提权进程不是 AI 会话的子进程**（UAC 拉起的是新会话树），随会话死不掉。照搬单进程自喂狗的话，AI 卡死或会话结束后心跳照喂，看门狗永远不会触发，等于没有保护。

## 拓扑

```
提权侧（一次 UAC，长生命周期）
  src\elevated\co_arm_elevated.ps1
    └─ python src\rycolab\rycolab_controller.py arm
         ├─ python src\watchdog\deadman_watchdog.py arm  ── Job Object (KILL_ON_JOB_CLOSE)
         │    └─ rycolab.exe find --quick --cores 0-7 --yes --plain
         │         └─ y-cruncher 引擎二进制（24-ZN5 ~ Komari.exe / 04-P4P.exe）
         ├─ 反复删除 \rycolab-find-resume 计划任务
         └─ 工作负载退出后：rycolab dev reset + rycolab dev probe（落盘）

AI 侧（非提权，随会话死）
  python src\rycolab\rycolab_controller.py feed --session <同一个 session>
```

AI 会话一死 → `feed` 进程被带走 → 心跳过期 → 看门狗杀 rycolab 及其 y-cruncher 子进程（Job Object + 进程名白名单双保险）→ `arm` 收尾执行 `dev reset`，把每核 margin 拉回 baseline 并 `dev probe` 留证。

## 启动

```bat
:: 1) 提权侧（会弹 UAC）
powershell -NoProfile -ExecutionPolicy Bypass -File src\elevated\co_arm_elevated.ps1
::   自定义： -Session 名字 -Cores 0-7 -HeartbeatTimeout 45 -HardTimeout 14400

:: 2) 等 artifacts\sessions\<session>\session.json 出现，再起 AI 侧喂狗
python src\rycolab\rycolab_controller.py feed --session <session> --interval 10 --report-interval 60
```

session 名不得与 `artifacts/sessions/` 下已有目录重名；结束后照常用 `python src\common\archive_watchdog_session.py <session>` 归档。

## 默认阈值的理由

| 参数 | 默认 | 依据 |
|---|---|---|
| `--heartbeat-timeout` | 45 s | 比内存那套的 30 s 宽：`find` 在阶段切换处会连续几十秒只写文件，喂狗间隔 10 s 要留抖动余量 |
| `--hard-timeout` | 14400 s（4 h） | 8 核 quick 的最坏情况是每核走完全档；到点必停，避免"没人看着也一直跑" |
| `--cpu-temp-stop/-emergency` | 90 / 95 ℃ | 深负压的收益就是更高 boost，热是首要代价；9700X 的 Tctl 上限 95 ℃ |
| `--dimm-temp-stop/-emergency` | 70 / 75 ℃ | 内存侧本轮不是变量，但全核 AVX-512 负载会连带主板与 DIMM 升温，不能裸奔 |
| `--sensor-stale` | 15 s | HWiNFO 采样 333 ms，留够容错；**HWiNFO 必须开着并启用共享内存**，否则 `arm` 直接 refused |

`--sensor-required` 是硬要求：拿不到受保护温度就拒绝起跑，不会退化成"只靠心跳"。

## 与 rycolab 自身机制的边界

- rycolab 自带 WHEA／计算错误／进程失联判定，每次 run 后回 baseline；看门狗管的是**它管不到的**：AI 掉线、温度越线、硬超时、进程杀不干净
- **删掉 `rycolab-find-resume` 是有意的**：那任务会在重启后登录时无条件续跑 campaign，正好绕开整套看门狗。因此本方案下"死机重启 = 本轮结束"，要再跑得重新 arm。SMU 写入是 volatile 的，重启后 margin 自动回 BIOS 状态，不会残留深负压
- `rycolab-guard` 计划任务保持 disabled；本方案不用 `rycolab on`，profile 只在测量结束时作为提案存在
- `dev calibrate` 在本机失败（`table version 0x620105`，四个数据块都没认出来），所以报告里的每核 V/GHz 是空的；温度与频率证据改由 HWiNFO 共享内存提供，测量本身不受影响

## 已知代价

`find --quick` 的判据是 1 线程、3 个 test、180 s 一档，**替代不了**仓库既有的 30 min VT3 24 GiB 全核验收。这条链路的定位是"把 8 个核的相对画像摸出来并保证过程可控"，任何参数要日常使用仍须过全核压测。
