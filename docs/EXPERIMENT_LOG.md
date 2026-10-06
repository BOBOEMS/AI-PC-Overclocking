# Experiment log — reference machine

> **These numbers describe one specific machine.** They are kept because they are
> worked examples of the method: what was changed, what was measured, and how the
> verdict was reached. They are not universal targets, and they are not a
> recommendation for your hardware.

## The machine

| Item | Value |
|---|---|
| CPU | AMD Ryzen 7 9700X (8 cores / 16 threads), single-tower air cooler |
| Motherboard / BIOS | MSI MPG X670E CARBON WIFI (MS-7D70), `E7D70AMS.1S3` (2026-09-11) |
| Memory | Gloway DDR5 2×16 GB `VGM5UH60C30AG-DVDASM`. SPD read directly: **SK Hynix 16 Gb die, x8, single rank**, `DramStepping 0x4D`. SPD declares **tRFC1 floor 295 ns** (= 944 T at 6400) |
| GPU | XFX RX 7900 XTX + RX 7800 XT + integrated |
| OS | Windows 11 Pro (10.0.26200) |
| Primary use | **local AI**: two GPUs running multiple models concurrently, plus auxiliary models offloaded to CPU; some gaming |

Methodology in full: [OVERCLOCK_TUNING_ROADMAP.md](OVERCLOCK_TUNING_ROADMAP.md).

## Results index

| Run directory | Subject | Verdict |
|---|---|---|
| `20260914-011646` | Pre-chapter-1 baseline batch (R23 / y-cruncher / TM5 / dual-GPU FurMark) | R23 completed at ~20859. y-cruncher FFT passed; VT3 was **aborted by the watchdog** at CCD1 93.4 °C — recorded as **incomplete**, not as a compute error. TM5 never entered an effective working state |
| `20260927-013633-chapter1-baseline` | Chapter 1 read-only baseline capture | Completed; later superseded by the updated capture |
| `20260927-204032-chapter1-postupdate-baseline` | Updated baseline + BIOS screenshot freeze | Completed. The `AMD Overclocking` submenu was **not captured**, so PBO / CO / Curve Shaper remained **user declaration only** |
| `20260927-211448-ddr5-6400-memory-test` | 30-38-38-76, tRFC1 2120, tREFI 46800 | FFT 30 min + VT3 30 min **screening pass**; VT3 8.56 × 10⁹ bits/s. One intermediate abort recorded as `WinError 5` |
| `20260929-013011-ddr5-6400-303672-trfc620` | Same primaries, tRFC1 620 | **Failed**: two blue screens (`0x1E`, `0xBE`) within ~17 s of boot. A software watchdog cannot capture a hard reset — a good example of the architecture's limit |
| `20260929-021041-ddr5-6400-303672-trfc960` | 30-36-36-72 + tRFC1 960 | **Failed**: VT3 `Checksum Mismatch` at 3.027 s, throughput *fell* to 6.87 × 10⁹. Tighter timings made the test both slower and wrong |
| `20260929-205719-ddr5-6400-30383870-trfc960` | 30-38-38-70 + tRFC1 960 | VT3 30 min **passed**, 9.10 × 10⁹ bits/s; peak CPU 81.5 °C / SPD Hub 55.8 °C. Still component screening, not full acceptance |
| `20260930-002633-ddr5-6400-30383870-trfc700` | 30-38-38-70 + tRFC1 700 | VT3 30 min **passed** (9.08 × 10⁹), no new WHEA, no new minidump — but **zero gain over 960**. The refresh-occupancy model puts the ceiling at ~0.5 %. Conclusion: revert to 960; 700 is not a daily-use candidate |
| `20260930-025300-spd-identification` | SPD read-only identification | **SK Hynix / 16 Gb die / x8 / single rank all confirmed by direct SPD read.** `tRFC1MinNs = 295` → floor 944 T at 6400, so **960 is legal and 700 is 25.8 % below the floor**. Also read live `tREFI 65535`, `tWR 60` (chapter 1 recorded 46800 / Auto 72); the difference traces to a 09-29 02:00 change made together with tRFC1 640→960. It does not affect the 960-vs-700 single-variable comparison, but it does make the 09-27 8.56 × 10⁹ baseline non-comparable |
| `20261002-151037-vt3-180s-throughput` | Live 30-38-38-70 + tRFC1 960, 180 s VT3 24 GiB | **Throughput screen pass** (not a 30 min stability claim): `VT3: Passed`, 9.22 × 10⁹ bits/s, watchdog `completed`, WHEA 0, peak Tctl 79.50 °C / SPD Hub 49.75 °C. HWiNFO `Trfc` at arm was **960 T**. First arm attempt refused on a leftover `import hwinfo_shared` after the src/ restructure; that import is now `src.common.hwinfo_shared` |

## Curve Optimizer findings

From the 2026-10-01 session on this machine:

- **Frequency resolution saturates early.** Measuring effective frequency against
  margin: 0 → −10 gained **+80 MHz** (5380 → 5460), −10 → −20 gained **+5 MHz**
  (5465), and −20 → −30 **regressed** (5455). VID stayed flat at 1.35 V and Tctl
  varied by under 1 °C across all levels.
- **What runs out below −20 is the performance benefit, not the stability
  margin.** Historically −20 passed 30 min R23 and 15 min TM5 yet still died
  after 1–2 h of Apex. Those are different questions, and the first does not
  answer the second.
- **Per-core differentiation did not appear inside the sweet band.** Cores 2–7
  swept over −20 → −10 all came back clean with limit −20 and zero failures —
  no core needed a lower value than its neighbours.
- **All-core load ran cooler than single-core AVX-512** (85 °C vs a 90–93 °C
  cycle). The power limit lowers per-core frequency and voltage under all-core
  load, so the 90–93 °C cycle is a single-core power-density effect, not "heavy
  load". This inverted the intuition that a heavier-looking test is the hotter one.
- **BIOS-applied Curve Optimizer cost memory bandwidth.** Measured with
  `memprobe` under a matched thermal protocol (cooldown to a fixed Tctl before
  every sample, 5–6 samples each):

  | Metric | BIOS CO −15 | BIOS CO 0 | Change | Noise floor |
  |---|---|---|---|---|
  | copy | 58.80 GB/s | 61.50 GB/s | **+4.6 %** | 1.5 % |
  | scale | 46.09 GB/s | 48.15 GB/s | **+4.5 %** | 2.1 % |
  | triad | 50.12 GB/s | 53.51 GB/s | **+6.8 %** | 3.5 % |
  | VT3 throughput | 8.760 | 8.720 | −0.46 % | ~0.5 % |

  All three bandwidth figures exceed their noise floor and move together, so the
  effect is real. The plausible mechanism is that a BIOS offset is present
  **during boot-time memory training**, whereas a runtime SMU write happens after
  training completes — which would explain why the same numeric offset behaved
  differently depending on how it was applied. This is an inference, not a
  proven mechanism.

  **VT3 throughput was unaffected**, which is worth stating because an earlier
  single-sample reading suggested a 1.5 % drop. Six samples showed it was scatter.

## Method lessons extracted from this machine

1. **A 14 % throughput swing was caused by a memory setting, not the CPU.** MSI
   *Latency Killer* cost 9.21 → 7.93 × 10⁹ bits/s (13.9 %) while core clocks were
   unchanged (5140 → 5135 MHz, VID identical). Checking what the *CPU* was doing
   located the problem in one step and avoided a much longer investigation of the
   wrong subsystem.
2. **Throughput repeatability must be measured before it is interpreted.** Once
   established at ~1 % for this metric, a 14 % difference is obviously real and a
   0.46 % difference is obviously not.
3. **Thermal state, not just configuration, moves the numbers.** A cool start
   (53.6 °C) produced 9.10 × 10⁹; the same nominal configuration starting at
   62–64 °C produced 8.72–8.76 × 10⁹. Samples taken without a cooldown drifted
   monotonically and produced a 4.2 % within-configuration spread that looked
   like a result.
4. **Single samples mislead.** Two separate conclusions in this session had to be
   retracted after more samples arrived. Report the sample count with every
   number.
